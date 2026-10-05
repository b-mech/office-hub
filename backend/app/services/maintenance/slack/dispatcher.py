from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core import User
from app.models.maintenance import (
    MaintAttachment,
    MaintParty,
    MaintSlackCard,
    MaintSlackOutbox,
    MaintSmsMessage,
    MaintTicket,
    MaintVendor,
    MaintWorkOrder,
)
from app.models.rentals import RentalProperty, RentalUnit
from app.services.maintenance.media import download_attachment
from app.services.maintenance.slack.render import (
    render_emergency_alert,
    render_ticket_card,
    render_work_order_card,
)
from app.services.maintenance.slack.types import TicketCardView, WorkOrderCardView


class SlackClient(Protocol):
    async def chat_postMessage(self, **kwargs: object) -> object: ...
    async def chat_update(self, **kwargs: object) -> object: ...
    async def files_upload_v2(self, **kwargs: object) -> object: ...
    async def reactions_add(self, **kwargs: object) -> object: ...
    async def reactions_remove(self, **kwargs: object) -> object: ...


def _value(item: object) -> object:
    return item.value if hasattr(item, "value") else item


async def ticket_card_view(db: AsyncSession, ticket_id: UUID) -> TicketCardView:
    ticket = await db.get(MaintTicket, ticket_id)
    if ticket is None:
        raise ValueError("Maintenance ticket was not found")
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    work_orders = list(
        (
            await db.scalars(
                select(MaintWorkOrder)
                .where(MaintWorkOrder.ticket_id == ticket.id)
                .order_by(MaintWorkOrder.created_at)
            )
        ).all()
    )
    order_views: list[WorkOrderCardView] = []
    for order in work_orders:
        if order.assignee_type == "vendor":
            vendor = await db.get(MaintVendor, order.vendor_id)
            assignee = vendor.name if vendor else "Unknown vendor"
        else:
            user = await db.get(User, order.assignee_user_id)
            assignee = user.full_name if user else "Unknown staff"
        order_views.append(
            WorkOrderCardView(
                id=order.id,
                number=order.number,
                assignee_type=order.assignee_type,
                assignee_name=assignee,
                status=str(_value(order.status)),
                scope=order.scope,
                scheduled_start=order.scheduled_start,
                scheduled_end=order.scheduled_end,
            )
        )
    attachment_count = int(
        await db.scalar(
            select(func.count()).select_from(MaintAttachment).where(MaintAttachment.ticket_id == ticket.id)
        )
        or 0
    )
    suggestion = None
    if ticket.ai_suggestion:
        suggestion = str(
            ticket.ai_suggestion.get("summary")
            or ticket.ai_suggestion.get("suggestion")
            or ticket.ai_suggestion
        )
    return TicketCardView(
        id=ticket.id,
        number=ticket.number,
        title=ticket.title,
        description=ticket.description,
        status=str(_value(ticket.status)),
        category=str(_value(ticket.category)) if ticket.category else None,
        priority=str(_value(ticket.priority)) if ticket.priority else None,
        is_emergency=ticket.is_emergency,
        emergency_acknowledged=ticket.emergency_acked_at is not None,
        property_label=(prop.group_name or prop.street_address) if prop else "Unknown property",
        unit_label=(unit.unit_label or "Main building") if unit else "Property-wide",
        reporter_name=ticket.reporter_name,
        reporter_verified=ticket.reporter_verified,
        entry_permission=ticket.entry_permission,
        sla_due_at=ticket.sla_due_at,
        work_orders=tuple(order_views),
        attachment_count=attachment_count,
        ai_suggestion=suggestion,
    )


async def _post(client: SlackClient, **kwargs: object) -> dict[str, object]:
    response = await client.chat_postMessage(**kwargs)
    return dict(response)  # type: ignore[arg-type]


