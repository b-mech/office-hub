from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
from app.services.maintenance.phones import format_phone
from app.services.maintenance.sms.outbound import (
    SmsOptedOutError,
    cancel_held_sms,
    quiet_hours_release,
    queue_sms,
    retry_failed_sms,
    sms_failure_reason,
)
from app.services.maintenance.sms.templates import render_template, render_tenant_reply
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
    is_future_scheduled_visit,
    schedule_work_order,
    validate_work_order_schedule,
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


async def _ticket_address_and_unit(
    db: AsyncSession,
    ticket: MaintTicket,
) -> tuple[str, str]:
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    if prop is None:
        raise ValueError("Ticket property not found")
    address = prop.street_address.strip()
    unit_label = unit.unit_label.strip() if unit and unit.unit_label else "Main building"
    return address, unit_label


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
                "scheduled_visit_status": order.scheduled_visit_status,
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


NOTICE_EVENT_TYPES = {
    "entry_notice_sent",
    "tenant_consent_confirmation_sent",
    "emergency_on_way_sent",
}


def _calendar_notice_status(message: MaintSmsMessage | None) -> str | None:
    if message is None:
        return None
    status = str(message.status)
    if status in {"pending", "held", "queued"}:
        return "queued"
    if status == "sent":
        return "sent"
    if status == "delivered":
        return "delivered"
    if status in {"failed", "cancelled"}:
        return "failed"
    return None


def _calendar_event_for_start(
    events: list[MaintEvent], event_types: set[str], start: datetime | None
) -> MaintEvent | None:
    candidates = [event for event in events if event.event_type in event_types]
    if not candidates:
        return None
    if start is not None:
        expected = start.isoformat()
        matches = [event for event in candidates if str((event.payload or {}).get("start")) == expected]
        if matches:
            return matches[-1]
    return candidates[-1]


