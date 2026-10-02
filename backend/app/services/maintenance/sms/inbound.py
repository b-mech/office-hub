from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.maintenance import (
    MaintDirection,
    MaintAttachment,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintSmsMessage,
    MaintStatus,
    MaintTicket,
    MaintVendor,
    MaintVisibility,
    MaintWorkOrder,
    MaintWorkOrderStatus,
)
from app.models.rentals import RentalLease, RentalLeaseTenant, RentalTenant
from app.services.maintenance.media import store_attachment, validate_file_count
from app.services.maintenance.notifier import MaintenanceNotifier
from app.services.maintenance.phones import normalize_phone
from app.services.maintenance.qr import create_temporary_intake_link
from app.services.maintenance.sms.outbound import SmsOptedOutError, queue_sms
from app.services.maintenance.sms.providers import SmsProvider
from app.services.maintenance.sms.templates import render_template
from app.services.maintenance.state_machine import ActorContext, transition


OPEN_STATUSES = {
    MaintStatus.NEW,
    MaintStatus.TRIAGED,
    MaintStatus.ASSIGNED,
    MaintStatus.SCHEDULED,
    MaintStatus.IN_PROGRESS,
    MaintStatus.AWAITING_PARTS,
    MaintStatus.AWAITING_TENANT,
}
ACTIVE_WO_STATUSES = {
    MaintWorkOrderStatus.OFFERED,
    MaintWorkOrderStatus.ACCEPTED,
    MaintWorkOrderStatus.SCHEDULED,
    MaintWorkOrderStatus.IN_PROGRESS,
}
CLOSE_KEYWORDS = {"YES", "Y", "FIXED", "DONE"}


def ringcentral_notification_form(payload: Mapping[str, object]) -> dict[str, str]:
    """Normalize a RingCentral instant-message notification for shared SMS routing."""
    body = payload.get("body")
    if not isinstance(body, Mapping):
        raise ValueError("RingCentral notification body is missing")
    if str(body.get("direction", "")).casefold() != "inbound":
        raise ValueError("RingCentral notification is not an inbound message")
    if str(body.get("type", "")).casefold() not in {"sms", "mms"}:
        raise ValueError("RingCentral notification is not SMS/MMS")

    sender = body.get("from")
    recipients = body.get("to")
    if not isinstance(sender, Mapping) or not isinstance(recipients, list) or not recipients:
        raise ValueError("RingCentral notification is missing sender or recipient")
    sender_phone = str(sender.get("phoneNumber", ""))
    recipient = next(
        (
            item
            for item in recipients
            if isinstance(item, Mapping) and item.get("target") is True
        ),
        recipients[0],
    )
    if not isinstance(recipient, Mapping):
        raise ValueError("RingCentral notification recipient is invalid")

    message_id = str(body.get("id", ""))
    if not sender_phone or not message_id:
        raise ValueError("RingCentral notification is missing sender or message ID")

    form = {
        "From": sender_phone,
        "To": str(recipient.get("phoneNumber", "")),
        "Body": str(body.get("subject", "")),
        "MessageSid": message_id,
    }
    attachments = body.get("attachments", [])
    media = (
        [
            item
            for item in attachments
            if isinstance(item, Mapping)
            and str(item.get("type", "")).casefold() == "mmsattachment"
            and item.get("uri")
        ]
        if isinstance(attachments, list)
        else []
    )
    form["NumMedia"] = str(len(media))
    for index, attachment in enumerate(media):
        form[f"MediaUrl{index}"] = str(attachment["uri"])
        form[f"MediaContentType{index}"] = str(
            attachment.get("contentType", "application/octet-stream")
        )
    return form


class RouteKind(str, Enum):
    VENDOR_WORK_ORDER = "vendor_work_order"
    TENANT_OPEN = "tenant_open"
    TENANT_RECENT_RESOLVED = "tenant_recent_resolved"
    KNOWN_TENANT = "known_tenant"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RouteDecision:
    kind: RouteKind
    ticket_id: object | None = None
    work_order_id: object | None = None
    unit_id: int | None = None
    other_open_numbers: tuple[str, ...] = ()