class SlackOutboxDispatcher:
    def __init__(self, client: SlackClient) -> None:
        self.client = client

    async def dispatch(self, db: AsyncSession, item: MaintSlackOutbox) -> None:
        if item.kind in {"ticket_created", "ticket_updated", "emergency_alert"} and item.ticket_id:
            view = await ticket_card_view(db, item.ticket_id)
            if item.kind != "emergency_alert":
                await self.upsert_ticket_card(db, view)
            if item.kind in {"ticket_created", "emergency_alert"} and view.is_emergency:
                await _post(
                    self.client,
                    channel=settings.slack_emergency_channel_id,
                    text=f"Emergency {view.number}: {view.title}",
                    blocks=render_emergency_alert(view),
                    client_msg_id=item.idempotency_key,
                )
            return
        if item.kind == "work_order_created" and item.ticket_id and item.work_order_id:
            await self.upsert_work_order_card(db, item.ticket_id, item.work_order_id)
            await self.upsert_ticket_card(db, await ticket_card_view(db, item.ticket_id))
            return
        if item.kind == "inbound_message" and item.sms_message_id:
            await self.post_inbound_message(db, item.sms_message_id)
            return
        if item.kind == "unmatched_message" and item.sms_message_id:
            message = await db.get(MaintSmsMessage, item.sms_message_id)
            if message:
                label = "known tenant" if item.payload.get("known_tenant") else "unknown sender"
                await _post(
                    self.client,
                    channel=settings.slack_tickets_channel_id,
                    text=f"Unmatched maintenance text from {label}, phone ending {message.from_e164[-4:]}",
                    client_msg_id=item.idempotency_key,
                )
            return
        if item.kind == "sms_status_changed" and item.sms_message_id:
            await self.update_sms_reaction(db, item.sms_message_id)
            return
        if item.kind == "opted_out":
            await _post(
                self.client,
                channel=settings.slack_tickets_channel_id,
                text=f"SMS opt-out recorded for phone ending {item.payload.get('phone_last4', 'unknown')}",
                client_msg_id=item.idempotency_key,
            )

    async def upsert_ticket_card(self, db: AsyncSession, view: TicketCardView) -> MaintSlackCard:
        card = await db.scalar(
            select(MaintSlackCard).where(
                MaintSlackCard.ticket_id == view.id,
                MaintSlackCard.work_order_id.is_(None),
            )
        )
        blocks = render_ticket_card(view)
        if card:
            await self.client.chat_update(
                channel=card.channel_id,
                ts=card.message_ts,
                text=f"{view.number}: {view.title}",
                blocks=blocks,
            )
            return card
        response = await _post(
            self.client,
            channel=settings.slack_tickets_channel_id,
            text=f"{view.number}: {view.title}",
            blocks=blocks,
            client_msg_id=f"ticket:{view.id}:card",
        )
        card = MaintSlackCard(
            ticket_id=view.id,
            channel_id=settings.slack_tickets_channel_id,
            message_ts=str(response["ts"]),
            thread_party=MaintParty.TENANT,
        )
        db.add(card)
        await db.flush()
        return card

    async def upsert_work_order_card(
        self, db: AsyncSession, ticket_id: UUID, work_order_id: UUID
    ) -> MaintSlackCard:
        view = await ticket_card_view(db, ticket_id)
        order = next((value for value in view.work_orders if value.id == work_order_id), None)
        if order is None:
            raise ValueError("Maintenance work order was not found")
        card = await db.scalar(
            select(MaintSlackCard).where(MaintSlackCard.work_order_id == work_order_id)
        )
        blocks = render_work_order_card(order, ticket_id)
        if card:
            await self.client.chat_update(
                channel=card.channel_id,
                ts=card.message_ts,
                text=f"{order.number}: {order.scope}",
                blocks=blocks,
            )
            return card
        response = await _post(
            self.client,
            channel=settings.slack_tickets_channel_id,
            text=f"{order.number}: {order.scope}",
            blocks=blocks,
            client_msg_id=f"work-order:{order.id}:card",
        )
        card = MaintSlackCard(
            ticket_id=ticket_id,
            work_order_id=work_order_id,
            channel_id=settings.slack_tickets_channel_id,
            message_ts=str(response["ts"]),
            thread_party=MaintParty.STAFF if order.assignee_type == "staff" else MaintParty.VENDOR,
        )
        db.add(card)
        await db.flush()
        return card

    async def post_inbound_message(self, db: AsyncSession, message_id: UUID) -> None:
        message = await db.get(MaintSmsMessage, message_id)
        if message is None or message.ticket_id is None:
            return
        card = None
        party = MaintParty.TENANT
        display_name = "Tenant text"
        if message.work_order_id:
            card = await db.scalar(
                select(MaintSlackCard).where(MaintSlackCard.work_order_id == message.work_order_id)
            )
            work_order = await db.get(MaintWorkOrder, message.work_order_id)
            if work_order and work_order.vendor_id:
                vendor = await db.get(MaintVendor, work_order.vendor_id)
                display_name = f"Vendor · {vendor.name}" if vendor else "Vendor text"
                party = MaintParty.VENDOR
        if card is None:
            card = await db.scalar(
                select(MaintSlackCard).where(
                    MaintSlackCard.ticket_id == message.ticket_id,
                    MaintSlackCard.work_order_id.is_(None),
                )
            )
            ticket = await db.get(MaintTicket, message.ticket_id)
            if ticket and ticket.reporter_name:
                display_name = f"Tenant · {ticket.reporter_name}"
        if card is None:
            view = await ticket_card_view(db, message.ticket_id)
            card = await self.upsert_ticket_card(db, view)
        await _post(
            self.client,
            channel=card.channel_id,
            thread_ts=card.message_ts,
            text=message.body or "(media only)",
            username=display_name,
            icon_emoji=":speech_balloon:" if party == MaintParty.TENANT else ":construction_worker:",
            client_msg_id=f"sms:{message.id}:inbound",
        )
        for attachment_id in message.media_attachment_ids:
            attachment = await db.get(MaintAttachment, attachment_id)
            if attachment is None:
                continue
            content = await asyncio.to_thread(download_attachment, attachment.minio_key)
            await self.client.files_upload_v2(
                channel=card.channel_id,
                thread_ts=card.message_ts,
                file=BytesIO(content),
                filename=attachment.original_filename or f"attachment-{attachment.id}",
                title=f"Inbound {party.value} media",
            )
        view = await ticket_card_view(db, message.ticket_id)
        await self.upsert_ticket_card(db, view)

    async def update_sms_reaction(self, db: AsyncSession, message_id: UUID) -> None:
        message = await db.get(MaintSmsMessage, message_id)
        if message is None or not message.slack_channel_id or not message.slack_ts:
            return
        reaction = {
            "held": "hourglass_flowing_sand",
            "queued": "email",
            "sent": "email",
            "delivered": "email",
            "failed": "warning",
            "cancelled": "x",
        }.get(message.status)
        if reaction is None:
            return
        for old in ("hourglass_flowing_sand", "email", "warning", "x"):
            if old == reaction:
                continue
            try:
                await self.client.reactions_remove(
                    channel=message.slack_channel_id, timestamp=message.slack_ts, name=old
                )
            except Exception:
                pass
        await self.client.reactions_add(
            channel=message.slack_channel_id,
            timestamp=message.slack_ts,
            name=reaction,
        )
