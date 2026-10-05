from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import User, UserRole
from app.models.maintenance import (
    MaintAttachment,
    MaintCategory,
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintPriority,
    MaintSmsMessage,
    MaintStatus,
    MaintTicket,
    MaintVendor,
    MaintVisibility,
    MaintWorkOrder,
)
from app.models.rentals import RentalProperty, RentalUnit
from app.services.maintenance.media import store_attachment, validate_file_count
from app.services.maintenance.sms.outbound import SmsOptedOutError, cancel_held_sms, queue_sms
from app.services.maintenance.sms.templates import render_template
from app.services.maintenance.state_machine import ActorContext, transition
from app.services.maintenance.tickets import (
    acknowledge_emergency,
    cancel_ticket,
    mark_duplicate,
    triage_ticket,
)
from app.services.maintenance.work_orders import (
    assign_vendor_work_order,
    complete_work_order,
    create_work_order,
    schedule_work_order,
)


BLOCKED_MESSAGE_STATUSES = {MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}
OPEN_LIST_STATUSES = {
    MaintStatus.NEW,
    MaintStatus.TRIAGED,
    MaintStatus.ASSIGNED,
    MaintStatus.SCHEDULED,
    MaintStatus.IN_PROGRESS,
    MaintStatus.AWAITING_PARTS,
    MaintStatus.AWAITING_TENANT,
    MaintStatus.RESOLVED,
}


def value(item: object | None) -> str | None:
    if item is None:
        return None
    return str(item.value if hasattr(item, "value") else item)


def actor_for(user: User | None) -> ActorContext:
    return ActorContext(
        party=MaintParty.STAFF,
        user_id=user.id if user else None,
        is_admin=bool(user and user.role == UserRole.ADMIN),
    )


def message_allowed(status: MaintStatus | str) -> bool:
    return MaintStatus(status) not in BLOCKED_MESSAGE_STATUSES


def sms_display_status(status: str) -> str:
    if status in {"queued", "sent", "delivered"}:
        return "sent"
    if status in {"pending", "held"}:
        return "held"
    return status


def sla_status(ticket: MaintTicket, *, now: datetime | None = None) -> str:
    checked_at = now or datetime.now(timezone.utc)
    if ticket.sla_due_at is None:
        return "untriaged"
    if MaintStatus(ticket.status) not in OPEN_LIST_STATUSES:
        return "complete"
    if checked_at >= ticket.sla_due_at:
        return "overdue"
    started = ticket.triaged_at or ticket.created_at
    warning_at = started + ((ticket.sla_due_at - started) * 0.75)
    return "warning" if checked_at >= warning_at else "on_track"


async def ticket_needs_reply(db: AsyncSession, ticket_id: UUID) -> bool:
    latest = await db.scalar(
        select(MaintEvent)
        .where(
            MaintEvent.ticket_id == ticket_id,
            MaintEvent.event_type == "message",
            MaintEvent.visibility == MaintVisibility.EXTERNAL,
        )
        .order_by(MaintEvent.created_at.desc())
        .limit(1)
    )
    return bool(latest and latest.direction == MaintDirection.INBOUND)


async def _ticket_location(
    db: AsyncSession,
    ticket: MaintTicket,
) -> tuple[str, str]:
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    property_label = (prop.group_name or prop.street_address) if prop else "Unknown property"
    unit_label = unit.unit_label if unit and unit.unit_label else "Main building"
    return property_label, unit_label


