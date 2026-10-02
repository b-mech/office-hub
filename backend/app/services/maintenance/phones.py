from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

import phonenumbers
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintStatus, MaintTicket, MaintVendor, MaintWorkOrder, MaintWorkOrderStatus
from app.models.rentals import RentalLease, RentalLeaseTenant, RentalProperty, RentalTenant, RentalUnit
from app.services.maintenance.errors import InvalidPhoneError


OPEN_TICKET_STATUSES = tuple(
    status for status in MaintStatus if status not in {MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}
)
ACTIVE_WORK_ORDER_STATUSES = tuple(
    status for status in MaintWorkOrderStatus if status not in {MaintWorkOrderStatus.COMPLETED, MaintWorkOrderStatus.CANCELLED, MaintWorkOrderStatus.DECLINED}
)


@dataclass(frozen=True)
class TicketMatch:
    id: UUID
    number: str
    status: MaintStatus


@dataclass(frozen=True)
class WorkOrderMatch:
    id: UUID
    number: str
    status: MaintWorkOrderStatus
    ticket_id: UUID


@dataclass(frozen=True)
class PartyMatch:
    party: str
    party_id: int | UUID
    name: str
    phone_e164: str
    unit_id: int | None = None
    lease_id: int | None = None
    property_id: int | None = None
    unit_label: str | None = None
    property_label: str | None = None
    sms_opted_out: bool = False
    open_tickets: list[TicketMatch] = field(default_factory=list)
    active_work_orders: list[WorkOrderMatch] = field(default_factory=list)


def normalize_phone(value: str, default_region: str = "CA") -> str:
    try:
        parsed = phonenumbers.parse(value.strip(), default_region)
    except (AttributeError, phonenumbers.NumberParseException) as exc:
        raise InvalidPhoneError("Enter a valid Canadian mobile number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneError("Enter a valid Canadian mobile number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


async def resolve_phone(db: AsyncSession, e164: str) -> list[PartyMatch]:
    normalized = normalize_phone(e164)
    matches: list[PartyMatch] = []

    vendors = list(
        (
            await db.scalars(
                select(MaintVendor).where(
                    MaintVendor.phone_e164 == normalized,
                    MaintVendor.is_active.is_(True),
                )
            )
        ).all()
    )
    for vendor in vendors:
        work_orders = list(
            (
                await db.scalars(
                    select(MaintWorkOrder)
                    .where(
                        MaintWorkOrder.vendor_id == vendor.id,
                        MaintWorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES),
                    )
                    .order_by(MaintWorkOrder.created_at.desc())
                )
            ).all()
        )
        matches.append(
            PartyMatch(
                party="vendor",
                party_id=vendor.id,
                name=vendor.name,
                phone_e164=vendor.phone_e164,
                sms_opted_out=vendor.sms_opted_out,
                active_work_orders=[
                    WorkOrderMatch(item.id, item.number, item.status, item.ticket_id) for item in work_orders
                ],
            )
        )

    tenant_rows = (
        await db.execute(
            select(RentalTenant, RentalLease, RentalUnit, RentalProperty)
            .join(RentalLeaseTenant, RentalLeaseTenant.tenant_id == RentalTenant.id)
            .join(RentalLease, RentalLease.id == RentalLeaseTenant.lease_id)
            .join(RentalUnit, RentalUnit.id == RentalLease.unit_id)
            .join(RentalProperty, RentalProperty.id == RentalUnit.property_id)
            .where(
                RentalTenant.phone == normalized,
                RentalLease.status.in_(("active", "month_to_month")),
                or_(RentalLease.lease_end.is_(None), RentalLease.lease_end >= date.today()),
            )
            .order_by(RentalLease.lease_start.desc().nullslast(), RentalLease.id.desc())
        )
    ).all()
    for tenant, lease, unit, rental_property in tenant_rows:
        tickets = list(
            (
                await db.scalars(
                    select(MaintTicket)
                    .where(
                        MaintTicket.reporter_phone_e164 == normalized,
                        MaintTicket.unit_id == unit.id,
                        MaintTicket.status.in_(OPEN_TICKET_STATUSES),
                    )
                    .order_by(MaintTicket.updated_at.desc(), MaintTicket.created_at.desc())
                )
            ).all()
        )
        matches.append(
            PartyMatch(
                party="tenant",
                party_id=tenant.id,
                name=tenant.full_name,
                phone_e164=normalized,
                unit_id=unit.id,
                lease_id=lease.id,
                property_id=rental_property.id,
                unit_label=unit.unit_label,
                property_label=rental_property.street_address,
                sms_opted_out=tenant.sms_opted_out,
                open_tickets=[TicketMatch(item.id, item.number, item.status) for item in tickets],
            )
        )
    return matches