def choose_route(
    *,
    vendor_work_orders: list[tuple[object, object]],
    open_tickets: list[tuple[object, str]],
    recent_resolved_ticket: object | None,
    known_unit_id: int | None,
) -> RouteDecision:
    if vendor_work_orders:
        ticket_id, work_order_id = vendor_work_orders[0]
        return RouteDecision(RouteKind.VENDOR_WORK_ORDER, ticket_id, work_order_id)
    if open_tickets:
        ticket_id, _ = open_tickets[0]
        return RouteDecision(
            RouteKind.TENANT_OPEN,
            ticket_id,
            other_open_numbers=tuple(number for _, number in open_tickets[1:]),
        )
    if recent_resolved_ticket is not None:
        return RouteDecision(RouteKind.TENANT_RECENT_RESOLVED, recent_resolved_ticket)
    if known_unit_id is not None:
        return RouteDecision(RouteKind.KNOWN_TENANT, unit_id=known_unit_id)
    return RouteDecision(RouteKind.UNKNOWN)


def opt_keyword(body: str) -> bool | None:
    keyword = body.strip().upper()
    if keyword == "STOP":
        return True
    if keyword == "START":
        return False
    return None


def is_close_confirmation(body: str) -> bool:
    return body.strip().upper() in CLOSE_KEYWORDS


async def _route(db: AsyncSession, phone: str, now: datetime) -> RouteDecision:
    vendor_rows = (
        await db.execute(
            select(MaintWorkOrder.ticket_id, MaintWorkOrder.id)
            .join(MaintVendor, MaintVendor.id == MaintWorkOrder.vendor_id)
            .join(MaintTicket, MaintTicket.id == MaintWorkOrder.ticket_id)
            .where(
                MaintVendor.phone_e164 == phone,
                MaintVendor.is_active.is_(True),
                MaintWorkOrder.status.in_(ACTIVE_WO_STATUSES),
                MaintTicket.status.notin_([MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE]),
            )
            .order_by(MaintTicket.updated_at.desc(), MaintWorkOrder.created_at.desc())
        )
    ).all()
    open_rows = (
        await db.execute(
            select(MaintTicket.id, MaintTicket.number)
            .where(MaintTicket.reporter_phone_e164 == phone, MaintTicket.status.in_(OPEN_STATUSES))
            .order_by(MaintTicket.updated_at.desc())
        )
    ).all()
    recent = await db.scalar(
        select(MaintTicket.id)
        .where(
            MaintTicket.reporter_phone_e164 == phone,
            MaintTicket.status == MaintStatus.RESOLVED,
            MaintTicket.resolved_at >= now - timedelta(days=settings.maint_autoclose_days),
        )
        .order_by(MaintTicket.updated_at.desc())
        .limit(1)
    )
    today = date.today()
    known_unit = await db.scalar(
        select(RentalLease.unit_id)
        .join(RentalLeaseTenant, RentalLeaseTenant.lease_id == RentalLease.id)
        .join(RentalTenant, RentalTenant.id == RentalLeaseTenant.tenant_id)
        .where(
            RentalTenant.phone == phone,
            RentalLease.status.in_(["active", "month_to_month"]),
            (RentalLease.lease_end.is_(None) | (RentalLease.lease_end >= today)),
        )
        .order_by(RentalLease.lease_start.desc().nullslast())
        .limit(1)
    )
    return choose_route(
        vendor_work_orders=list(vendor_rows),
        open_tickets=list(open_rows),
        recent_resolved_ticket=recent,
        known_unit_id=known_unit,
    )


async def mirror_opt_out(db: AsyncSession, phone: str, opted_out: bool) -> None:
    await db.execute(
        update(MaintVendor)
        .where(MaintVendor.phone_e164 == phone, MaintVendor.is_active.is_(True))
        .values(sms_opted_out=opted_out)
    )
    await db.execute(
        update(RentalTenant).where(RentalTenant.phone == phone).values(sms_opted_out=opted_out)
    )