async def calendar_view(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    property_id: int | None = None,
    assignee_id: UUID | None = None,
    visit_type: Literal["routine", "tenant_consent", "emergency"] | None = None,
    status: MaintStatus | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return scheduled visits and the filtered unscheduled queue in one request."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Calendar range must include a timezone")
    if end <= start:
        raise ValueError("Calendar range end must be after start")
    if end - start > timedelta(days=370):
        raise ValueError("Calendar range cannot exceed 370 days")

    ticket_statement = select(MaintTicket).where(MaintTicket.status.in_(OPEN_LIST_STATUSES))
    if property_id is not None:
        ticket_statement = ticket_statement.where(MaintTicket.property_id == property_id)
    if status is not None:
        ticket_statement = ticket_statement.where(MaintTicket.status == status)
    tickets = list((await db.scalars(ticket_statement.order_by(MaintTicket.created_at))).all())
    ticket_by_id = {ticket.id: ticket for ticket in tickets}
    ticket_ids = list(ticket_by_id)
    orders = (
        list(
            (
                await db.scalars(
                    select(MaintWorkOrder)
                    .where(MaintWorkOrder.ticket_id.in_(ticket_ids))
                    .order_by(MaintWorkOrder.created_at)
                )
            ).all()
        )
        if ticket_ids
        else []
    )
    order_ids = [order.id for order in orders]
    events = (
        list(
            (
                await db.scalars(
                    select(MaintEvent)
                    .where(MaintEvent.work_order_id.in_(order_ids))
                    .order_by(MaintEvent.created_at)
                )
            ).all()
        )
        if order_ids
        else []
    )
    events_by_order: dict[UUID, list[MaintEvent]] = {}
    for event in events:
        if event.work_order_id is not None:
            events_by_order.setdefault(event.work_order_id, []).append(event)

    properties = list((await db.scalars(select(RentalProperty).order_by(RentalProperty.street_address))).all())
    property_by_id = {prop.id: prop for prop in properties}
    unit_ids = [ticket.unit_id for ticket in tickets if ticket.unit_id is not None]
    units = (
        list((await db.scalars(select(RentalUnit).where(RentalUnit.id.in_(unit_ids)))).all())
        if unit_ids
        else []
    )
    unit_by_id = {unit.id: unit for unit in units}
    users = list((await db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name))).all())
    vendors = list((await db.scalars(select(MaintVendor).where(MaintVendor.is_active.is_(True)).order_by(MaintVendor.name))).all())
    user_by_id = {user.id: user for user in users}
    vendor_by_id = {vendor.id: vendor for vendor in vendors}
    checked_at = now or datetime.now(timezone.utc)

    visits: list[dict[str, object]] = []
    unscheduled: list[dict[str, object]] = []
    orders_by_ticket: dict[UUID, list[MaintWorkOrder]] = {}
    for order in orders:
        orders_by_ticket.setdefault(order.ticket_id, []).append(order)

    def assignee(order: MaintWorkOrder) -> tuple[UUID | None, str]:
        identity = order.assignee_user_id if order.assignee_type == "staff" else order.vendor_id
        if order.assignee_type == "staff":
            person = user_by_id.get(identity)
            return identity, person.full_name if person else "Unknown staff"
        vendor = vendor_by_id.get(identity)
        return identity, vendor.name if vendor else "Unknown vendor"

    for ticket in tickets:
        prop = property_by_id.get(ticket.property_id)
        unit = unit_by_id.get(ticket.unit_id)
        address = prop.street_address if prop else "Unknown property"
        property_name = (prop.group_name or prop.street_address) if prop else address
        unit_name = unit.unit_label if unit and unit.unit_label else "Main building"
        ticket_orders = orders_by_ticket.get(ticket.id, [])
        active_orders = [order for order in ticket_orders if value(order.status) not in {"cancelled"}]
        if not active_orders:
            inferred_type = "emergency" if ticket.is_emergency else "routine"
            if assignee_id is None and (visit_type is None or visit_type == inferred_type):
                unscheduled.append(
                    {
                        "id": f"ticket:{ticket.id}", "ticket_id": ticket.id, "work_order_id": None,
                        "ticket_number": ticket.number, "address": address, "property": property_name,
                        "property_id": ticket.property_id, "unit": unit_name, "title": ticket.title,
                        "assignee_id": None, "assignee_name": "Unassigned", "assignee_type": None,
                        "priority": value(ticket.priority), "ticket_status": value(ticket.status),
                        "created_at": ticket.created_at, "visit_type": inferred_type,
                        "is_emergency": ticket.is_emergency, "draggable": False,
                    }
                )
            continue

        for order in active_orders:
            assigned_id, assigned_name = assignee(order)
            if assignee_id is not None and assigned_id != assignee_id:
                continue
            order_events = events_by_order.get(order.id, [])
            schedule_event = _calendar_event_for_start(order_events, {"work_order_scheduled"}, order.scheduled_start)
            access_basis = str((schedule_event.payload or {}).get("access_basis", "routine")) if schedule_event else ("emergency" if ticket.is_emergency else "routine")
            if visit_type is not None and access_basis != visit_type:
                continue
            is_completed = order.scheduled_visit_status == "completed" or value(order.status) == "completed"
            if order.scheduled_start is not None and order.scheduled_visit_status != "cancelled":
                visit_end = order.scheduled_end or order.scheduled_start + timedelta(hours=1)
                if order.scheduled_start < end and visit_end > start:
                    notice_event = _calendar_event_for_start(order_events, NOTICE_EVENT_TYPES, order.scheduled_start)
                    message = await db.get(MaintSmsMessage, notice_event.sms_message_id) if notice_event and notice_event.sms_message_id else None
                    visits.append(
                        {
                            "id": order.id, "ticket_id": ticket.id, "work_order_id": order.id,
                            "ticket_number": ticket.number, "work_order_number": order.number,
                            "address": address, "property": property_name, "property_id": ticket.property_id,
                            "unit": unit_name, "title": order.scope, "assignee_id": assigned_id,
                            "assignee_name": assigned_name, "assignee_type": order.assignee_type,
                            "start": order.scheduled_start, "end": visit_end, "visit_type": access_basis,
                            "visit_status": "completed" if is_completed else "scheduled",
                            "ticket_status": value(ticket.status), "priority": value(ticket.priority),
                            "notice_status": _calendar_notice_status(message),
                            "notice_error": message.error_code if message and _calendar_notice_status(message) == "failed" else None,
                            "draggable": bool(not is_completed and order.scheduled_visit_status == "scheduled" and order.scheduled_start > checked_at),
                            "href": f"/rentals/maintenance/{ticket.id}#work-order-{order.id}",
                        }
                    )
                continue
            if not is_completed:
                unscheduled.append(
                    {
                        "id": str(order.id), "ticket_id": ticket.id, "work_order_id": order.id,
                        "ticket_number": ticket.number, "work_order_number": order.number,
                        "address": address, "property": property_name, "property_id": ticket.property_id,
                        "unit": unit_name, "title": order.scope, "assignee_id": assigned_id,
                        "assignee_name": assigned_name, "assignee_type": order.assignee_type,
                        "priority": value(ticket.priority), "ticket_status": value(ticket.status),
                        "created_at": ticket.created_at, "visit_type": access_basis,
                        "is_emergency": ticket.is_emergency, "draggable": True,
                    }
                )

    priority_order = {"emergency": 0, "urgent": 1, "routine": 2, "low": 3, None: 4}
    unscheduled.sort(key=lambda item: (0 if item["is_emergency"] else 1, priority_order.get(item["priority"], 4), item["created_at"]))
    return {
        "timezone": settings.timezone,
        "visits": visits,
        "unscheduled": unscheduled,
        "properties": [{"id": prop.id, "name": prop.group_name or prop.street_address} for prop in properties],
        "assignees": [
            *[{"id": user.id, "name": user.full_name, "type": "staff"} for user in users],
            *[{"id": vendor.id, "name": vendor.name, "type": "vendor"} for vendor in vendors],
        ],
    }


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
                        "retryable": (
                            event.event_type == "message"
                            and sms.status == "failed"
                            and sms.cancelled_at is None
                            and sms.provider_sid is None
                        ),
                        "error_code": sms.error_code,
                        "failure_reason": (
                            sms_failure_reason(sms.error_code) if sms.status == "failed" else None
                        ),
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
        body=render_tenant_reply(body) if target == "tenant" else body,
        ticket_id=ticket.id,
        work_order_id=work_order_id,
        media_attachment_ids=[item.id for item in attachments],
        automated=False,
        append_signature=target != "tenant",
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


