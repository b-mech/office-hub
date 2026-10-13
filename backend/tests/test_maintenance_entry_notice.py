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
        entry_permission="denied",
        is_emergency=False,
    ) == "notice_required"


def test_notice_rejects_too_soon() -> None:
    with pytest.raises(EntryNoticeError, match="24 hours"):
        validate_entry_notice(
            NOW + timedelta(hours=23),
            NOW + timedelta(hours=24),
            NOW,
            entry_permission="not_asked",
            is_emergency=False,
        )


def test_notice_rejects_outside_window() -> None:
    with pytest.raises(EntryNoticeError, match="window"):
        validate_entry_notice(
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            datetime(2026, 10, 2, 22, 0, tzinfo=TZ),
            NOW,
            entry_permission="denied",
            is_emergency=False,
        )

    with pytest.raises(EntryNoticeError, match="Visit end"):
        validate_entry_notice(
            datetime(2026, 10, 2, 19, 0, tzinfo=TZ),
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            NOW,
            entry_permission="denied",
            is_emergency=False,
        )


def test_notice_rejects_end_before_start() -> None:
    start = NOW + timedelta(days=2)
    with pytest.raises(EntryNoticeError, match="end must be after"):
        validate_entry_notice(
            start,
            start - timedelta(minutes=1),
            NOW,
            entry_permission="denied",
            is_emergency=False,
        )


def test_notice_rejects_visit_across_local_calendar_days() -> None:
    with pytest.raises(EntryNoticeError, match="same local calendar day"):
        validate_entry_notice(
            datetime(2026, 10, 2, 19, 0, tzinfo=TZ),
            datetime(2026, 10, 3, 9, 0, tzinfo=TZ),
            NOW,
            entry_permission="denied",
            is_emergency=False,
        )


def test_notice_validates_window_in_configured_timezone() -> None:
    policy = EntryNoticePolicy(timezone=TZ)
    assert validate_entry_notice(
        datetime(2026, 10, 2, 14, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 2, 16, 0, tzinfo=ZoneInfo("UTC")),
        NOW,
        entry_permission="denied",
        is_emergency=False,
        policy=policy,
    ) == "notice_required"


def test_permission_and_emergency_bypass_minimum_notice_but_not_visit_window() -> None:
    too_soon = NOW + timedelta(hours=1)
    end = too_soon + timedelta(hours=1)
    assert validate_entry_notice(
        too_soon, end, NOW, entry_permission="granted", is_emergency=False
    ) == "permission_granted"
    assert validate_entry_notice(
        too_soon,
        end,
        NOW,
        entry_permission="denied",
        is_emergency=True,
    ) == "emergency_bypass"
    with pytest.raises(EntryNoticeError, match="entry window"):
        validate_entry_notice(
            datetime(2026, 10, 2, 21, 0, tzinfo=TZ),
            datetime(2026, 10, 2, 22, 0, tzinfo=TZ),
            NOW,
            entry_permission="granted",
            is_emergency=False,
        )
