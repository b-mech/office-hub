from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintSlackOutbox


async def enqueue_slack_notification(
    db: AsyncSession,
    *,
    idempotency_key: str,
    kind: str,
    ticket_id: UUID | None = None,
    work_order_id: UUID | None = None,
    sms_message_id: UUID | None = None,
    payload: dict[str, object] | None = None,
    now: datetime | None = None,
) -> None:
    """Insert once inside the caller's transaction without committing it."""
    if not idempotency_key.strip() or not kind.strip():
        raise ValueError("Slack notification key and kind are required")
    created_at = now or datetime.now(timezone.utc)
    statement = (
        insert(MaintSlackOutbox)
        .values(
            idempotency_key=idempotency_key,
            kind=kind,
            ticket_id=ticket_id,
            work_order_id=work_order_id,
            sms_message_id=sms_message_id,
            payload=payload or {},
            attempts=0,
            available_at=created_at,
            created_at=created_at,
            updated_at=created_at,
        )
        .on_conflict_do_nothing(index_elements=[MaintSlackOutbox.idempotency_key])
    )
    await db.execute(statement)


async def claim_due_notifications(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 25,
    stale_after: timedelta = timedelta(minutes=5),
) -> list[MaintSlackOutbox]:
    claimed_at = now or datetime.now(timezone.utc)
    rows = list(
        (
            await db.scalars(
                select(MaintSlackOutbox)
                .where(
                    MaintSlackOutbox.delivered_at.is_(None),
                    MaintSlackOutbox.failed_at.is_(None),
                    MaintSlackOutbox.available_at <= claimed_at,
                    or_(
                        MaintSlackOutbox.claimed_at.is_(None),
                        MaintSlackOutbox.claimed_at <= claimed_at - stale_after,
                    ),
                )
                .order_by(MaintSlackOutbox.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for row in rows:
        row.claimed_at = claimed_at
        row.attempts += 1
        row.updated_at = claimed_at
    await db.flush()
    return rows


def retry_after_seconds(exc: Exception, attempts: int) -> int:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 429:
        headers = getattr(response, "headers", {}) or {}
        try:
            return max(1, min(int(headers.get("Retry-After", "1")), 3600))
        except (TypeError, ValueError):
            return 1
    return min(2 ** max(attempts - 1, 0), 900)


def mark_delivered(row: MaintSlackOutbox, *, now: datetime | None = None) -> None:
    delivered_at = now or datetime.now(timezone.utc)
    row.delivered_at = delivered_at
    row.claimed_at = None
    row.last_error = None
    row.updated_at = delivered_at


def mark_failed_attempt(
    row: MaintSlackOutbox,
    exc: Exception,
    *,
    now: datetime | None = None,
    max_attempts: int = 8,
) -> None:
    failed_at = now or datetime.now(timezone.utc)
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    row.last_error = f"{type(exc).__name__}:{status}" if status else type(exc).__name__
    row.claimed_at = None
    row.updated_at = failed_at
    if row.attempts >= max_attempts:
        row.failed_at = failed_at
    else:
        row.available_at = failed_at + timedelta(seconds=retry_after_seconds(exc, row.attempts))