async def receive_sms(
    db: AsyncSession,
    provider: SmsProvider,
    notifier: MaintenanceNotifier,
    form: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> MaintSmsMessage:
    now = now or datetime.now(timezone.utc)
    phone = normalize_phone(form.get("From", ""))
    body = form.get("Body", "")
    provider_sid = form.get("MessageSid") or None
    if provider_sid:
        existing = await db.scalar(
            select(MaintSmsMessage).where(MaintSmsMessage.provider_sid == provider_sid)
        )
        if existing is not None:
            return existing
    message = MaintSmsMessage(
        direction=MaintDirection.INBOUND,
        from_e164=phone,
        to_e164=form.get("To", settings.sms_from_number or ""),
        body=body,
        provider_sid=provider_sid,
        status="received",
        created_at=now,
        updated_at=now,
    )
    db.add(message)
    await db.flush()

    decision = await _route(db, phone, now)
    media_party = MaintParty.VENDOR if decision.kind == RouteKind.VENDOR_WORK_ORDER else MaintParty.TENANT
    media_count = int(form.get("NumMedia", "0") or 0)
    validate_file_count(media_count, party=media_party)
    attachment_ids = []
    for index in range(media_count):
        media_url = form.get(f"MediaUrl{index}")
        if not media_url:
            continue
        attachment = await store_attachment(
            db,
            ticket_id=None,
            content=await provider.fetch_media(media_url),
            original_filename=f"sms-{message.provider_sid or message.id}-{index}",
            uploaded_by_party=media_party,
        )
        attachment_ids.append(attachment.id)
    message.media_attachment_ids = attachment_ids

    opt_state = opt_keyword(body)
    if opt_state is not None:
        await mirror_opt_out(db, phone, opt_state)
        if opt_state:
            await notifier.opted_out(phone)

    ticket = await db.get(MaintTicket, decision.ticket_id) if decision.ticket_id else None
    message.ticket_id = ticket.id if ticket else None
    message.work_order_id = decision.work_order_id
    if ticket:
        ticket.updated_at = now
        for attachment_id in attachment_ids:
            attachment = await db.get(MaintAttachment, attachment_id)
            if attachment:
                attachment.ticket_id = ticket.id
                attachment.work_order_id = decision.work_order_id
        payload: dict[str, object] = {"route": decision.kind.value}
        if decision.other_open_numbers:
            payload["also_open"] = list(decision.other_open_numbers)
        db.add(
            MaintEvent(
                ticket_id=ticket.id,
                work_order_id=decision.work_order_id,
                event_type="message",
                channel=MaintEventChannel.SMS,
                visibility=MaintVisibility.EXTERNAL,
                direction=MaintDirection.INBOUND,
                actor_party=MaintParty.VENDOR if decision.kind == RouteKind.VENDOR_WORK_ORDER else MaintParty.TENANT,
                actor_phone_e164=phone,
                body=body,
                payload=payload,
                sms_message_id=message.id,
                created_at=now,
            )
        )
        if ticket.status == MaintStatus.RESOLVED and is_close_confirmation(body):
            await transition(
                db,
                ticket,
                MaintStatus.CLOSED,
                ActorContext(party=MaintParty.TENANT, phone_e164=phone),
                "tenant_confirmed",
                now=now,
            )
    elif decision.kind == RouteKind.KNOWN_TENANT and decision.unit_id is not None and opt_state is None:
        intake_url = await create_temporary_intake_link(db, decision.unit_id)
        try:
            await queue_sms(
                db,
                to=phone,
                body=render_template("tenant_no_open_ticket", intake_url=intake_url),
                automated=True,
            )
        except SmsOptedOutError:
            await notifier.opted_out(phone)
        await notifier.unmatched_message(message, known_tenant=True)
    else:
        await notifier.unmatched_message(message, known_tenant=False)
    await notifier.inbound_message(message, ticket)
    await db.flush()
    return message