async def _work_order_views(db: AsyncSession, ticket_id: UUID) -> list[dict[str, object]]:
    orders = list(
        (
            await db.scalars(
                select(MaintWorkOrder)
                .where(MaintWorkOrder.ticket_id == ticket_id)
                .order_by(MaintWorkOrder.created_at)
            )
        ).all()
    )
    views: list[dict[str, object]] = []
    for order in orders:
        assignee_name = "Unassigned"
        if order.assignee_type == "staff" and order.assignee_user_id:
            user = await db.get(User, order.assignee_user_id)
            assignee_name = user.full_name if user else "Unknown staff"
        elif order.vendor_id:
            vendor = await db.get(MaintVendor, order.vendor_id)
            assignee_name = vendor.name if vendor else "Unknown vendor"
        views.append(
            {
                "id": order.id,
                "number": order.number,
                "assignee_type": order.assignee_type,
                "assignee_name": assignee_name,
                "status": value(order.status),
                "scope": order.scope,
                "scheduled_start": order.scheduled_start,
                "scheduled_end": order.scheduled_end,
                "cost_estimate": str(order.cost_estimate) if order.cost_estimate is not None else None,
                "cost_actual": str(order.cost_actual) if order.cost_actual is not None else None,
                "completion_notes": order.completion_notes,
                "external_party": order.assignee_type == "vendor",
            }
        )
    return views


async def list_ticket_views(
    db: AsyncSession,
    *,
    include_terminal: bool = False,
    status: MaintStatus | None = None,
    priority: MaintPriority | None = None,
    property_id: int | None = None,
    needs_reply_only: bool = False,
) -> list[dict[str, object]]:
    statement = select(MaintTicket)
    if status is not None:
        statement = statement.where(MaintTicket.status == status)
    elif not include_terminal:
        statement = statement.where(MaintTicket.status.in_(OPEN_LIST_STATUSES))
    if priority is not None:
        statement = statement.where(MaintTicket.priority == priority)
    if property_id is not None:
        statement = statement.where(MaintTicket.property_id == property_id)
    tickets = list(
        (
            await db.scalars(
                statement.order_by(MaintTicket.sla_due_at.asc().nullslast(), MaintTicket.updated_at.desc())
            )
        ).all()
    )
    result: list[dict[str, object]] = []
    for ticket in tickets:
        needs_reply = await ticket_needs_reply(db, ticket.id)
        if needs_reply_only and not needs_reply:
            continue
        property_label, unit_label = await _ticket_location(db, ticket)
        result.append(
            {
                "id": ticket.id,
                "number": ticket.number,
                "title": ticket.title,
                "property": property_label,
                "unit": unit_label,
                "category": value(ticket.category),
                "priority": value(ticket.priority),
                "status": value(ticket.status),
                "is_emergency": ticket.is_emergency,
                "needs_reply": needs_reply,
                "sla_status": sla_status(ticket),
                "sla_due_at": ticket.sla_due_at,
                "updated_at": ticket.updated_at,
            }
        )
    return result


async def _timeline(db: AsyncSession, ticket_id: UUID) -> list[dict[str, object]]:
    events = list(
        (
            await db.scalars(
                select(MaintEvent)
                .where(MaintEvent.ticket_id == ticket_id)
                .order_by(MaintEvent.created_at, MaintEvent.id)
            )
        ).all()
    )
    attachments = list(
        (
            await db.scalars(
                select(MaintAttachment)
                .where(MaintAttachment.ticket_id == ticket_id)
                .order_by(MaintAttachment.created_at)
            )
        ).all()
    )
    by_event: dict[UUID, list[dict[str, object]]] = {}
    for attachment in attachments:
        if attachment.event_id is None:
            continue
        by_event.setdefault(attachment.event_id, []).append(
            {
                "id": attachment.id,
                "filename": attachment.original_filename,
                "content_type": attachment.content_type,
                "url": f"/api/maintenance/attachments/{attachment.id}",
            }
        )
    items: list[dict[str, object]] = []
    for event in events:
        actor_name = None
        if event.actor_user_id:
            user = await db.get(User, event.actor_user_id)
            actor_name = user.full_name if user else None
        elif event.actor_vendor_id:
            vendor = await db.get(MaintVendor, event.actor_vendor_id)
            actor_name = vendor.name if vendor else None
        sms = await db.get(MaintSmsMessage, event.sms_message_id) if event.sms_message_id else None
        items.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "channel": value(event.channel),
                "visibility": value(event.visibility),
                "direction": value(event.direction),
                "party": value(event.actor_party),
                "actor_name": actor_name,
                "body": event.body,
                "payload": event.payload or {},
                "created_at": event.created_at,
                "attachments": by_event.get(event.id, []),
                "sms": (
                    {
                        "id": sms.id,
                        "status": sms_display_status(sms.status),
                        "hold_until": sms.hold_until,
                        "cancellable": sms.status == "held" and sms.cancelled_at is None,
                        "error_code": sms.error_code,
                    }
                    if sms
                    else None
                ),
            }
        )
    return items


