from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.services.maintenance.errors import EntryNoticeError


@dataclass(frozen=True)
class EntryNoticePolicy:
    minimum_notice: timedelta = timedelta(hours=24)
    window_start: time = time(8, 0)
    window_end: time = time(20, 0)


def validate_entry_notice(
    scheduled_start: datetime,
    now: datetime,
    *,
    entry_permission: str,
    is_emergency: bool,
    admin_override_reason: str | None = None,
    policy: EntryNoticePolicy = EntryNoticePolicy(),
) -> str:
    if entry_permission == "granted":
        return "permission_granted"
    if is_emergency:
        return "emergency_bypass"
    if admin_override_reason and admin_override_reason.strip():
        return "admin_override"
    if scheduled_start < now + policy.minimum_notice:
        raise EntryNoticeError("The scheduled start does not provide the configured minimum entry notice")
    local_time = scheduled_start.timetz().replace(tzinfo=None)
    if not policy.window_start <= local_time <= policy.window_end:
        raise EntryNoticeError("The scheduled start is outside the configured entry window")
    return "notice_required"
