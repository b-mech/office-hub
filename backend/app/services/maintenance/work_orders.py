from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintStatus,
    MaintTicket,
    MaintVisibility,
    MaintWorkOrder,
    MaintWorkOrderStatus,
)
from app.services.maintenance.state_machine import ActorContext, transition
from app.services.maintenance.tokens import generate_token


def status_after_first_work_order(current: MaintStatus, existing_count: int) -> MaintStatus | None:
    return MaintStatus.ASSIGNED if existing_count == 0 and current == MaintStatus.TRIAGED else None


def status_after_schedule(current: MaintStatus) -> MaintStatus | None:
    if current in {MaintStatus.ASSIGNED, MaintStatus.AWAITING_PARTS, MaintStatus.AWAITING_TENANT}:
        return MaintStatus.SCHEDULED
    return None


def status_after_work_started(current: MaintStatus) -> MaintStatus | None:
    if current in {MaintStatus.ASSIGNED, MaintStatus.SCHEDULED, MaintStatus.AWAITING_PARTS, MaintStatus.AWAITING_TENANT}:
        return MaintStatus.IN_PROGRESS
    return None


def all_active_work_orders_complete(statuses: list[MaintWorkOrderStatus]) -> bool:
    active = [status for status in statuses if status != MaintWorkOrderStatus.CANCELLED]
    return bool(active) and all(status == MaintWorkOrderStatus.COMPLETED for status in active)


async def create_work_order(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    assignee_type: str,
    scope: str,
    assignee_user_id: UUID | None = None,
    vendor_id: UUID | None = None,
    cost_estimate: Decimal | None = None,
) -> tuple[MaintWorkOrder, str | None]:
    if assignee_type not in {"staff", "vendor"}:
        raise ValueError("Work order assignee type must be staff or vendor")
    if (assignee_type == "staff") != (assignee_user_id is not None):
        raise ValueError("Staff work orders require exactly one staff assignee")
    if (assignee_type == "vendor") != (vendor_id is not None):
        raise ValueError("Vendor work orders require exactly one vendor")
    if not scope.strip():
        raise ValueError("Work order scope is required")

    sequence = int(
        await db.scalar(select(func.count()).select_from(MaintWorkOrder).where(MaintWorkOrder.ticket_id == ticket.id))
        or 0
    ) + 1
    raw_token: str | None = None
    token_hash: str | None = None
    if assignee_type == "vendor":
        token = generate_token()
        raw_token = token.value
        token_hash = token.digest

    work_order = MaintWorkOrder(
        ticket_id=ticket.id,
        number=f"{ticket.number}-W{sequence}",
        assignee_type=assignee_type,
        assignee_user_id=assignee_user_id,
        vendor_id=vendor_id,
        scope=scope.strip(),
        cost_estimate=cost_estimate,
        access_token_hash=token_hash,
        created_by=actor.user_id,
    )
    db.add(work_order)
    await db.flush()
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            work_order_id=work_order.id,
            event_type="assigned",
            channel=MaintEventChannel.SYSTEM,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            payload={"work_order": work_order.number, "assignee_type": assignee_type},
        )
    )
    derived_status = status_after_first_work_order(MaintStatus(ticket.status), sequence - 1)
    if derived_status is not None:
        await transition(db, ticket, derived_status, actor)
    await db.flush()
    return work_order, raw_token


async def schedule_work_order(
    db: AsyncSession,
    ticket: MaintTicket,
    work_order: MaintWorkOrder,
    actor: ActorContext,
    start: datetime,
    end: datetime,
) -> MaintWorkOrder:
    if end <= start:
        raise ValueError("Scheduled end must be after the start")
    work_order.scheduled_start = start
    work_order.scheduled_end = end
    work_order.status = MaintWorkOrderStatus.SCHEDULED
    derived_status = status_after_schedule(MaintStatus(ticket.status))
    if derived_status is not None:
        await transition(db, ticket, derived_status, actor)
    await db.flush()
    return work_order


async def start_work_order(
    db: AsyncSession,
    ticket: MaintTicket,
    work_order: MaintWorkOrder,
    actor: ActorContext,
) -> MaintWorkOrder:
    work_order.status = MaintWorkOrderStatus.IN_PROGRESS
    derived_status = status_after_work_started(MaintStatus(ticket.status))
    if derived_status is not None:
        await transition(db, ticket, derived_status, actor)
    await db.flush()
    return work_order


async def complete_work_order(
    db: AsyncSession,
    ticket: MaintTicket,
    work_order: MaintWorkOrder,
    actor: ActorContext,
    *,
    completion_notes: str,
    cost_actual: Decimal | None = None,
    now: datetime | None = None,
) -> bool:
    completed_at = now or datetime.now(timezone.utc)
    work_order.status = MaintWorkOrderStatus.COMPLETED
    work_order.completion_notes = completion_notes.strip() or None
    work_order.cost_actual = cost_actual
    work_order.completed_at = completed_at
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            work_order_id=work_order.id,
            event_type="work_order_completed",
            channel=MaintEventChannel.SYSTEM,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            actor_vendor_id=actor.vendor_id,
            body=work_order.completion_notes,
            payload={"work_order": work_order.number},
            created_at=completed_at,
        )
    )
    await db.flush()
    remaining = int(
        await db.scalar(
            select(func.count())
            .select_from(MaintWorkOrder)
            .where(
                MaintWorkOrder.ticket_id == ticket.id,
                MaintWorkOrder.status.not_in((MaintWorkOrderStatus.COMPLETED, MaintWorkOrderStatus.CANCELLED)),
            )
        )
        or 0
    )
    return remaining == 0
