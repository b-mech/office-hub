"""Read-only rental unit roster: every unit with its property, occupancy and current lease."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintStatus, MaintTicket
from app.models.rentals import LeaseAgreement, RentalLease, RentalLeaseTenant, RentalProperty, RentalTenant, RentalUnit

CURRENT_LEASE_STATUSES = ("active", "month_to_month")
OPEN_TICKET_STATUSES = (
    MaintStatus.NEW, MaintStatus.TRIAGED, MaintStatus.ASSIGNED, MaintStatus.SCHEDULED,
    MaintStatus.IN_PROGRESS, MaintStatus.AWAITING_PARTS, MaintStatus.AWAITING_TENANT,
)
ENDING_SOON_DAYS = 60


def _sort_key(lease: RentalLease) -> tuple[date, int]:
    return (lease.lease_start or date.min, lease.id)


def pick_leases(leases: Iterable[RentalLease]) -> tuple[dict[int, RentalLease], dict[int, RentalLease]]:
    """Return (current lease per unit, most recent lease of any status per unit)."""
    current: dict[int, RentalLease] = {}
    latest: dict[int, RentalLease] = {}
    for lease in leases:
        if lease.unit_id not in latest or _sort_key(lease) > _sort_key(latest[lease.unit_id]):
            latest[lease.unit_id] = lease
        if lease.status in CURRENT_LEASE_STATUSES and (
            lease.unit_id not in current or _sort_key(lease) > _sort_key(current[lease.unit_id])
        ):
            current[lease.unit_id] = lease
    return current, latest


def lease_flag(lease: RentalLease | None, today: date) -> str | None:
    if lease is None:
        return None
    if lease.status == "month_to_month":
        return "month_to_month"
    if lease.lease_end is None:
        return None
    days = (lease.lease_end - today).days
    if days < 0:
        return "past_end"
    if days <= ENDING_SOON_DAYS:
        return "ending_soon"
    return None


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))


def build_roster(
    rows: Sequence[tuple[RentalUnit, RentalProperty]],
    leases: Iterable[RentalLease],
    tenants_by_lease: Mapping[int, Sequence[tuple[str, bool]]],
    open_tickets: Mapping[int, int],
    agreement_status: Mapping[int, str],
    *,
    today: date,
) -> list[dict[str, object]]:
    current, latest = pick_leases(leases)
    result: list[dict[str, object]] = []
    for unit, prop in rows:
        lease = current.get(unit.id)
        last = latest.get(unit.id)
        tenants = sorted(tenants_by_lease.get(lease.id, ()) if lease else (), key=lambda t: (not t[1], t[0].lower()))
        net = None
        if lease is not None:
            net = Decimal(lease.rent) - Decimal(lease.rent_discount_amount or 0)
        result.append({
            "unit_id": unit.id,
            "unit_label": unit.unit_label or "Main building",
            "is_basement": unit.is_basement,
            "unit_status": unit.status,
            "property_id": prop.id,
            "street_address": prop.street_address,
            "group_name": prop.group_name,
            "city": prop.city,
            "occupancy": "occupied" if lease else "vacant",
            "lease": None if lease is None else {
                "id": lease.id,
                "status": lease.status,
                "rent": _money(lease.rent),
                "rent_discount": _money(lease.rent_discount_amount),
                "net_rent": _money(net),
                "deposit": _money(lease.deposit),
                "lease_start": lease.lease_start,
                "lease_end": lease.lease_end,
                "days_to_end": (lease.lease_end - today).days if lease.lease_end else None,
                "flag": lease_flag(lease, today),
            },
            "tenants": [name for name, _primary in tenants],
            "primary_tenant": tenants[0][0] if tenants else None,
            "last_lease_end": None if lease or last is None else last.lease_end,
            "last_lease_status": None if lease or last is None else last.status,
            "lease_agreement_status": agreement_status.get(unit.id),
            "open_maintenance_tickets": int(open_tickets.get(unit.id, 0)),
        })
    return result


async def unit_roster(db: AsyncSession, *, property_id: int | None = None, today: date | None = None) -> list[dict[str, object]]:
    statement = select(RentalUnit, RentalProperty).join(RentalProperty, RentalProperty.id == RentalUnit.property_id)
    if property_id is not None:
        statement = statement.where(RentalProperty.id == property_id)
    rows = [(unit, prop) for unit, prop in (await db.execute(
        statement.order_by(RentalProperty.street_address, RentalUnit.unit_label.nulls_first(), RentalUnit.id)
    )).all()]
    unit_ids = [unit.id for unit, _ in rows]
    if not unit_ids:
        return []
    leases = list((await db.scalars(select(RentalLease).where(RentalLease.unit_id.in_(unit_ids)))).all())
    current, _ = pick_leases(leases)
    tenants_by_lease: dict[int, list[tuple[str, bool]]] = {}
    current_ids = [lease.id for lease in current.values()]
    if current_ids:
        for lease_id, name, primary in (await db.execute(
            select(RentalLeaseTenant.lease_id, RentalTenant.full_name, RentalLeaseTenant.is_primary_contact)
            .join(RentalTenant, RentalTenant.id == RentalLeaseTenant.tenant_id)
            .where(RentalLeaseTenant.lease_id.in_(current_ids))
        )).all():
            tenants_by_lease.setdefault(lease_id, []).append((name, bool(primary)))
    open_tickets = {unit_id: count for unit_id, count in (await db.execute(
        select(MaintTicket.unit_id, func.count())
        .where(MaintTicket.unit_id.in_(unit_ids), MaintTicket.status.in_(OPEN_TICKET_STATUSES))
        .group_by(MaintTicket.unit_id)
    )).all()}
    agreement_status: dict[int, str] = {}
    for unit_id, status in (await db.execute(
        select(LeaseAgreement.unit_id, LeaseAgreement.status)
        .where(LeaseAgreement.unit_id.in_(unit_ids))
        .order_by(LeaseAgreement.unit_id, LeaseAgreement.created_at.desc())
    )).all():
        agreement_status.setdefault(unit_id, status)
    return build_roster(rows, leases, tenants_by_lease, open_tickets, agreement_status, today=today or date.today())
