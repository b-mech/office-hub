from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import (
    MaintCategory,
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintPriority,
    MaintStatus,
    MaintTicket,
    MaintVisibility,
)
from app.services.maintenance.phones import normalize_phone
from app.services.maintenance.sla import DEFAULT_SLA_TARGETS, SlaTargets, sla_due_at
from app.services.maintenance.state_machine import ActorContext, transition


EMERGENCY_CATEGORIES = frozenset(
    {
        MaintCategory.WATER_LEAK,
        MaintCategory.NO_HEAT,
        MaintCategory.GAS_SMELL,
        MaintCategory.NO_POWER,
        MaintCategory.SECURITY,
    }
)


@dataclass(frozen=True)
class TicketCreate:
    property_id: int
    unit_id: int | None
    lease_id: int | None
    source: str
    reporter_party: MaintParty
    reporter_name: str | None
    reporter_phone: str | None
    reporter_verified: bool
    title: str
    description: str
    category: MaintCategory | None = None
    priority: MaintPriority | None = None
    entry_permission: str = "not_asked"
    entry_notes: str | None = None
    inspection_id: int | None = None


async def create_ticket(
    db: AsyncSession,
    data: TicketCreate,
    actor: ActorContext,
    *,
    channel: MaintEventChannel,
    visibility: MaintVisibility,
    direction: MaintDirection,
    now: datetime | None = None,
    sla_targets: SlaTargets = DEFAULT_SLA_TARGETS,
) -> MaintTicket:
    if len(data.description.strip()) < 10:
        raise ValueError("Ticket description must be at least 10 characters")
    if data.entry_permission not in {"granted", "denied", "not_asked"}:
        raise ValueError("Invalid entry permission")
    created_at = now or datetime.now(timezone.utc)
    is_emergency = data.category in EMERGENCY_CATEGORIES
    priority = MaintPriority.EMERGENCY if is_emergency else data.priority
    ticket = MaintTicket(
        property_id=data.property_id,
        unit_id=data.unit_id,
        lease_id=data.lease_id,
        source=data.source,
        reporter_party=data.reporter_party,
        reporter_name=data.reporter_name.strip() if data.reporter_name else None,
        reporter_phone_e164=normalize_phone(data.reporter_phone) if data.reporter_phone else None,
        reporter_verified=data.reporter_verified,
        title=data.title.strip(),
        description=data.description.strip(),
        category=data.category,
        priority=priority,
        is_emergency=is_emergency,
        entry_permission=data.entry_permission,
        entry_notes=data.entry_notes.strip() if data.entry_notes else None,
        inspection_id=data.inspection_id,
        created_by=actor.user_id,
        created_at=created_at,
        updated_at=created_at,
    )
    if is_emergency:
        ticket.sla_due_at = sla_due_at(created_at, MaintPriority.EMERGENCY, sla_targets)
    db.add(ticket)
    await db.flush()
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            event_type="created",
            channel=channel,
            visibility=visibility,
            direction=direction,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            actor_vendor_id=actor.vendor_id,
            actor_phone_e164=actor.phone_e164,
            payload={"source": data.source},
            created_at=created_at,
        )
    )
    await db.flush()
    return ticket


async def triage_ticket(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    category: MaintCategory,
    priority: MaintPriority,
    is_emergency: bool,
    title: str,
    staff_summary: str | None = None,
    now: datetime | None = None,
    sla_targets: SlaTargets = DEFAULT_SLA_TARGETS,
) -> MaintTicket:
    ticket.category = category
    ticket.priority = MaintPriority.EMERGENCY if is_emergency else priority
    ticket.is_emergency = is_emergency
    ticket.title = title.strip()
    await transition(
        db,
        ticket,
        MaintStatus.TRIAGED,
        actor,
        staff_summary,
        now=now,
        sla_targets=sla_targets,
    )
    return ticket


async def acknowledge_emergency(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> bool:
    if not ticket.is_emergency:
        raise ValueError("Only emergency tickets can be acknowledged")
    if actor.user_id is None:
        raise ValueError("Emergency acknowledgement requires a staff user")
    if ticket.emergency_acked_at is not None:
        return False
    acknowledged_at = now or datetime.now(timezone.utc)
    ticket.emergency_acked_by = actor.user_id
    ticket.emergency_acked_at = acknowledged_at
    ticket.updated_at = acknowledged_at
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            event_type="emergency_acknowledged",
            channel=MaintEventChannel.SLACK,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            created_at=acknowledged_at,
        )
    )
    await db.flush()
    return True


async def cancel_ticket(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    reason: str,
    now: datetime | None = None,
) -> MaintTicket:
    if not reason.strip():
        raise ValueError("A cancellation reason is required")
    return await transition(
        db,
        ticket,
        MaintStatus.CANCELLED,
        actor,
        reason.strip(),
        channel=MaintEventChannel.SLACK,
        now=now,
    )


async def mark_duplicate(
    db: AsyncSession,
    ticket: MaintTicket,
    canonical: MaintTicket,
    actor: ActorContext,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> MaintTicket:
    if ticket.id == canonical.id:
        raise ValueError("A ticket cannot be a duplicate of itself")
    if MaintStatus(canonical.status) in {MaintStatus.CANCELLED, MaintStatus.DUPLICATE}:
        raise ValueError("The canonical ticket cannot be cancelled or duplicate")
    ticket.duplicate_of = canonical.id
    detail = reason.strip() if reason and reason.strip() else f"Duplicate of {canonical.number}"
    return await transition(
        db,
        ticket,
        MaintStatus.DUPLICATE,
        actor,
        detail,
        channel=MaintEventChannel.SLACK,
        now=now,
    )