async def render_scheduled_visit_message(
    db: AsyncSession,
    ticket: MaintTicket,
    *,
    start: datetime,
    end: datetime,
    access_basis: Literal["routine", "tenant_consent", "emergency"],
    reason: str | None,
) -> str:
    address, unit_label = await _ticket_address_and_unit(db, ticket)
    local_timezone = ZoneInfo(settings.timezone)
    local_start = start.astimezone(local_timezone)
    local_end = end.astimezone(local_timezone)
    values: dict[str, object] = {
        "address": address,
        "unit": unit_label,
        "weekday": local_start.strftime("%a"),
        "date": local_start.strftime("%b %-d"),
        "start_time": local_start.strftime("%-I:%M %p"),
        "end_time": local_end.strftime("%-I:%M %p"),
        "reason": reason.strip() if reason else "",
    }
    if access_basis == "emergency":
        values["emergency_phone"] = format_phone(settings.privi_emergency_phone)
    template = {
        "routine": "tenant_entry_notice",
        "tenant_consent": "tenant_consent_confirmation",
        "emergency": "tenant_emergency_on_way",
    }[access_basis]
    return render_template(template, **values)


async def preview_schedule_work(
    db: AsyncSession,
    ticket: MaintTicket,
    *,
    work_order_id: UUID,
    start: datetime,
    end: datetime,
    access_basis: Literal["routine", "tenant_consent", "emergency"] = "routine",
    consent_evidence: str | None = None,
    reason: str | None = None,
    now: datetime | None = None,
) -> str:
    order = await db.get(MaintWorkOrder, work_order_id)
    if order is None or order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    scheduled_at = now or datetime.now(timezone.utc)
    notice_sent_at = (
        quiet_hours_release(scheduled_at) or scheduled_at
        if access_basis == "routine"
        else scheduled_at
    )
    validate_work_order_schedule(
        ticket,
        start,
        end,
        access_basis=access_basis,
        consent_evidence=consent_evidence,
        reason=reason,
        now=scheduled_at,
        notice_sent_at=notice_sent_at,
    )
    return await render_scheduled_visit_message(
        db,
        ticket,
        start=start,
        end=end,
        access_basis=access_basis,
        reason=reason,
    )


