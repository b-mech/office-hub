from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest
import pdfplumber
from docxtpl import DocxTemplate

from app.models.rentals import RentalProperty
from app.core.config import settings
from app.services import docusign as shared_docusign
from app.services.lease_agreements import build_context, utility_defaults
from app.services.lease_rendering import TEMPLATE, check_pdf, expected_anchors
from app.services.lease_docusign import EMAIL_PATTERN, PHONE_PATTERN, _tabs, structured_contacts

FIXTURE = Path(__file__).parent / "fixtures" / "sample_lease_context.json"


def sample() -> dict:
    return json.loads(FIXTURE.read_text())


def property() -> RentalProperty:
    return RentalProperty(street_address="166 Clubhouse Drive", city="Lorette",
                          municipality="Lorette", is_multiplex=False, is_condo=False)


def test_rent_arithmetic_and_money_format() -> None:
    raw = sample()
    raw.update(basic_rent="2,200", parking_amount="125", other_charge_amount="25.50", rent_discount="100")
    context = build_context(raw, property())
    assert context["rent_payable"] == "2,350.50"
    assert context["actual_rent"] == "2,250.50"
    assert context["unit_address"] == "166 Clubhouse Drive, Lorette, MB"
    assert set(context) == set(sample())


@pytest.mark.parametrize("mutation,error", [
    ({"tenants": []}, "At least one tenant"),
    ({"tenants": [{"name": "A", "email": "bad"}]}, "valid email"),
    ({"tenants": [{"name": "A", "email": "x@example.com"}, {"name": "B", "email": "X@example.com"}]}, "unique"),
    ({"fixed_end": "February 1, 2026"}, "after its start"),
    ({"periodic_start": "March 1, 2026"}, "exactly one"),
    ({"basic_rent": "0"}, "greater than zero"),
    ({"security_deposit_amount": "1,101"}, "Security deposit"),
    ({"pet_deposit_amount": "2,201"}, "Pet deposit"),
    ({"discount_change": "invalid"}, "Invalid discount"),
])
def test_validation(mutation: dict, error: str) -> None:
    raw = sample()
    raw.update(mutation)
    with pytest.raises(ValueError, match=error):
        build_context(raw, property())


def test_periodic_and_renewal_discount() -> None:
    raw = sample()
    raw.update(fixed_start=None, fixed_end=None, periodic_start="2026-03-01", periodic_period="month to month",
               rent_discount="100")
    assert build_context(raw, property())["periodic_start"] == "March 1, 2026"
    with pytest.raises(ValueError, match="Discount change"):
        build_context(raw, property(), renewal=True)
    raw["discount_change"] = "same"
    assert build_context(raw, property(), renewal=True)["discount_change"] == "same"


def test_utility_rules() -> None:
    assert utility_defaults("Winnipeg", False)["utility_exceptions"] is None
    assert utility_defaults("Winnipeg", True)["utility_exceptions"] == "water and sewer"
    assert utility_defaults("Lorette", False)["utility_exceptions"] == "water and sewer"


def test_approved_template_fonts() -> None:
    with ZipFile(TEMPLATE) as docx:
        styles = docx.read("word/styles.xml")
        theme = docx.read("word/theme/theme1.xml")
        document = docx.read("word/document.xml")
    assert b"Liberation Serif" in styles and b"Liberation Serif" in theme
    assert document.count(b'w:ascii="FreeSerif"') == 12
    assert b"Times New Roman" not in styles + theme + document


def test_docusign_tabs_and_capture() -> None:
    landlord = _tabs(0, landlord=True)
    first = _tabs(1)
    other = _tabs(4)
    assert landlord.sign_here_tabs[0].anchor_string == "\\ll_sig\\"
    assert first.sign_here_tabs[0].anchor_string == "\\t1_sig\\"
    assert other.sign_here_tabs[0].anchor_string == "\\t4_sig\\"
    assert first.text_tabs[0].tab_label == "t1_phone"
    assert first.text_tabs[1].tab_label == "t1_email"
    assert first.text_tabs[1].validation_pattern
    assert first.list_tabs[0].tab_label == "t1_pref"
    assert len(first.text_tabs) == 46
    assert len(other.text_tabs) == 2
    captured = structured_contacts({"t1_phone": "2045550100", "t1_pref": "Text",
                                    "ec_r1_c1": "Jane", "ec_r1_c3": "2045550111"},
                                   {"tenants": [{"name": "Devon"}]})
    assert captured["tenants"][0]["phone"] == "2045550100"
    assert captured["emergency_contacts"] == [{"name": "Jane", "relationship": "",
                                               "phone": "2045550111", "email": ""}]