async def ticket_detail_view(db: AsyncSession, ticket_id: UUID) -> dict[str, object] | None:
    ticket = await db.get(MaintTicket, ticket_id)
    if ticket is None:
        return None
    property_label, unit_label = await _ticket_location(db, ticket)
    users = list(
        (
            await db.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.full_name)
            )
        ).all()
    )
    vendors = list(
        (
            await db.scalars(
                select(MaintVendor).where(MaintVendor.is_active.is_(True)).order_by(MaintVendor.name)
            )
        ).all()
    )
    return {
        "id": ticket.id,
        "number": ticket.number,
        "title": ticket.title,
        "description": ticket.description,
        "property": property_label,
        "unit": unit_label,
        "category": value(ticket.category),
        "priority": value(ticket.priority),
        "status": value(ticket.status),
        "is_emergency": ticket.is_emergency,
        "emergency_acked_at": ticket.emergency_acked_at,
        "entry_permission": ticket.entry_permission,
        "entry_notes": ticket.entry_notes,
        "chargeback_flag": ticket.chargeback_flag,
        "sla_status": sla_status(ticket),
        "sla_due_at": ticket.sla_due_at,
        "needs_reply": await ticket_needs_reply(db, ticket.id),
        "messaging_allowed": message_allowed(ticket.status),
        "work_orders": await _work_order_views(db, ticket.id),
        "timeline": await _timeline(db, ticket.id),
        "staff_options": [{"id": item.id, "name": item.full_name} for item in users],
        "vendor_options": [{"id": item.id, "name": item.name} for item in vendors],
    }


async def post_message(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    target: str,
    body: str,
    work_order_id: UUID | None,
    files: list[tuple[str | None, bytes]],
) -> MaintSmsMessage | None:
    if not message_allowed(ticket.status):
        raise ValueError("Messaging is blocked for closed, cancelled, and duplicate tickets")
    if not body.strip() and not files:
        raise ValueError("A message or attachment is required")
    validate_file_count(len(files), party=MaintParty.STAFF)
    if target == "internal":
        event = MaintEvent(
            ticket_id=ticket.id,
            work_order_id=work_order_id,
            event_type="note",
            channel=MaintEventChannel.WEB,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=MaintParty.STAFF,
            actor_user_id=actor.user_id,
            body=body.strip() or None,
        )
        db.add(event)
        await db.flush()
        for filename, content in files:
            await store_attachment(
                db,
                ticket_id=ticket.id,
                work_order_id=work_order_id,
                event_id=event.id,
                content=content,
                original_filename=filename,
                uploaded_by_party=MaintParty.STAFF,
            )
        return None

    recipient = ticket.reporter_phone_e164 if target == "tenant" else None
    order = None
    if target == "vendor":
        if work_order_id is None:
            raise ValueError("Choose a vendor work order")
        order = await db.get(MaintWorkOrder, work_order_id)
        if order is None or order.ticket_id != ticket.id:
            raise ValueError("Work order not found")
        if order.assignee_type != "vendor" or order.vendor_id is None:
            raise ValueError("Staff work orders have no external party")
        vendor = await db.get(MaintVendor, order.vendor_id)
        recipient = vendor.phone_e164 if vendor and vendor.is_active else None
    if target not in {"tenant", "vendor"}:
        raise ValueError("Invalid message target")
    if not recipient:
        raise ValueError("The selected party has no text-message recipient")

    attachments = []
    for filename, content in files:
        attachments.append(
            await store_attachment(
                db,
                ticket_id=ticket.id,
                work_order_id=work_order_id,
                content=content,
                original_filename=filename,
                uploaded_by_party=MaintParty.STAFF,
            )
        )
    message = await queue_sms(
        db,
        to=recipient,
        body=body,
        ticket_id=ticket.id,
        work_order_id=work_order_id,
        media_attachment_ids=[item.id for item in attachments],
        automated=False,
        actor_party=MaintParty.STAFF,
        actor_user_id=actor.user_id,
    )
    event = await db.scalar(select(MaintEvent).where(MaintEvent.sms_message_id == message.id))
    for attachment in attachments:
        attachment.event_id = event.id if event else None
    return message


