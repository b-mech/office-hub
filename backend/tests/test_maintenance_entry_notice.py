from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.maintenance.entry_notice import validate_entry_notice
from app.services.maintenance.errors import EntryNoticeError


TZ = ZoneInfo("America/Winnipeg")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=TZ)


def test_notice_inside_window_and_after_minimum() -> None:
    assert validate_entry_notice(
        NOW + timedelta(hours=25), NOW, entry_permission="denied", is_emergency=False
    ) == "notice_required"


def test_notice_rejects_too_soon() -> None:
    with pytest.raises(EntryNoticeError, match="minimum"):
        validate_entry_notice(
            NOW + timedelta(hours=23), NOW, entry_permission="not_asked", is_emergency=False
        )


def test_notice_rejects_outside_window() -> None:
    with pytest.raises(EntryNoticeError, match="window"):
        validate_entry_notice(
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            NOW,
            entry_permission="denied",
            is_emergency=False,
        )


def test_permission_emergency_and_admin_bypasses() -> None:
    too_soon = NOW + timedelta(hours=1)
    assert validate_entry_notice(too_soon, NOW, entry_permission="granted", is_emergency=False) == "permission_granted"
    assert validate_entry_notice(too_soon, NOW, entry_permission="denied", is_emergency=True) == "emergency_bypass"
    assert validate_entry_notice(
        too_soon,
        NOW,
        entry_permission="denied",
        is_emergency=False,
        admin_override_reason="Tenant requested this time by phone",
    ) == "admin_override"
