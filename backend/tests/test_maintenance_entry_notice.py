from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.maintenance.entry_notice import EntryNoticePolicy, validate_entry_notice
from app.services.maintenance.errors import EntryNoticeError


TZ = ZoneInfo("America/Winnipeg")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=TZ)


def test_notice_inside_window_and_after_minimum() -> None:
    start = NOW + timedelta(hours=25)
    assert validate_entry_notice(
        start,
        start + timedelta(hours=1),
        NOW,
        access_basis="routine",
        is_emergency_ticket=False,
    ) == "notice_required"


def test_notice_rejects_too_soon() -> None:
    with pytest.raises(EntryNoticeError, match="24 hours"):
        validate_entry_notice(
            NOW + timedelta(hours=23),
            NOW + timedelta(hours=24),
            NOW,
            access_basis="routine",
            is_emergency_ticket=False,
        )


def test_notice_rejects_outside_window() -> None:
    with pytest.raises(EntryNoticeError, match="window"):
        validate_entry_notice(
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            datetime(2026, 10, 2, 22, 0, tzinfo=TZ),
            NOW,
            access_basis="routine",
            is_emergency_ticket=False,
        )

    with pytest.raises(EntryNoticeError, match="Visit end"):
        validate_entry_notice(
            datetime(2026, 10, 2, 19, 0, tzinfo=TZ),
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            NOW,
            access_basis="routine",
            is_emergency_ticket=False,
        )


def test_notice_rejects_end_before_start() -> None:
    start = NOW + timedelta(days=2)
    with pytest.raises(EntryNoticeError, match="end must be after"):
        validate_entry_notice(
            start,
            start - timedelta(minutes=1),
            NOW,
            access_basis="routine",
            is_emergency_ticket=False,
        )


def test_notice_rejects_visit_across_local_calendar_days() -> None:
    with pytest.raises(EntryNoticeError, match="same local calendar day"):
        validate_entry_notice(
            datetime(2026, 10, 2, 19, 0, tzinfo=TZ),
            datetime(2026, 10, 3, 9, 0, tzinfo=TZ),
            NOW,
            access_basis="routine",
            is_emergency_ticket=False,
        )


def test_notice_validates_window_in_configured_timezone() -> None:
    policy = EntryNoticePolicy(timezone=TZ)
    assert validate_entry_notice(
        datetime(2026, 10, 2, 14, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 2, 16, 0, tzinfo=ZoneInfo("UTC")),
        NOW,
        access_basis="routine",
        is_emergency_ticket=False,
        policy=policy,
    ) == "notice_required"


def test_tenant_consent_bypasses_minimum_but_not_visit_window() -> None:
    too_soon = NOW + timedelta(hours=1)
    end = too_soon + timedelta(hours=1)
    assert validate_entry_notice(
        too_soon, end, NOW, access_basis="tenant_consent", is_emergency_ticket=False
    ) == "tenant_consent"
    with pytest.raises(EntryNoticeError, match="entry window"):
        validate_entry_notice(
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            datetime(2026, 10, 2, 22, 0, tzinfo=TZ),
            NOW,
            access_basis="tenant_consent",
            is_emergency_ticket=False,
        )


def test_emergency_bypasses_minimum_and_entry_window_only_on_emergency_ticket() -> None:
    start = datetime(2026, 10, 1, 21, 0, tzinfo=TZ)
    end = start + timedelta(hours=1)
    assert validate_entry_notice(
        start,
        end,
        NOW,
        access_basis="emergency",
        is_emergency_ticket=True,
    ) == "emergency"
    with pytest.raises(EntryNoticeError, match="only allowed for an emergency ticket"):
        validate_entry_notice(
            start,
            end,
            NOW,
            access_basis="emergency",
            is_emergency_ticket=False,
        )
