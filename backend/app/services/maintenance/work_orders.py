from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

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
    MaintVendor,
)
from app.models.rentals import RentalProperty, RentalUnit
from app.core.config import settings
from app.services.maintenance.entry_notice import EntryNoticePolicy, validate_entry_notice
from app.services.maintenance.errors import EntryNoticeError
from app.services.maintenance.sms.outbound import queue_sms
from app.services.maintenance.sms.templates import render_template
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


def is_future_scheduled_visit(
    work_order: MaintWorkOrder,
    *,
    now: datetime | None = None,
) -> bool:
    checked_at = now or datetime.now(timezone.utc)
    return bool(
        work_order.scheduled_visit_status == "scheduled"
        and work_order.scheduled_start
        and work_order.scheduled_start > checked_at
    )


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


def validate_work_order_schedule(
    ticket: MaintTicket,
    start: datetime,
    end: datetime,
    *,
    access_basis: Literal["routine", "tenant_consent", "emergency"] = "routine",
    consent_evidence: str | None = None,
    reason: str | None = None,
    now: datetime | None = None,
    notice_sent_at: datetime | None = None,
) -> tuple[str, str | None, str | None]:
    scheduled_at = now or datetime.now(timezone.utc)
    evidence = consent_evidence.strip() if consent_evidence else None
    entry_reason = reason.strip() if reason else None
    if access_basis != "emergency" and not entry_reason:
        raise EntryNoticeError("Reason for entry is required")
    if access_basis == "tenant_consent" and not evidence:
        raise EntryNoticeError(
            "Tenant consent scheduling requires the tenant's message or a staff note as evidence"
        )
    if access_basis != "tenant_consent" and evidence:
        raise EntryNoticeError("Consent evidence can only be used with tenant consent scheduling")
    notice_basis = validate_entry_notice(
        start,
        end,
        notice_sent_at or scheduled_at,
        access_basis=access_basis,
        is_emergency_ticket=ticket.is_emergency,
        policy=EntryNoticePolicy(
            minimum_notice=timedelta(hours=settings.entry_notice_min_hours),
            window_start=settings.entry_window_start,
            window_end=settings.entry_window_end,
            timezone=ZoneInfo(settings.timezone),
        ),
    )
    return notice_basis, evidence, entry_reason


async def schedule_work_order(
    db: AsyncSession,
    ticket: MaintTicket,
    work_order: MaintWorkOrder,
    actor: ActorContext,
    start: datetime,
    end: datetime,
    *,
    access_basis: Literal["routine", "tenant_consent", "emergency"] = "routine",
    consent_evidence: str | None = None,
    reason: str | None = None,
    now: datetime | None = None,
    notice_sent_at: datetime | None = None,
) -> MaintWorkOrder:
    scheduled_at = now or datetime.now(timezone.utc)
    notice_basis, evidence, entry_reason = validate_work_order_schedule(
        ticket,
        start,
        end,
        access_basis=access_basis,
        consent_evidence=consent_evidence,
        reason=reason,
        now=scheduled_at,
        notice_sent_at=notice_sent_at,
    )
    work_order.scheduled_start = start
    work_order.scheduled_end = end
    work_order.scheduled_visit_status = "scheduled"
    work_order.status = MaintWorkOrderStatus.SCHEDULED
    if access_basis != "routine":
        local_timezone = ZoneInfo(settings.timezone)
        local_start = start.astimezone(local_timezone)
        local_end = end.astimezone(local_timezone)
        window = (
            f"{local_start.strftime('%b %-d, %-I:%M %p')}"
            f"–{local_end.strftime('%-I:%M %p')}"
        )
        label = "Tenant consent" if access_basis == "tenant_consent" else "Emergency"
        body = f"{label} scheduling exemption selected for {window}."
        if evidence:
            body = f"{body} Evidence: {evidence}"
        db.add(
            MaintEvent(
                ticket_id=ticket.id,
                work_order_id=work_order.id,
                event_type="entry_policy_exemption",
                channel=MaintEventChannel.WEB,
                visibility=MaintVisibility.INTERNAL,
                direction=MaintDirection.NONE,
                actor_party=actor.party,
                actor_user_id=actor.user_id,
                body=body,
                payload={
                    "access_basis": access_basis,
                    "evidence": evidence,
                    "reason": entry_reason,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
                created_at=scheduled_at,
            )
        )
    db.add(
        MaintEvent(
            ticket_id=ticket.id,
            work_order_id=work_order.id,
            event_type="work_order_scheduled",
            channel=MaintEventChannel.WEB,
            visibility=MaintVisibility.INTERNAL,
            direction=MaintDirection.NONE,
            actor_party=actor.party,
            actor_user_id=actor.user_id,
            payload={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "entry_notice": notice_basis,
                "access_basis": access_basis,
                "reason": entry_reason,
            },
            created_at=scheduled_at,
        )
    )
    derived_status = status_after_schedule(MaintStatus(ticket.status))
    if derived_status is not None:
        await transition(db, ticket, derived_status, actor)
    await db.flush()
    return work_order


async def assign_vendor_work_order(
    db: AsyncSession,
    ticket: MaintTicket,
    actor: ActorContext,
    *,
    vendor_id: UUID,
    scope: str,
    cost_estimate: Decimal | None = None,
) -> MaintWorkOrder:
    if not settings.public_base_url.strip():
        raise ValueError("PUBLIC_BASE_URL is required before assigning a vendor")
    vendor = await db.get(MaintVendor, vendor_id)
    if vendor is None or not vendor.is_active:
        raise ValueError("Active vendor not found")
    prop = await db.get(RentalProperty, ticket.property_id)
    unit = await db.get(RentalUnit, ticket.unit_id) if ticket.unit_id else None
    if prop is None:
        raise ValueError("Ticket property not found")
    area = prop.street_address
    if unit and unit.unit_label:
        area = f"{area} · {unit.unit_label}"

    work_order, raw_token = await create_work_order(
        db,
        ticket,
        actor,
        assignee_type="vendor",
        scope=scope,
        vendor_id=vendor.id,
        cost_estimate=cost_estimate,
    )
    if raw_token is None:
        raise RuntimeError("Vendor work order token was not generated")
    link = f"{settings.public_base_url.rstrip('/')}/w/{raw_token}"
    await queue_sms(
        db,
        to=vendor.phone_e164,
        body=render_template(
            "vendor_offer",
            number=work_order.number,
            area=area,
            scope=work_order.scope,
            entry_notes=(
                f" Entry notes: {ticket.entry_notes.strip()}."
                if ticket.entry_notes and ticket.entry_notes.strip()
                else ""
            ),
            link=link,
        ),
        ticket_id=ticket.id,
        work_order_id=work_order.id,
        automated=True,
        actor_party=actor.party,
    )
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
