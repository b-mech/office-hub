import pytest

from app.services.maintenance.errors import InvalidPhoneError
from app.services.maintenance.phones import format_phone, normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["204 555 1234", "1 204 555 1234", "+1 (204) 555-1234", "(204)555-1234"],
)
def test_normalize_canadian_phone(raw: str) -> None:
    assert normalize_phone(raw) == "+12045551234"


@pytest.mark.parametrize("raw", ["", "204-12", "not a phone", "+999123"])
def test_invalid_phone(raw: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone(raw)


def test_format_phone_for_tenant_message() -> None:
    assert format_phone("+12042598093") == "(204) 259-8093"
