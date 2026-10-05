from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.core import User, UserRole
from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintOnCall,
    MaintParty,
    MaintStatus,
    MaintTicket,
    MaintVisibility,
)
from app.models.rentals import RentalProperty, RentalUnit
from app.services.maintenance.slack.outbox import enqueue_slack_notification
from app.services.maintenance.sms.outbound import SmsOptedOutError, queue_sms
from app.services.maintenance.sms.templates import render_template


TERMINAL_STATUSES = (MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE)


async def _admins(db: AsyncSession) -> list[User]:
    return list(
        (
            await db.scalars(
                select(User)
                .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
                .order_by(User.email)
            )
        ).all()
    )


async def page_targets(db: AsyncSession, *, stage: int, now: datetime) -> list[User]:
    if stage < 2:
        users = list(
            (
                await db.scalars(
                    select(User)
                    .join(MaintOnCall, MaintOnCall.user_id == User.id)
                    .where(
                        MaintOnCall.starts_at <= now,
                        MaintOnCall.ends_at > now,
                        MaintOnCall.is_backup.is_(stage == 1),
                        User.is_active.is_(True),
                    )
                    .order_by(MaintOnCall.starts_at.desc())
                )
            ).unique().all()
        )
        if users:
            return users
    return await _admins(db)


async def _already_paged(db: AsyncSession, ticket_id: UUID, stage: int) -> bool:
    events = list(
        (
            await db.scalars(
                select(MaintEvent).where(
                    MaintEvent.ticket_id == ticket_id,
                    MaintEvent.event_type == "emergency_paged",
                )
            )
        ).all()
    )
    return any(int((event.payload or {}).get("stage", -1)) == stage for event in events)


async def page_emergency(
    db: AsyncSession,
    ticket: MaintTicket,
    *,
    stage: int,
    now: datetime | None = None,
) -> bool:
    if not ticket.is_emergency or ticket.emergency_acked_at is not None:
        return False
    paged_at = now or datetime.now(timezone.utc)
    if await _already_paged(db, ticket.id, stage):
        return False
    users = await page_targets(db, stage=stage, now=paged_at)
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    property_label = (prop.group_name or prop.street_address) if prop else "Unknown property"
    unit_label = unit.unit_label if unit and unit.unit_label else "Main building"
    location = f"{property_label} · {unit_label}"
    link = f"{settings.public_site_url.rstrip('/')}/rentals/maintenance/{ticket.id}"
    for user in users:
        if not user.phone_e164:
            continue
        try:
            await queue_sms(
                db,
                to=user.phone_e164,
                body=render_template(
                    "oncall_emergency_page",
                    number=ticket.number,
                    unit=location,
                    link=link,
                ),
                ticket_id=ticket.id,
                automated=True,
                emergency=True,
            )
        except SmsOptedOutError:
            continue
    user_ids = [str(user.id) for user in users]
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            event_type="emergency_paged",
            channel=MaintEventChannel.SYSTEM,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.OUTBOUND,
            actor_party=MaintParty.SYSTEM,
            payload={"stage": stage, "user_ids": user_ids},
            created_at=paged_at,
        )
    )
    await enqueue_slack_notification(
        db,
        idempotency_key=f"ticket:{ticket.id}:emergency:{stage}",
        kind="emergency_alert",
        ticket_id=ticket.id,
        payload={"stage": stage, "user_ids": user_ids},
        now=paged_at,
    )
    await db.flush()
    return True


async def escalate_emergencies(*, now: datetime | None = None) -> int:
    checked_at = now or datetime.now(timezone.utc)
    interval = timedelta(minutes=settings.maint_emergency_ack_minutes)
    count = 0
    async with AsyncSessionLocal() as db:
        tickets = list(
            (
                await db.scalars(
                    select(MaintTicket)
                    .where(
                        MaintTicket.is_emergency.is_(True),
                        MaintTicket.emergency_acked_at.is_(None),
                        MaintTicket.status.notin_(TERMINAL_STATUSES),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for ticket in tickets:
            pages = list(
                (
                    await db.scalars(
                        select(MaintEvent)
                        .where(
                            MaintEvent.ticket_id == ticket.id,
                            MaintEvent.event_type == "emergency_paged",
                        )
                        .order_by(MaintEvent.created_at)
                    )
                ).all()
            )
            if not pages:
                count += int(await page_emergency(db, ticket, stage=0, now=checked_at))
                continue
            stages = [int((event.payload or {}).get("stage", 0)) for event in pages]
            stage = max(stages)
            last = max(event.created_at for event in pages if int((event.payload or {}).get("stage", 0)) == stage)
            if stage < 2 and checked_at >= last + interval:
                count += int(await page_emergency(db, ticket, stage=stage + 1, now=checked_at))
        await db.commit()
    return count


def run_escalation_sync() -> int:
    return asyncio.run(escalate_emergencies())
