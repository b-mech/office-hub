from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintPriority,
    MaintStatus,
    MaintTicket,
    MaintVisibility,
)
from app.services.maintenance.errors import InvalidTransitionError
from app.services.maintenance.sla import DEFAULT_SLA_TARGETS, SlaTargets, sla_due_at


ALLOWED_TRANSITIONS: dict[MaintStatus, frozenset[MaintStatus]] = {
    MaintStatus.NEW: frozenset({MaintStatus.TRIAGED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}),
    MaintStatus.TRIAGED: frozenset({MaintStatus.ASSIGNED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}),
    MaintStatus.ASSIGNED: frozenset({MaintStatus.SCHEDULED, MaintStatus.IN_PROGRESS, MaintStatus.TRIAGED, MaintStatus.CANCELLED}),
    MaintStatus.SCHEDULED: frozenset(
        {MaintStatus.IN_PROGRESS, MaintStatus.ASSIGNED, MaintStatus.RESOLVED, MaintStatus.CANCELLED}
    ),
    MaintStatus.IN_PROGRESS: frozenset({MaintStatus.AWAITING_PARTS, MaintStatus.AWAITING_TENANT, MaintStatus.RESOLVED}),
    MaintStatus.AWAITING_PARTS: frozenset({MaintStatus.IN_PROGRESS, MaintStatus.SCHEDULED, MaintStatus.RESOLVED}),
    MaintStatus.AWAITING_TENANT: frozenset({MaintStatus.IN_PROGRESS, MaintStatus.SCHEDULED, MaintStatus.RESOLVED}),
    MaintStatus.RESOLVED: frozenset({MaintStatus.CLOSED, MaintStatus.IN_PROGRESS}),
    MaintStatus.CLOSED: frozenset({MaintStatus.IN_PROGRESS}),
    MaintStatus.CANCELLED: frozenset({MaintStatus.IN_PROGRESS}),
    MaintStatus.DUPLICATE: frozenset({MaintStatus.IN_PROGRESS}),
}


@dataclass(frozen=True)
class ActorContext:
    party: MaintParty
    user_id: UUID | None = None
    vendor_id: UUID | None = None
    phone_e164: str | None = None
    is_admin: bool = False


TransitionHook = Callable[[MaintTicket, MaintStatus, MaintStatus], Awaitable[None]]


def validate_transition(current: MaintStatus, target: MaintStatus, *, is_admin: bool = False) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Cannot move a maintenance ticket from {current.value} to {target.value}")
    if (
        current in {MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}
        and target == MaintStatus.IN_PROGRESS
        and not is_admin
    ):
        raise InvalidTransitionError("Only a maintenance admin can reopen a terminal ticket")


async def transition(
    db: AsyncSession,
    ticket: MaintTicket,
    target: MaintStatus,
    actor: ActorContext,
    reason: str | None = None,
    *,
    channel: MaintEventChannel = MaintEventChannel.SYSTEM,
    now: datetime | None = None,
    sla_targets: SlaTargets = DEFAULT_SLA_TARGETS,
    after_transition: TransitionHook | None = None,
) -> MaintTicket:
    current = MaintStatus(ticket.status)
    target = MaintStatus(target)
    validate_transition(current, target, is_admin=actor.is_admin)
    changed_at = now or datetime.now(timezone.utc)

    ticket.status = target
    ticket.updated_at = changed_at
    if target == MaintStatus.TRIAGED:
        ticket.triaged_at = ticket.triaged_at or changed_at
        ticket.triaged_by = actor.user_id
        if ticket.priority is not None:
            ticket.sla_due_at = sla_due_at(ticket.triaged_at, MaintPriority(ticket.priority), sla_targets)
    if target == MaintStatus.RESOLVED:
        ticket.resolved_at = changed_at
    elif target == MaintStatus.CLOSED:
        ticket.closed_at = changed_at
        ticket.close_reason = reason
    elif target == MaintStatus.IN_PROGRESS and current in {
        MaintStatus.RESOLVED,
        MaintStatus.CLOSED,
        MaintStatus.CANCELLED,
        MaintStatus.DUPLICATE,
    }:
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.close_reason = None
        if current == MaintStatus.DUPLICATE:
            ticket.duplicate_of = None

    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            event_type="status_changed",
            channel=channel,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            actor_vendor_id=actor.vendor_id,
            actor_phone_e164=actor.phone_e164,
            body=reason,
            payload={"from": current.value, "to": target.value, **({"reason": reason} if reason else {})},
            created_at=changed_at,
        )
    )
    await db.flush()
    if after_transition is not None:
        await after_transition(ticket, current, target)
    return ticket


def initialize_emergency_sla(
    ticket: MaintTicket,
    *,
    targets: SlaTargets = DEFAULT_SLA_TARGETS,
) -> None:
    if ticket.is_emergency:
        ticket.priority = MaintPriority.EMERGENCY
        ticket.sla_due_at = sla_due_at(ticket.created_at, MaintPriority.EMERGENCY, targets)