async def apply_triage(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    category: MaintCategory,
    priority: MaintPriority,
    is_emergency: bool,
    title: str,
    staff_summary: str | None,
) -> None:
    await triage_ticket(
        db,
        ticket,
        actor,
        category=category,
        priority=priority,
        is_emergency=is_emergency,
        title=title,
        staff_summary=staff_summary,
        channel=MaintEventChannel.WEB,
    )
    if ticket.reporter_phone_e164:
        timeframe = {
            MaintPriority.EMERGENCY: "as soon as possible",
            MaintPriority.URGENT: "within 24 hours",
            MaintPriority.ROUTINE: "within 7 days",
            MaintPriority.LOW: "within 14 days",
        }[MaintPriority(ticket.priority)]
        try:
            await queue_sms(
                db,
                to=ticket.reporter_phone_e164,
                body=render_template("tenant_triaged", number=ticket.number, timeframe=timeframe),
                ticket_id=ticket.id,
                automated=True,
                emergency=ticket.is_emergency,
                actor_party=MaintParty.STAFF,
                actor_user_id=actor.user_id,
            )
        except SmsOptedOutError:
            pass


async def assign_work(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    assignee_type: str,
    scope: str,
    assignee_user_id: UUID | None,
    vendor_id: UUID | None,
    cost_estimate: Decimal | None,
) -> MaintWorkOrder:
    if assignee_type == "vendor":
        if vendor_id is None:
            raise ValueError("Choose a vendor")
        return await assign_vendor_work_order(
            db,
            ticket,
            actor,
            vendor_id=vendor_id,
            scope=scope,
            cost_estimate=cost_estimate,
        )
    order, _ = await create_work_order(
        db,
        ticket,
        actor,
        assignee_type=assignee_type,
        scope=scope,
        assignee_user_id=assignee_user_id,
        vendor_id=vendor_id,
        cost_estimate=cost_estimate,
    )
    return order


