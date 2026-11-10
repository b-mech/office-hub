from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintStatus,
    MaintTicket,
    MaintVisibility,
)
from app.services.maintenance.sla import sla_warning_at
from app.services.maintenance.slack.outbox import enqueue_slack_notification


SLA_STATUSES = (
    MaintStatus.TRIAGED,
    MaintStatus.ASSIGNED,
    MaintStatus.SCHEDULED,
    MaintStatus.IN_PROGRESS,
    MaintStatus.AWAITING_PARTS,
    MaintStatus.AWAITING_TENANT,
)


async def watch_sla(*, now: datetime | None = None) -> int:
    checked_at = now or datetime.now(timezone.utc)
    created = 0
    async with AsyncSessionLocal() as db:
        tickets = list(
            (
                await db.scalars(
                    select(MaintTicket).where(
                        MaintTicket.status.in_(SLA_STATUSES),
                        MaintTicket.sla_due_at.is_not(None),
                    )
                )
            ).all()
        )
        for ticket in tickets:
            existing = set(
                (
                    await db.scalars(
                        select(MaintEvent.event_type).where(
                            MaintEvent.ticket_id == ticket.id,
                            MaintEvent.event_type.in_(("sla_warning", "sla_breached")),
                        )
                    )
                ).all()
            )
            event_type = None
            if checked_at >= ticket.sla_due_at and "sla_breached" not in existing:
                event_type = "sla_breached"
            else:
                started = ticket.triaged_at or ticket.created_at
                if checked_at >= sla_warning_at(started, ticket.sla_due_at) and "sla_warning" not in existing:
                    event_type = "sla_warning"
            if event_type is None:
                continue
            db.add(
                MaintEvent(
                    ticket_id=ticket.id,
                    event_type=event_type,
                    channel=MaintEventChannel.SYSTEM,
                    visibility=MaintVisibility.INTERNAL,
                    direction=MaintDirection.NONE,
                    actor_party=MaintParty.SYSTEM,
                    created_at=checked_at,
                )
            )
            await enqueue_slack_notification(
                db,
                idempotency_key=f"ticket:{ticket.id}:{event_type}",
                kind=event_type,
                ticket_id=ticket.id,
                now=checked_at,
            )
            created += 1
        await db.commit()
    return created


async def enqueue_morning_digest(*, now: datetime | None = None) -> int:
    queued_at = now or datetime.now(timezone.utc)
    local_date = queued_at.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    async with AsyncSessionLocal() as db:
        open_ticket = await db.scalar(
            select(MaintTicket.id).where(MaintTicket.status.in_(SLA_STATUSES)).limit(1)
        )
        if open_ticket is None:
            return 0
        await enqueue_slack_notification(
            db,
            idempotency_key=f"maintenance:digest:{local_date}",
            kind="morning_digest",
            now=queued_at,
        )
        await db.commit()
    return 1


def run_sla_watch_sync() -> int:
    return asyncio.run(watch_sla())


def run_digest_sync() -> int:
    return asyncio.run(enqueue_morning_digest())