async def schedule_work(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    work_order_id: UUID,
    start: datetime,
    end: datetime,
    access_basis: Literal["routine", "tenant_consent", "emergency"] = "routine",
    consent_evidence: str | None = None,
    reason: str | None = None,
    now: datetime | None = None,
) -> None:
    order = await db.get(MaintWorkOrder, work_order_id)
    if order is None or order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    scheduled_at = now or datetime.now(timezone.utc)
    entry_notice_required = access_basis == "routine"
    notice_sent_at = (
        quiet_hours_release(scheduled_at) or scheduled_at
        if entry_notice_required
        else scheduled_at
    )
    previous_start = getattr(order, "scheduled_start", None)
    previous_end = getattr(order, "scheduled_end", None)
    is_reschedule = bool(
        previous_start
        and getattr(order, "scheduled_visit_status", None) == "scheduled"
        and (previous_start != start or previous_end != end)
    )
    # Validate the replacement before a cancellation or any other side effect is queued.
    validate_work_order_schedule(
        ticket,
        start,
        end,
        access_basis=access_basis,
        consent_evidence=consent_evidence,
        reason=reason,
        now=scheduled_at,
        notice_sent_at=notice_sent_at,
    )
    if is_reschedule and ticket.reporter_phone_e164:
        await _queue_visit_cancellation(
            db,
            ticket,
            order,
            actor,
            scheduled_start=previous_start,
            now=scheduled_at,
            require_prior_notice=False,
        )
    await schedule_work_order(
        db,
        ticket,
        order,
        actor,
        start,
        end,
        access_basis=access_basis,
        consent_evidence=consent_evidence,
        reason=reason,
        now=scheduled_at,
        notice_sent_at=notice_sent_at,
    )
    if is_reschedule:
        db.add(
            MaintEvent(
                ticket_id=ticket.id,
                work_order_id=order.id,
                event_type="scheduled_visit_rescheduled",
                channel=MaintEventChannel.WEB,
                visibility=MaintVisibility.INTERNAL,
                direction=MaintDirection.NONE,
                actor_party=actor.party,
                actor_user_id=actor.user_id,
                body=f"Visit moved from {_visit_start_label(previous_start)} to {_visit_start_label(start)}.",
                payload={
                    "old_start": previous_start.isoformat(),
                    "old_end": previous_end.isoformat() if previous_end else None,
                    "new_start": start.isoformat(),
                    "new_end": end.isoformat(),
                },
                created_at=scheduled_at,
            )
        )
    local_timezone = ZoneInfo(settings.timezone)
    local_start = start.astimezone(local_timezone)
    local_end = end.astimezone(local_timezone)
    window = f"{local_start.strftime('%b %-d, %-I:%M %p')}–{local_end.strftime('%-I:%M %p')}"
    if ticket.reporter_phone_e164:
        try:
            outgoing = await render_scheduled_visit_message(
                db,
                ticket,
                start=start,
                end=end,
                access_basis=access_basis,
                reason=reason,
            )
            message = await queue_sms(
                db,
                to=ticket.reporter_phone_e164,
                body=outgoing,
                ticket_id=ticket.id,
                work_order_id=order.id,
                automated=True,
                emergency=access_basis == "emergency",
                actor_party=MaintParty.STAFF,
                actor_user_id=actor.user_id,
                now=scheduled_at,
            )
            event_type = {
                "routine": "entry_notice_sent",
                "tenant_consent": "tenant_consent_confirmation_sent",
                "emergency": "emergency_on_way_sent",
            }[access_basis]
            db.add(
                MaintEvent(
                    ticket_id=ticket.id,
                    work_order_id=order.id,
                    event_type=event_type,
                    channel=MaintEventChannel.SMS,
                    visibility=MaintVisibility.EXTERNAL,
                    direction=MaintDirection.OUTBOUND,
                    actor_party=MaintParty.STAFF,
                    actor_user_id=actor.user_id,
                    body=outgoing,
                    sms_message_id=message.id,
                    payload={
                        "access_basis": access_basis,
                        "reason": reason.strip() if reason else None,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                    },
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


def _visit_view(order: MaintWorkOrder) -> dict[str, object]:
    return {
        "work_order_id": order.id,
        "work_order_number": order.number,
        "scheduled_start": order.scheduled_start,
        "scheduled_end": order.scheduled_end,
    }


async def _ticket_work_orders(db: AsyncSession, ticket_id: UUID) -> list[MaintWorkOrder]:
    return list(
        (
            await db.scalars(
                select(MaintWorkOrder)
                .where(MaintWorkOrder.ticket_id == ticket_id)
                .order_by(MaintWorkOrder.created_at)
            )
        ).all()
    )


def _future_scheduled_visits(
    orders: list[MaintWorkOrder],
    *,
    now: datetime | None = None,
) -> list[MaintWorkOrder]:
    return [order for order in orders if is_future_scheduled_visit(order, now=now)]


def _visit_start_label(start: datetime) -> str:
    local = start.astimezone(ZoneInfo(settings.timezone))
    return local.strftime("%b %-d, %-I:%M %p")


async def _queue_visit_cancellation(
    db: AsyncSession,
    ticket: MaintTicket,
    order: MaintWorkOrder,
    actor: ActorContext,
    *,
    scheduled_start: datetime,
    now: datetime,
    require_prior_notice: bool = True,
) -> bool:
    if require_prior_notice:
        notification_sent = await db.scalar(
            select(MaintEvent.id)
            .where(
                MaintEvent.ticket_id == ticket.id,
                MaintEvent.work_order_id == order.id,
                MaintEvent.event_type.in_(NOTICE_EVENT_TYPES),
            )
            .limit(1)
        )
        if notification_sent is None:
            return False
    if not ticket.reporter_phone_e164:
        return False
    try:
        address, unit_label = await _ticket_address_and_unit(db, ticket)
        local_start = scheduled_start.astimezone(ZoneInfo(settings.timezone))
        await queue_sms(
            db,
            to=ticket.reporter_phone_e164,
            body=render_template(
                "tenant_visit_cancelled",
                address=address,
                unit=unit_label,
                weekday=local_start.strftime("%a"),
                date=local_start.strftime("%b %-d"),
                start_time=local_start.strftime("%-I:%M %p"),
            ),
            ticket_id=ticket.id,
            work_order_id=order.id,
            automated=True,
            emergency=ticket.is_emergency,
            actor_party=MaintParty.STAFF,
            actor_user_id=actor.user_id,
            now=now,
        )
    except SmsOptedOutError:
        return False
    return True


async def set_scheduled_visit_status(
    db: AsyncSession,
    ticket: MaintTicket,
    order: MaintWorkOrder,
    actor: ActorContext,
    *,
    status: str,
    now: datetime | None = None,
) -> None:
    if order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    if status not in {"completed", "cancelled"}:
        raise ValueError("Scheduled visit must be completed or cancelled")
    if order.scheduled_start is None or order.scheduled_visit_status != "scheduled":
        raise ValueError("This work order has no active scheduled visit")

    changed_at = now or datetime.now(timezone.utc)
    order.scheduled_visit_status = status
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            work_order_id=order.id,
            event_type=f"scheduled_visit_{status}",
            channel=MaintEventChannel.WEB,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            body=(
                f"Scheduled visit for {_visit_start_label(order.scheduled_start)} was {status}."
            ),
            payload={
                "work_order": order.number,
                "scheduled_start": order.scheduled_start.isoformat(),
                "scheduled_end": order.scheduled_end.isoformat() if order.scheduled_end else None,
                "status": status,
            },
            created_at=changed_at,
        )
    )

    if status == "cancelled" and ticket.reporter_phone_e164:
        await _queue_visit_cancellation(
            db,
            ticket,
            order,
            actor,
            scheduled_start=order.scheduled_start,
            now=changed_at,
        )
    await db.flush()