def test_contact_tab_validation() -> None:
    tabs = {tab.tab_label: tab for tab in _tabs(1).text_tabs}
    phone_tabs = {"t1_phone", *(f"oc_r{row}_c4" for row in range(1, 5)),
                  *(f"ec_r{row}_c3" for row in range(1, 3))}
    email_tabs = {"t1_email", *(f"oc_r{row}_c5" for row in range(1, 5)),
                  *(f"ec_r{row}_c4" for row in range(1, 3))}
    assert all(tabs[label].validation_pattern == PHONE_PATTERN for label in phone_tabs)
    assert all(tabs[label].validation_pattern == EMAIL_PATTERN for label in email_tabs)
    assert {tab.tab_label for tab in _tabs(2).text_tabs} == {"t2_phone", "t2_email"}
    assert _tabs(2).text_tabs[0].validation_pattern == PHONE_PATTERN
    assert _tabs(2).text_tabs[1].validation_pattern == EMAIL_PATTERN
    for value in ("2045550100", "(204) 555-0100", "[204] 555 0100", "204-555-0100"):
        assert re.fullmatch(PHONE_PATTERN, value)
    for value in ("204555010", "20455501001", "204555O100", "+1 2045550100", "204.555.0100"):
        assert not re.fullmatch(PHONE_PATTERN, value)
    assert re.fullmatch(EMAIL_PATTERN, "tenant@example.com")
    assert not re.fullmatch(EMAIL_PATTERN, "not-an-email")


@pytest.mark.parametrize("tenant_count", [2, 3, 4])
def test_approved_template_renders_all_anchors(tenant_count: int) -> None:
    context = sample()
    for index in range(3, tenant_count + 1):
        name = f"Tenant {index}"
        context["tenants"].append({"name": name, "email": f"tenant{index}@example.com"})
        context["tenant_names"] += f" & {name}"
    with TemporaryDirectory() as directory:
        target = Path(directory) / "lease.docx"
        template = DocxTemplate(TEMPLATE)
        template.render(context, autoescape=True)
        template.save(target)
        with ZipFile(target) as docx:
            xml = docx.read("word/document.xml").decode()
        assert not re.search(r"\{[{%]", xml)
        for anchor, count in expected_anchors(tenant_count).items():
            assert xml.count(anchor) == count, anchor
        if shutil.which("soffice"):
            import subprocess
            result = subprocess.run(["soffice", "-env:UserInstallation=" + (Path(directory) / "profile").as_uri(),
                                     "--headless", "--convert-to", "pdf", "--outdir", directory, str(target)],
                                    check=False, capture_output=True, text=True, timeout=90)
            assert result.returncode == 0, result.stderr
            pdf_path = target.with_suffix(".pdf")
            check_pdf(pdf_path.read_bytes(), tenant_count)
            if tenant_count == 2:
                with pdfplumber.open(pdf_path) as document:
                    assert len(document.pages) == 8


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError])
@pytest.mark.parametrize("operation", ["client", "change_order"])
def test_unavailable_docusign_key_path_fails_gracefully_without_sdk_or_sensitive_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    error_type: type[OSError], operation: str,
) -> None:
    import builtins

    key_path = tmp_path / "absent-or-unreadable-review-key.pem"
    monkeypatch.setattr(settings, "docusign_private_key_path", str(key_path))
    monkeypatch.setattr(settings, "docusign_private_key", "")
    for field in ("docusign_integration_key", "docusign_user_id", "docusign_account_id"):
        monkeypatch.setattr(settings, field, "unit-test-only")
    assert settings.docusign_configured
    original_open = builtins.open

    def unavailable(path, *args, **kwargs):
        if str(path) == str(key_path):
            raise error_type("sensitive-key-path-detail")
        return original_open(path, *args, **kwargs)

    def forbidden_sdk(*args, **kwargs):
        pytest.fail("DocuSign SDK must not be constructed for unavailable key material")

    monkeypatch.setattr(builtins, "open", unavailable)
    monkeypatch.setattr(shared_docusign, "ApiClient", forbidden_sdk)
    monkeypatch.setattr(shared_docusign, "EnvelopesApi", forbidden_sdk)
    if operation == "client":
        assert shared_docusign.get_docusign_client() is None
    else:
        assert shared_docusign.send_for_signature(
            "unit", "unit", "Unit", "unit@example.invalid", b"unit-test-only",
        ) == (None, None)
    assert error_type.__name__ in caplog.text
    assert "sensitive-key-path-detail" not in caplog.text
    assert str(key_path) not in caplog.text


def test_explicit_docusign_key_path_read_does_not_authenticate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Non-secret bytes deliberately are not a real key and never reach the SDK.
    path = tmp_path / "nonsecret-fixture.txt"
    content = b"non-secret fixture, not authentication material"
    path.write_bytes(content)
    monkeypatch.setattr(settings, "docusign_private_key_path", str(path))
    monkeypatch.setattr(settings, "docusign_private_key", "")

    def forbidden_sdk(*args, **kwargs):
        pytest.fail("Reading a configured path must not authenticate or send")

    monkeypatch.setattr(shared_docusign, "ApiClient", forbidden_sdk)
    monkeypatch.setattr(shared_docusign, "EnvelopesApi", forbidden_sdk)
    assert shared_docusign._private_key_bytes() == content
