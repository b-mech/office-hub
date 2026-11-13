"""Rentals UX fixes: date-derived lease status, current-lease choice, unit overview,
new-lease defaults, lease-import dry run and report expiry. All read-only / pure."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from openpyxl import Workbook

from app.core.config import settings
from app.main import app
from app.routers.rentals import report_display_status
from app.services.lease_workflow import default_term
from app.services.rental_lease_imports import HEADERS, validate_workbook
from app.services.rental_units import build_roster, lease_display_status, lease_history_entry, pick_leases

TODAY = date(2026, 11, 13)


def lease(lid: int, unit_id: int = 7, status: str = "active", start: date | None = date(2026, 1, 1),
          end: date | None = date(2027, 1, 1)) -> SimpleNamespace:
    return SimpleNamespace(id=lid, unit_id=unit_id, status=status, lease_start=start, lease_end=end,
                           rent=Decimal("1290.00"), rent_discount_amount=None, deposit=None)


@pytest.mark.parametrize(("item", "expected"), [
    (lease(1), "active"),
    (lease(1, end=date(2026, 11, 7)), "expired"),
    (lease(1, end=None), "active"),
    (lease(1, start=date(2026, 12, 1)), "upcoming"),
    (lease(1, status="month_to_month", end=date(2025, 1, 1)), "month_to_month"),
    (lease(1, status="expired", end=date(2024, 5, 31)), "expired"),
    (lease(1, status="terminated"), "terminated"),
    (lease(1, end=TODAY), "active"),
])
def test_lease_display_status_is_derived_from_dates(item, expected) -> None:
    assert lease_display_status(item, TODAY) == expected


def test_lease_display_status_does_not_mutate() -> None:
    item = lease(1, end=date(2026, 11, 7))
    lease_display_status(item, TODAY)
    assert item.status == "active"


def test_current_lease_prefers_in_term_over_newer_past_end_record() -> None:
    # Mirrors staging unit 7: open-ended 2020 lease and a newer record that ended 2026-11-07.
    old_open = lease(6, start=date(2020, 12, 1), end=None)
    newer_past = lease(24, start=date(2026, 10, 8), end=date(2026, 11, 7))
    current, latest = pick_leases([old_open, newer_past], TODAY)
    assert current[7].id == 6 and latest[7].id == 24


def test_current_lease_falls_back_to_past_end_then_upcoming() -> None:
    past = lease(1, start=date(2025, 1, 1), end=date(2026, 1, 1))
    upcoming = lease(2, start=date(2026, 12, 1), end=date(2027, 12, 1))
    assert pick_leases([past, upcoming], TODAY)[0][7].id == 1
    assert pick_leases([upcoming], TODAY)[0][7].id == 2


def test_roster_lease_carries_display_status() -> None:
    unit = SimpleNamespace(id=7, unit_label=None, is_basement=False, status="unknown")
    prop = SimpleNamespace(id=3, street_address="1 Test St", group_name=None, city="Winnipeg")
    rows = build_roster([(unit, prop)], [lease(24, start=date(2026, 10, 8), end=date(2026, 11, 7))], {}, {}, {}, today=TODAY)
    assert rows[0]["lease"]["status"] == "active"
    assert rows[0]["lease"]["display_status"] == "expired"
    assert rows[0]["lease"]["flag"] == "past_end"


def test_lease_history_entry_orders_primary_tenant_first() -> None:
    entry = lease_history_entry(lease(17), [("Zed", False), ("Amy", True)], today=TODAY, current_id=17)
    assert entry["tenants"] == ["Amy", "Zed"] and entry["is_current"] and entry["display_status"] == "active"
    assert entry["net_rent"] == "1290.00"


@pytest.mark.parametrize(("today", "after", "expected"), [
    (date(2026, 11, 13), None, (date(2026, 12, 1), date(2027, 11, 30))),
    (date(2026, 12, 5), None, (date(2027, 1, 1), date(2027, 12, 31))),
    (date(2026, 11, 13), date(2026, 11, 7), (date(2026, 12, 1), date(2027, 11, 30))),
    (date(2026, 11, 13), date(2027, 4, 30), (date(2027, 5, 1), date(2028, 4, 30))),
])
def test_default_term_is_one_year_and_never_in_the_past(today, after, expected) -> None:
    assert default_term(today, after) == expected
    assert expected[0] > today


def _workbook(rows: list[list[object]], headers: list[str] | None = None, sheet: str = "Rent Roll") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers or HEADERS)
    for row in rows:
        ws.append(row + [None] * (len(HEADERS) - len(row)))
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _row(**values: object) -> list[object]:
    data = {h: None for h in HEADERS}
    data.update({"Property Street Address": "166 Clubhouse Drive", "Tenant 1 Name": "Amy Lee", "Rent": 2200,
                 "Lease Start": date(2027, 1, 1), "Lease End": date(2027, 12, 31)})
    data.update({k.replace("_", " "): v for k, v in values.items()})
    return [data[h] for h in HEADERS]


KNOWN = {"166 clubhouse drive": {"", "test"}}


def test_validate_workbook_accepts_clean_rows_and_matches_units() -> None:
    result = validate_workbook("ok.xlsx", _workbook([_row()]), KNOWN)
    assert result["ok"] and result["total_rows"] == 1 and result["rows_ready"] == 1
    assert result["rows"][0]["property_match"] == "existing_unit"
    assert result["rows"][0]["rent"] == "2200.00" and result["rows"][0]["tenant_names"] == ["Amy Lee"]


def test_validate_workbook_flags_row_errors_and_warnings() -> None:
    rows = [
        _row(Rent="abc"),
        _row(**{"Lease Start": date(2027, 5, 1), "Lease End": date(2027, 1, 1)}),
        _row(**{"Property Street Address": None, "Tenant 1 Email": "nope"}),
        _row(**{"Property Street Address": "9 New Rd", "Lease End": None}),
    ]
    result = validate_workbook("bad.xlsx", _workbook(rows), KNOWN)
    assert not result["ok"] and result["rows_with_errors"] == 3 and result["rows_ready"] == 1
    errors = [row["errors"] for row in result["rows"]]
    assert "Rent must be a number" in errors[0]
    assert "Lease End is before Lease Start" in errors[1]
    assert "Property Street Address is required" in errors[2]
    assert any("Email" in e for e in errors[2])
    assert result["rows"][3]["property_match"] == "new_property" and result["rows"][3]["warnings"]


def test_validate_workbook_rejects_wrong_sheet_or_headers() -> None:
    assert validate_workbook("x.xlsx", b"not a zip", KNOWN)["file_errors"]
    assert "Rent Roll" in validate_workbook("x.xlsx", _workbook([], sheet="Other"), KNOWN)["file_errors"][0]
    bad = validate_workbook("x.xlsx", _workbook([], headers=HEADERS[:-1]), KNOWN)
    assert "missing: Notes" in bad["file_errors"][0]
    empty = validate_workbook("x.xlsx", _workbook([]), KNOWN)
    assert not empty["ok"] and "no data rows" in empty["file_errors"][0]


@pytest.mark.asyncio
async def test_upload_dry_run_does_not_write_or_extract(monkeypatch) -> None:
    from app.core.database import get_db
    from app.services import rental_lease_imports

    monkeypatch.setattr(settings, "auth_enforced", False)
    calls: list[str] = []

    class ReadOnlyDb:
        async def execute(self, statement):
            calls.append(str(statement).lstrip().split()[0].upper())
            return SimpleNamespace(all=lambda: [("166 Clubhouse Drive", None)])

        def add(self, *_a):  # pragma: no cover - must never be called
            raise AssertionError("dry run must not add rows")

        async def commit(self):  # pragma: no cover
            raise AssertionError("dry run must not commit")

    async def dep():
        yield ReadOnlyDb()

    async def boom(*_a, **_k):  # pragma: no cover
        raise AssertionError("dry run must not extract")

    monkeypatch.setattr(rental_lease_imports, "upload_and_extract", boom)
    app.dependency_overrides[get_db] = dep
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/rentals/lease-import/upload?dry_run=true",
                                         files={"file": ("rent.xlsx", _workbook([_row()]), "application/octet-stream")})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True and body["ok"] is True and body["rows"][0]["property_match"] == "existing_unit"
    assert calls == ["SELECT"]


def test_report_display_status_expires_without_mutation() -> None:
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    sent = SimpleNamespace(status="sent", expires_at=now - timedelta(minutes=1))
    assert report_display_status(sent, now) == "expired" and sent.status == "sent"
    naive = SimpleNamespace(status="draft", expires_at=(now + timedelta(days=1)).replace(tzinfo=None))
    assert report_display_status(naive, now) == "draft"


def test_unit_overview_route_registered_without_shadowing() -> None:
    paths = [route.path for route in app.routes]
    assert "/api/rentals/units/{unit_id}/overview" in paths
    assert paths.index("/api/rentals/units/roster") < paths.index("/api/rentals/units/{unit_id}/overview")


@pytest.mark.asyncio
async def test_unit_overview_requires_sign_in_when_auth_enforced(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/rentals/units/18/overview")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_lease_passes_start_from_and_rejects_unknown(monkeypatch) -> None:
    from app.core.database import get_db
    from app.routers import lease_agreements
    from app.services import lease_workflow

    monkeypatch.setattr(settings, "auth_enforced", False)
    captured: dict[str, object] = {}

    async def create(db, unit_id, user_id, copy_id, start_from=None):
        if start_from not in (None, "blank", "tenancy"):
            raise ValueError("start_from must be 'blank' or 'tenancy'")
        captured["start_from"] = start_from
        return SimpleNamespace()

    async def admin() -> SimpleNamespace:
        return SimpleNamespace(id="u1")

    async def dep():
        yield SimpleNamespace()

    monkeypatch.setattr(lease_workflow, "create", create)
    monkeypatch.setattr(lease_agreements, "output", lambda lease: {"ok": True})
    app.dependency_overrides[get_db] = dep
    app.dependency_overrides[lease_agreements.editor] = admin
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            ok = await client.post("/api/rentals/leases", json={"unit_id": 18, "start_from": "blank"})
            bad = await client.post("/api/rentals/leases", json={"unit_id": 18, "start_from": "weird"})
    finally:
        app.dependency_overrides.clear()
    assert ok.status_code == 200 and captured["start_from"] == "blank"
    assert bad.status_code == 422