async def update_scheduled_visit(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    work_order_id: UUID,
    status: str,
) -> None:
    order = await db.get(MaintWorkOrder, work_order_id)
    if order is None:
        raise ValueError("Work order not found")
    await set_scheduled_visit_status(db, ticket, order, actor, status=status)


async def resolve_ticket(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    note: str,
    cancel_scheduled_visit_ids: list[UUID] | None = None,
) -> None:
    if MaintStatus(ticket.status) == MaintStatus.RESOLVED:
        return
    orders = await _ticket_work_orders(db, ticket.id)
    blockers = _future_scheduled_visits(orders)
    requested = set(cancel_scheduled_visit_ids or [])
    blocker_ids = {order.id for order in blockers}
    if requested - blocker_ids:
        raise ValueError("A selected scheduled visit is no longer active")
    for order in blockers:
        if order.id in requested:
            await set_scheduled_visit_status(db, ticket, order, actor, status="cancelled")
    remaining = [order for order in blockers if order.id not in requested]
    if remaining:
        labels = ", ".join(
            f"{order.number} ({_visit_start_label(order.scheduled_start)})"
            for order in remaining
            if order.scheduled_start is not None
        )
        raise ValueError(f"Resolve blocked by scheduled visits: {labels}")
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
) -> tuple[bool, list[dict[str, object]]]:
    order = await db.get(MaintWorkOrder, work_order_id)
    if order is None or order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    all_complete = await complete_work_order(
        db,
        ticket,
        order,
        actor,
        completion_notes=completion_notes,
        cost_actual=cost_actual,
    )
    future_visits = [_visit_view(order)] if is_future_scheduled_visit(order) else []
    return all_complete, future_visits


async def cancel_message(
    db: AsyncSession,
    message_id: UUID,
    actor: ActorContext,
) -> None:
    await cancel_held_sms(db, message_id, actor)


async def retry_message(
    db: AsyncSession,
    message_id: UUID,
    actor: ActorContext,
) -> None:
    await retry_failed_sms(db, message_id, actor)


async def acknowledge_ticket(db: AsyncSession, ticket: MaintTicket, actor: ActorContext) -> bool:
    return await acknowledge_emergency(db, ticket, actor, channel=MaintEventChannel.WEB)