async def schedule_work(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    work_order_id: UUID,
    start: datetime,
    end: datetime,
    admin_override_reason: str | None,
) -> None:
    order = await db.get(MaintWorkOrder, work_order_id)
    if order is None or order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    await schedule_work_order(
        db,
        ticket,
        order,
        actor,
        start,
        end,
        admin_override_reason=admin_override_reason,
    )
    window = f"{start.astimezone().strftime('%b %-d, %-I:%M %p')}–{end.astimezone().strftime('%-I:%M %p')}"
    if ticket.reporter_phone_e164:
        template = "tenant_scheduled" if ticket.entry_permission == "granted" or ticket.is_emergency else "tenant_entry_notice"
        values: dict[str, object] = {"number": ticket.number, "window": window}
        if template == "tenant_entry_notice":
            _, unit_label = await _ticket_location(db, ticket)
            values.update({"unit": unit_label, "details": ticket.entry_notes or "Entry is required for the scheduled work."})
        try:
            outgoing = render_template(template, **values)
            await queue_sms(
                db,
                to=ticket.reporter_phone_e164,
                body=outgoing,
                ticket_id=ticket.id,
                work_order_id=order.id,
                automated=True,
                emergency=ticket.is_emergency,
                actor_party=MaintParty.STAFF,
                actor_user_id=actor.user_id,
            )
            if template == "tenant_entry_notice":
                db.add(
                    MaintEvent(
                        ticket_id=ticket.id,
                        work_order_id=order.id,
                        event_type="entry_notice_sent",
                        channel=MaintEventChannel.SMS,
                        visibility=MaintVisibility.EXTERNAL,
                        direction=MaintDirection.OUTBOUND,
                        actor_party=MaintParty.STAFF,
                        actor_user_id=actor.user_id,
                        body=outgoing,
                    )
                )
        except SmsOptedOutError:
            pass
    if order.assignee_type == "vendor" and order.vendor_id:
        vendor = await db.get(MaintVendor, order.vendor_id)
        if vendor and vendor.is_active:
            try:
                await queue_sms(
                    db,
                    to=vendor.phone_e164,
                    body=render_template("vendor_scheduled_confirm", number=order.number, window=window),
                    ticket_id=ticket.id,
                    work_order_id=order.id,
                    automated=True,
                    actor_party=MaintParty.STAFF,
                    actor_user_id=actor.user_id,
                )
            except SmsOptedOutError:
                pass


async def resolve_ticket(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    note: str,
) -> None:
    await transition(db, ticket, MaintStatus.RESOLVED, actor, note, channel=MaintEventChannel.WEB)
    if ticket.reporter_phone_e164:
        try:
            await queue_sms(
                db,
                to=ticket.reporter_phone_e164,
                body=render_template("tenant_resolved_check", number=ticket.number),
                ticket_id=ticket.id,
                automated=True,
                actor_party=MaintParty.STAFF,
                actor_user_id=actor.user_id,
            )
        except SmsOptedOutError:
            pass


async def apply_more_action(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    action: str,
    reason: str | None,
    canonical_ticket_id: UUID | None,
) -> None:
    if action == "cancel":
        await cancel_ticket(db, ticket, actor, reason=reason or "Cancelled in Office Hub")
    elif action == "duplicate":
        if canonical_ticket_id is None:
            raise ValueError("Choose the canonical ticket")
        canonical = await db.get(MaintTicket, canonical_ticket_id)
        if canonical is None:
            raise ValueError("Canonical ticket not found")
        await mark_duplicate(db, ticket, canonical, actor, reason=reason)
    elif action == "reopen":
        await transition(db, ticket, MaintStatus.IN_PROGRESS, actor, reason, channel=MaintEventChannel.WEB)
    elif action == "toggle_chargeback":
        ticket.chargeback_flag = not ticket.chargeback_flag
        db.add(
            MaintEvent(
                ticket_id=ticket.id,
                event_type="chargeback_toggled",
                channel=MaintEventChannel.WEB,
                visibility=MaintVisibility.INTERNAL,
                direction=MaintDirection.NONE,
                actor_party=MaintParty.STAFF,
                actor_user_id=actor.user_id,
                payload={"enabled": ticket.chargeback_flag},
            )
        )
    else:
        raise ValueError("Unsupported ticket action")


async def complete_order(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    work_order_id: UUID,
    completion_notes: str,
    cost_actual: Decimal | None,
) -> bool:
    order = await db.get(MaintWorkOrder, work_order_id)
    if order is None or order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    return await complete_work_order(
        db,
        ticket,
        order,
        actor,
        completion_notes=completion_notes,
        cost_actual=cost_actual,
    )


async def cancel_message(
    db: AsyncSession,
    message_id: UUID,
    actor: ActorContext,
) -> None:
    await cancel_held_sms(db, message_id, actor)


async def acknowledge_ticket(db: AsyncSession, ticket: MaintTicket, actor: ActorContext) -> bool:
    return await acknowledge_emergency(db, ticket, actor, channel=MaintEventChannel.WEB)
