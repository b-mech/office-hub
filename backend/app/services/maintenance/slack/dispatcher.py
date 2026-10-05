from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.core import User
from app.models.maintenance import (
    MaintSlackOutbox,
    MaintStatus,
    MaintTicket,
    MaintWorkOrder,
)
from app.models.rentals import RentalProperty, RentalUnit
from app.services.maintenance.slack.client import HttpSlackClient, SlackClient
from app.services.maintenance.slack.outbox import (
    claim_due_notifications,
    mark_delivered,
    mark_failed_attempt,
)
from app.services.maintenance.slack.users import ensure_slack_user_id


OPEN_STATUSES = (
    MaintStatus.NEW,
    MaintStatus.TRIAGED,
    MaintStatus.ASSIGNED,
    MaintStatus.SCHEDULED,
    MaintStatus.IN_PROGRESS,
    MaintStatus.AWAITING_PARTS,
    MaintStatus.AWAITING_TENANT,
    MaintStatus.RESOLVED,
)


@dataclass(frozen=True)
class TicketLinkView:
    number: str
    unit: str
    category: str
    priority: str
    link: str


def _label(value: object | None, fallback: str = "untriaged") -> str:
    if value is None:
        return fallback
    raw = value.value if hasattr(value, "value") else value
    return str(raw).replace("_", " ").title()


def ticket_link(ticket_id: UUID) -> str:
    return f"{settings.public_site_url.rstrip('/')}/rentals/maintenance/{ticket_id}"


async def ticket_link_view(db: AsyncSession, ticket: MaintTicket) -> TicketLinkView:
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    property_label = (prop.group_name or prop.street_address) if prop else "Unknown property"
    unit_label = unit.unit_label if unit and unit.unit_label else "Main building"
    return TicketLinkView(
        number=ticket.number,
        unit=f"{property_label} · {unit_label}",
        category=_label(ticket.category),
        priority=_label(ticket.priority),
        link=ticket_link(ticket.id),
    )


def render_link_notification(prefix: str, view: TicketLinkView, mentions: tuple[str, ...] = ()) -> str:
    mention_text = " ".join(f"<@{value}>" for value in mentions)
    suffix = f" · {mention_text}" if mention_text else ""
    return (
        f"{prefix} · {view.number} · {view.unit} · {view.category} · "
        f"{view.priority} · <{view.link}|Open in Office Hub>{suffix}"
    )


async def _staff_assignees(db: AsyncSession, ticket_id: UUID) -> list[User]:
    return list(
        (
            await db.scalars(
                select(User)
                .join(MaintWorkOrder, MaintWorkOrder.assignee_user_id == User.id)
                .where(
                    MaintWorkOrder.ticket_id == ticket_id,
                    MaintWorkOrder.assignee_type == "staff",
                    User.is_active.is_(True),
                )
                .order_by(User.email)
            )
        ).unique().all()
    )


async def _mentions(
    db: AsyncSession,
    client: SlackClient,
    users: list[User],
) -> tuple[str, ...]:
    resolved: list[str] = []
    for user in users:
        slack_user_id = await ensure_slack_user_id(db, client, user)
        if slack_user_id and slack_user_id not in resolved:
            resolved.append(slack_user_id)
    return tuple(resolved)


async def _payload_users(db: AsyncSession, payload: dict[str, object]) -> list[User]:
    ids: list[UUID] = []
    for value in payload.get("user_ids", []):
        try:
            ids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    return list((await db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)))).all())


async def _dispatch_digest(db: AsyncSession, client: SlackClient) -> None:
    tickets = list(
        (
            await db.scalars(
                select(MaintTicket)
                .where(MaintTicket.status.in_(OPEN_STATUSES))
                .order_by(MaintTicket.sla_due_at.asc().nullslast(), MaintTicket.updated_at.desc())
                .limit(50)
            )
        ).all()
    )
    if not tickets:
        return
    now = datetime.now(timezone.utc)
    lines = ["Morning maintenance digest"]
    for ticket in tickets:
        view = await ticket_link_view(db, ticket)
        marker = "🔥" if ticket.sla_due_at and ticket.sla_due_at < now else "📋"
        lines.append(render_link_notification(marker, view))
    await client.post_message(settings.slack_tickets_channel_id, "\n".join(lines))


async def dispatch_notification(
    db: AsyncSession,
    client: SlackClient,
    row: MaintSlackOutbox,
) -> None:
    if row.kind == "morning_digest":
        await _dispatch_digest(db, client)
        return
    ticket = await db.get(MaintTicket, row.ticket_id) if row.ticket_id else None
    if ticket is None:
        return
    view = await ticket_link_view(db, ticket)
    payload = row.payload or {}

    if row.kind == "emergency_alert":
        users = await _payload_users(db, payload)
        mentions = await _mentions(db, client, users)
        stage = int(payload.get("stage", 0))
        prefix = "🚨 Emergency" if stage == 0 else "🚨 Emergency escalation"
        text = render_link_notification(prefix, view, mentions)
        await client.post_message(settings.slack_emergency_channel_id, text)
        for slack_user_id in mentions:
            channel = await client.open_dm(slack_user_id)
            await client.post_message(channel, text)
        return

    mentions: tuple[str, ...] = ()
    if row.kind in {"party_replied", "sla_warning", "sla_breached"}:
        mentions = await _mentions(db, client, await _staff_assignees(db, ticket.id))
    prefixes = {
        "ticket_created": "🆕 New ticket",
        "party_replied": f"💬 {_label(payload.get('party'), 'Party')} replied",
        "sla_warning": "⏰ SLA warning",
        "sla_breached": "🔥 SLA breached",
    }
    prefix = prefixes.get(row.kind)
    if prefix:
        await client.post_message(
            settings.slack_tickets_channel_id,
            render_link_notification(prefix, view, mentions),
        )


async def dispatch_outbox_once(client: SlackClient | None = None) -> int:
    if not settings.slack_configured:
        return 0
    client = client or HttpSlackClient()
    async with AsyncSessionLocal() as db:
        rows = await claim_due_notifications(db)
        row_ids = [row.id for row in rows]
        await db.commit()
    for row_id in row_ids:
        async with AsyncSessionLocal() as db:
            row = await db.get(MaintSlackOutbox, row_id)
            if row is None or row.delivered_at is not None or row.failed_at is not None:
                continue
            try:
                await dispatch_notification(db, client, row)
                mark_delivered(row)
            except Exception as exc:
                mark_failed_attempt(row, exc)
            await db.commit()
    return len(row_ids)


def run_dispatch_sync() -> int:
    return asyncio.run(dispatch_outbox_once())
