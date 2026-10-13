from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

from app.services.maintenance.errors import EntryNoticeError


@dataclass(frozen=True)
class EntryNoticePolicy:
    minimum_notice: timedelta = timedelta(hours=24)
    window_start: time = time(8, 0)
    window_end: time = time(20, 0)
    timezone: tzinfo | None = None


def validate_entry_notice(
    scheduled_start: datetime,
    scheduled_end: datetime,
    notice_sent_at: datetime,
    *,
    entry_permission: str,
    is_emergency: bool,
    policy: EntryNoticePolicy = EntryNoticePolicy(),
) -> str:
    if (
        scheduled_start.tzinfo is None
        or scheduled_end.tzinfo is None
        or notice_sent_at.tzinfo is None
    ):
        raise EntryNoticeError("Visit start, end, and notice time must include a timezone")
    if scheduled_end <= scheduled_start:
        raise EntryNoticeError("Visit end must be after the start")

    local_timezone = policy.timezone or scheduled_start.tzinfo
    local_start = scheduled_start.astimezone(local_timezone)
    local_end = scheduled_end.astimezone(local_timezone)
    if local_end.date() != local_start.date():
        raise EntryNoticeError("Visit start and end must be on the same local calendar day")
    if not policy.window_start <= local_start.time().replace(tzinfo=None) <= policy.window_end:
        raise EntryNoticeError(
            f"Visit start must be within the entry window "
            f"({policy.window_start.strftime('%-I:%M %p')} to "
            f"{policy.window_end.strftime('%-I:%M %p')})"
        )
    if not policy.window_start <= local_end.time().replace(tzinfo=None) <= policy.window_end:
        raise EntryNoticeError(
            f"Visit end must be within the entry window "
            f"({policy.window_start.strftime('%-I:%M %p')} to "
            f"{policy.window_end.strftime('%-I:%M %p')})"
        )

    if entry_permission == "granted":
        return "permission_granted"
    if is_emergency:
        return "emergency_bypass"
    if scheduled_start < notice_sent_at + policy.minimum_notice:
        hours = policy.minimum_notice.total_seconds() / 3600
        raise EntryNoticeError(
            f"Visit start must be at least {hours:g} hours after the entry notice is sent"
        )
    return "notice_required"
