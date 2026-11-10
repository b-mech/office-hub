"""Capability-scoped vendor access. Never serialize tickets or tenant contacts."""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.maintenance import (MaintAttachment, MaintDirection, MaintEvent, MaintEventChannel,
    MaintParty, MaintStatus, MaintTicket, MaintVendor, MaintVisibility, MaintWorkOrder, MaintWorkOrderStatus)
from app.models.rentals import RentalProperty, RentalUnit
from app.schemas.maintenance import VendorPortalAction
from app.services.maintenance.media import store_attachment, validate_file_count
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.tokens import hash_token
from app.services.maintenance.work_orders import complete_work_order, start_work_order, validate_work_order_schedule

class InvalidVendorLink(ValueError): pass
class VendorActionConflict(ValueError): pass

TERMINAL = {MaintStatus.RESOLVED, MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def public_text(value: str | None) -> str | None:
    if not value: return value
    # No contact fields are serialized, and common phone formats in free text
    # are withheld too. Do not include internal filenames or event payloads.
    import phonenumbers
    for match in reversed(list(phonenumbers.PhoneNumberMatcher(value, "CA"))):
        value = value[:match.start] + "[phone withheld]" + value[match.end:]
    return re.sub(r"(?<!\w)(?:\+?1[\s().-]*)?(?:\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{4}(?!\w)", "[phone withheld]", value)


async def resolve_vendor_link(db: AsyncSession, token: str, *, lock: bool = False, now: datetime | None = None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token): raise InvalidVendorLink()
    query = select(MaintWorkOrder).where(MaintWorkOrder.access_token_hash == hash_token(token))
    order = await db.scalar(query.with_for_update() if lock else query)
    checked = now or datetime.now(timezone.utc)
    if order is None or order.assignee_type != "vendor" or not order.vendor_id or order.status in {MaintWorkOrderStatus.DECLINED, MaintWorkOrderStatus.CANCELLED}:
        raise InvalidVendorLink()
    expiry = order.token_expires_at or (_aware(order.created_at) + timedelta(days=30))
    if _aware(expiry) <= checked: raise InvalidVendorLink()
    vendor = await db.get(MaintVendor, order.vendor_id)
    query = select(MaintTicket).where(MaintTicket.id == order.ticket_id)
    ticket = await db.scalar(query.with_for_update() if lock else query)
    if vendor is None or not vendor.is_active or ticket is None or ticket.status in TERMINAL:
        raise InvalidVendorLink()
    return order, ticket, vendor


def _event(db, order, ticket, vendor, action: str, body: str, *, payload=None):
    event = MaintEvent(ticket_id=ticket.id, work_order_id=order.id, event_type="message",
        channel=MaintEventChannel.WEB, visibility=MaintVisibility.EXTERNAL,
        direction=MaintDirection.INBOUND, actor_party=MaintParty.VENDOR, actor_vendor_id=vendor.id,
        body=body, payload={"vendor_action": action, **(payload or {})})
    db.add(event)
    ticket.updated_at = datetime.now(timezone.utc)
    return event


async def portal_view(db, order, ticket, vendor):
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    photos = list((await db.scalars(select(MaintAttachment).where(
        MaintAttachment.work_order_id == order.id, MaintAttachment.uploaded_by_party == MaintParty.VENDOR,
        MaintAttachment.kind == "photo").order_by(MaintAttachment.created_at))).all())
    return {"number": order.number, "status": order.status, "vendor_name": public_text(vendor.name),
        "scope": public_text(order.scope), "address": public_text(prop.street_address if prop else ""),
        "unit": public_text(unit.unit_label) if unit else None, "entry_notes": public_text(ticket.entry_notes),
        "entry_permission": ticket.entry_permission, "scheduled_start": order.scheduled_start,
        "scheduled_end": order.scheduled_end, "cost_estimate": str(order.cost_estimate) if order.cost_estimate is not None else None,
        "completion_notes": public_text(order.completion_notes), "is_emergency": ticket.is_emergency,
        "emergency_acknowledged": bool(ticket.emergency_acked_at),
        "photos": [{"id": p.id, "label": f"Photo {i+1}"} for i,p in enumerate(photos)]}


async def apply_vendor_action(db, order, ticket, vendor, data: VendorPortalAction, *, now=None):
    checked = now or datetime.now(timezone.utc)
    status = MaintWorkOrderStatus(order.status)
    actor = ActorContext(MaintParty.VENDOR, vendor_id=vendor.id)
    action = data.action
    payload = {}
    if action == "accept":
        if status != MaintWorkOrderStatus.OFFERED: raise VendorActionConflict("Only an offered work order can be accepted")
        order.status = MaintWorkOrderStatus.ACCEPTED
        body = "Vendor accepted the work order."
    elif action == "decline":
        if status not in {MaintWorkOrderStatus.OFFERED, MaintWorkOrderStatus.ACCEPTED}:
            raise VendorActionConflict("Ask staff to cancel an already scheduled or started visit")
        order.status = MaintWorkOrderStatus.DECLINED
        order.decline_reason = data.notes
        order.access_token_hash = None
        body = f"Vendor declined: {data.notes}"
    elif action == "propose_schedule":
        if status not in {MaintWorkOrderStatus.ACCEPTED, MaintWorkOrderStatus.SCHEDULED}:
            raise VendorActionConflict("Accept the work order before proposing a visit")
        validate_work_order_schedule(ticket, data.start, data.end, reason="Vendor proposed visit", now=checked)
        # A proposal is NOT an appointment or an entry notice. Staff must use
        # the existing scheduling workflow, including documented exemptions.
        payload = {"start": data.start.isoformat(), "end": data.end.isoformat(), "requires_staff_confirmation": True}
        body = f"Vendor proposed {data.start.isoformat()} to {data.end.isoformat()}. {data.notes or ''}".strip()
    elif action == "confirm_schedule":
        if status != MaintWorkOrderStatus.SCHEDULED or not order.scheduled_start or order.scheduled_visit_status != "scheduled":
            raise VendorActionConflict("Staff must schedule the visit first")
        if order.scheduled_end and _aware(order.scheduled_end) <= checked:
            raise VendorActionConflict("This visit window has passed; ask staff to reschedule")
        payload = {"start": order.scheduled_start.isoformat(), "end": order.scheduled_end.isoformat() if order.scheduled_end else None}
        body = "Vendor confirmed the staff-scheduled visit."
    elif action == "start":
        if status != MaintWorkOrderStatus.SCHEDULED or order.scheduled_visit_status != "scheduled" or not order.scheduled_start or not order.scheduled_end:
            raise VendorActionConflict("Staff must schedule the visit before work starts")
        if not (_aware(order.scheduled_start) <= checked < _aware(order.scheduled_end)):
            raise VendorActionConflict("Work can start only within the staff-scheduled visit window")
        if ticket.is_emergency and not ticket.emergency_acked_at:
            raise VendorActionConflict("Staff must acknowledge the emergency before work starts")
        await start_work_order(db, ticket, order, actor)
        body = "Vendor marked work in progress."
    else:
        if status != MaintWorkOrderStatus.IN_PROGRESS: raise VendorActionConflict("Start work before completing it")
        await complete_work_order(db, ticket, order, actor, completion_notes=data.notes or "", now=checked, channel=MaintEventChannel.WEB)
        # Staff still resolves the ticket; vendors cannot resolve/close it.
        body = f"Vendor completed the work: {data.notes}"
    _event(db, order, ticket, vendor, action, body, payload=payload)
    await db.flush()


async def upload_vendor_photos(db, order, ticket, vendor, files):
    if order.status == MaintWorkOrderStatus.COMPLETED: raise VendorActionConflict("Completed work is read-only")
    existing = int(await db.scalar(select(func.count()).select_from(MaintAttachment).where(
        MaintAttachment.work_order_id == order.id, MaintAttachment.uploaded_by_party == MaintParty.VENDOR)) or 0)
    validate_file_count(existing + len(files), party=MaintParty.VENDOR)
    for filename, content in files:
        event = _event(db, order, ticket, vendor, "photo", "Vendor added a photo.")
        await db.flush()
        attachment = await store_attachment(db, ticket_id=ticket.id, work_order_id=order.id,
            event_id=event.id, content=content, original_filename=filename, uploaded_by_party=MaintParty.VENDOR)
        event.payload = {**event.payload, "attachment_id": str(attachment.id)}
    await db.flush()
