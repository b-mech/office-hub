"""Staff intake uses the same events, state machine, SLA, media and SMS guards."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.maintenance import MaintDirection, MaintEvent, MaintEventChannel, MaintParty, MaintVisibility
from app.models.rentals import RentalProperty, RentalUnit
from app.schemas.maintenance import StaffTicketCreate
from app.services.maintenance.media import store_attachment, validate_file_count
from app.services.maintenance.notifier import get_maintenance_notifier
from app.services.maintenance.sms.outbound import SmsOptedOutError, queue_sms
from app.services.maintenance.sms.templates import render_template
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.tickets import TicketCreate, create_ticket, triage_ticket


def confirmation_policy(phone: str | None, opted_in: bool) -> str:
    if not opted_in:
        return "not_requested"
    if not phone:
        return "no_phone"
    if settings.is_staging and phone not in settings.staging_sms_allowlist_values:
        return "blocked_staging"
    return "eligible"


async def create_staff_ticket(db: AsyncSession, data: StaffTicketCreate, actor: ActorContext,
                              *, files: list[tuple[str | None, bytes]] | None = None):
    prop = await db.get(RentalProperty, data.property_id)
    if prop is None:
        raise ValueError("Property not found")
    unit = await db.get(RentalUnit, data.unit_id) if data.unit_id else None
    if data.unit_id and (unit is None or unit.property_id != prop.id):
        raise ValueError("Choose a unit belonging to the selected property")
    validate_file_count(len(files or []), party=MaintParty.STAFF)
    now = datetime.now(timezone.utc)
    ticket = await create_ticket(db, TicketCreate(
        property_id=prop.id, unit_id=unit.id if unit else None, lease_id=None,
        source="staff", reporter_party=MaintParty.STAFF,
        reporter_name=data.reporter_name, reporter_phone=data.reporter_phone or None,
        reporter_verified=False, title=data.title, description=data.description,
        category=data.category, priority=data.priority, is_emergency=data.is_emergency,
        entry_permission=data.entry_permission, entry_notes=data.entry_notes,
        confirmation_sms_opt_in=data.sms_opt_in,
    ), actor, channel=MaintEventChannel.WEB, visibility=MaintVisibility.INTERNAL,
       direction=MaintDirection.NONE, now=now)
    # The creator is a staff triager and has explicitly supplied classification.
    # This does NOT acknowledge an emergency or waive any entry-notice policy.
    await triage_ticket(db, ticket, actor, category=data.category, priority=data.priority,
                        is_emergency=ticket.is_emergency, title=data.title,
                        staff_summary="Created and classified by staff", now=now)
    for filename, content in files or []:
        event = MaintEvent(ticket_id=ticket.id, event_type="attachment_added",
            channel=MaintEventChannel.WEB, visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE, actor_party=MaintParty.STAFF, actor_user_id=actor.user_id)
        db.add(event)
        await db.flush()
        attachment = await store_attachment(db, ticket_id=ticket.id, content=content,
            original_filename=filename, uploaded_by_party=MaintParty.STAFF, event_id=event.id)
        event.payload = {"attachment_id": str(attachment.id)}
    confirmation = confirmation_policy(ticket.reporter_phone_e164, data.sms_opt_in)
    if confirmation == "eligible":
        try:
            await queue_sms(db, to=ticket.reporter_phone_e164,
                body=render_template("tenant_intake_confirm", number=ticket.number,
                    unit=unit.unit_label if unit and unit.unit_label else prop.street_address),
                ticket_id=ticket.id, automated=True, emergency=ticket.is_emergency,
                actor_party=MaintParty.STAFF, actor_user_id=actor.user_id)
            confirmation = "queued"
        except SmsOptedOutError:
            confirmation = "blocked_opt_out"
    if confirmation.startswith("blocked"):
        db.add(MaintEvent(ticket_id=ticket.id, event_type="sms_confirmation_blocked",
            channel=MaintEventChannel.WEB, visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE, actor_party=MaintParty.STAFF,
            actor_user_id=actor.user_id, payload={"reason": confirmation}))
    await get_maintenance_notifier().ticket_created(db, ticket)
    await db.flush()
    return ticket, confirmation
