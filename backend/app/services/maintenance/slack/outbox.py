from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

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
