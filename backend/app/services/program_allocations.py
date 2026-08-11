from __future__ import annotations

from datetime import datetime
from datetime import timezone
from decimal import Decimal
from decimal import ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Lot
from app.models.lenders import Lender
from app.models.program_allocations import AllocationRequest
from app.models.program_allocations import AllocationTier
from app.models.program_allocations import LenderProgram
from app.models.program_allocations import ProgramAllocation
from app.models.sales import SalesAgreement
from app.models.sales import SalesAgreementStatus
from app.schemas.program_allocations import AllocationCapacityOut
from app.schemas.program_allocations import AllocationCreate
from app.schemas.program_allocations import AllocationRequestCreate
from app.schemas.program_allocations import AllocationRequestOut
from app.schemas.program_allocations import AllocationRequestUpdate
from app.schemas.program_allocations import AllocationUpdate
from app.schemas.program_allocations import FitEvaluationOut
from app.schemas.program_allocations import FitEvaluationRequest
from app.schemas.program_allocations import ProgramCapacityOut
from app.schemas.program_allocations import ProgramCreate
from app.schemas.program_allocations import ProgramDetailOut
from app.schemas.program_allocations import ProgramUpdate
from app.schemas.program_allocations import TierCapacityOut
from app.schemas.program_allocations import TierCreate
from app.schemas.program_allocations import TierUpdate


MONEY = Decimal("0.01")
UNCONDITIONAL_STATUSES = {
    SalesAgreementStatus.FIRM,
    SalesAgreementStatus.BUILD_STARTED,
    SalesAgreementStatus.POSSESSION_COMPLETE,
}


class ProgramNotFoundError(ValueError):
    pass


class AllocationNotFoundError(ValueError):
    pass


class AllocationRequestNotFoundError(ValueError):
    pass


class ReleaseNotAllowedError(ValueError):
    pass


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def derive_basis(
    *,
    appraisal_value: Decimal | None,
    estimated_sale_price: Decimal | None,
    explicit_basis_value: Decimal | None,
) -> tuple[Decimal, str]:
    if appraisal_value is not None and estimated_sale_price is not None:
        return _money(min(appraisal_value, estimated_sale_price)), "lesser_of_appraisal_and_estimated_sale_price"
    if appraisal_value is not None:
        return _money(appraisal_value), "appraisal"
    if estimated_sale_price is not None:
        return _money(estimated_sale_price), "estimated_sale_price"
    if explicit_basis_value is not None:
        return _money(explicit_basis_value), "explicit_historical"
    raise ValueError("Provide appraisal_value, estimated_sale_price, or basis_value.")


async def list_programs(db: AsyncSession) -> list[ProgramCapacityOut]:
    ids = list((await db.scalars(select(LenderProgram.id).order_by(LenderProgram.name))).all())
    return [await get_program_capacity(db, program_id) for program_id in ids]


async def get_program_capacity(db: AsyncSession, program_id: UUID) -> ProgramCapacityOut:
    program_row = (
        await db.execute(
            select(LenderProgram, Lender.name)
            .join(Lender, Lender.id == LenderProgram.lender_id)
            .where(LenderProgram.id == program_id)
        )
    ).one_or_none()
    if program_row is None:
        raise ProgramNotFoundError("Lender program not found.")
    program, lender_name = program_row
    allocations = list(
        (await db.scalars(select(ProgramAllocation).where(ProgramAllocation.program_id == program_id).order_by(ProgramAllocation.name))).all()
    )
    allocation_outputs: list[AllocationCapacityOut] = []
    umbrella_consumed = Decimal("0")
    for allocation in allocations:
        requests = list(
            (
                await db.scalars(
                    select(AllocationRequest).where(
                        AllocationRequest.allocation_id == allocation.id,
                        AllocationRequest.status != "released",
                    )
                )
            ).all()
        )
        consumed = _money(sum((request.actual_amount if request.actual_amount is not None else request.suggested_amount for request in requests), Decimal("0")))
        umbrella_consumed += consumed
        tiers = list(
            (await db.scalars(select(AllocationTier).where(AllocationTier.allocation_id == allocation.id).order_by(AllocationTier.face_value))).all()
        )
        occupancy: dict[UUID, int] = {}
        for request in requests:
            if request.nearest_tier_id is not None:
                occupancy[request.nearest_tier_id] = occupancy.get(request.nearest_tier_id, 0) + 1
        tier_outputs = [
            TierCapacityOut(
                id=tier.id,
                face_value=tier.face_value,
                slot_count=tier.slot_count,
                label=tier.label,
                slots_occupied=occupancy.get(tier.id, 0),
                slots_remaining=max(tier.slot_count - occupancy.get(tier.id, 0), 0),
            )
            for tier in tiers
        ]
        allocation_outputs.append(
            AllocationCapacityOut(
                id=allocation.id,
                name=allocation.name,
                allocation_limit=allocation.allocation_limit,
                consumed=consumed,
                remaining=_money(allocation.allocation_limit - consumed),
                max_units=allocation.max_units,
                units_used=len(requests),
                units_remaining=max(allocation.max_units - len(requests), 0),
                max_per_unit=allocation.max_per_unit,
                funding_percentage=allocation.funding_percentage,
                notes=allocation.notes,
                tiers=tier_outputs,
            )
        )
    umbrella_consumed = _money(umbrella_consumed)
    return ProgramCapacityOut(
        id=program.id,
        lender_id=program.lender_id,
        lender_name=lender_name,
        name=program.name,
        umbrella_limit=program.umbrella_limit,
        consumed=umbrella_consumed,
        remaining=_money(program.umbrella_limit - umbrella_consumed),
        notes=program.notes,
        active=program.active,
        allocations=allocation_outputs,
    )


async def evaluate_property_fit(db: AsyncSession, data: FitEvaluationRequest) -> FitEvaluationOut:
    allocation = await db.get(ProgramAllocation, data.allocation_id)
    if allocation is None:
        raise AllocationNotFoundError("Program allocation not found.")
    if await db.get(Lot, data.lot_id) is None:
        raise ValueError("Lot not found.")
    basis_value, basis_source = derive_basis(
        appraisal_value=data.appraisal_value,
        estimated_sale_price=data.estimated_sale_price,
        explicit_basis_value=data.basis_value,
    )
    suggested = _money(basis_value * allocation.funding_percentage)
    capacity = await get_program_capacity(db, allocation.program_id)
    allocation_capacity = next(item for item in capacity.allocations if item.id == allocation.id)
    nearest_tier = min(
        allocation_capacity.tiers,
        key=lambda tier: (abs(tier.face_value - suggested), tier.face_value),
        default=None,
    )
    fits_allocation = suggested <= allocation_capacity.remaining
    fits_umbrella = suggested <= capacity.remaining
    units_available = allocation_capacity.units_remaining > 0
    flags: list[str] = []
    if nearest_tier is not None and suggested > nearest_tier.face_value:
        flags.append("exceeds_nearest_tier")
    if not fits_allocation:
        flags.append("exceeds_remaining_allocation")
    if not units_available:
        flags.append("no_units_remaining")
    if not fits_umbrella:
        flags.append("exceeds_umbrella")
    if allocation.max_per_unit is not None and suggested > allocation.max_per_unit:
        flags.append("exceeds_max_per_unit")
    return FitEvaluationOut(
        lot_id=data.lot_id,
        allocation_id=data.allocation_id,
        appraisal_value=data.appraisal_value,
        estimated_sale_price=data.estimated_sale_price,
        basis_value=basis_value,
        basis_source=basis_source,
        suggested_amount=suggested,
        nearest_tier=nearest_tier,
        fits_remaining_allocation=fits_allocation,
        fits_umbrella=fits_umbrella,
        units_available=units_available,
        flags=flags,
    )


async def get_program_detail(db: AsyncSession, program_id: UUID) -> ProgramDetailOut:
    capacity = await get_program_capacity(db, program_id)
    allocation_ids = [allocation.id for allocation in capacity.allocations]
    if not allocation_ids:
        return ProgramDetailOut(**capacity.model_dump(), requests=[])
    requests = list(
        (
            await db.scalars(
                select(AllocationRequest)
                .where(AllocationRequest.allocation_id.in_(allocation_ids))
                .order_by(AllocationRequest.requested_at.desc().nullslast(), AllocationRequest.id)
            )
        ).all()
    )
    return ProgramDetailOut(
        **capacity.model_dump(),
        requests=[await _request_out(db, request, capacity) for request in requests],
    )


async def create_program(db: AsyncSession, data: ProgramCreate) -> ProgramDetailOut:
    if await db.get(Lender, data.lender_id) is None:
        raise ValueError("Lender not found.")
    program = LenderProgram(**data.model_dump())
    db.add(program)
    await db.commit()
    return await get_program_detail(db, program.id)


async def update_program(db: AsyncSession, program_id: UUID, data: ProgramUpdate) -> ProgramDetailOut:
    program = await db.get(LenderProgram, program_id)
    if program is None:
        raise ProgramNotFoundError("Lender program not found.")
    _apply_updates(program, data.model_dump(exclude_unset=True))
    program.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await get_program_detail(db, program.id)


async def create_allocation(db: AsyncSession, program_id: UUID, data: AllocationCreate) -> ProgramDetailOut:
    if await db.get(LenderProgram, program_id) is None:
        raise ProgramNotFoundError("Lender program not found.")
    db.add(ProgramAllocation(program_id=program_id, **data.model_dump()))
    await db.commit()
    return await get_program_detail(db, program_id)


async def update_allocation(db: AsyncSession, allocation_id: UUID, data: AllocationUpdate) -> ProgramDetailOut:
    allocation = await db.get(ProgramAllocation, allocation_id)
    if allocation is None:
        raise AllocationNotFoundError("Program allocation not found.")
    _apply_updates(allocation, data.model_dump(exclude_unset=True))
    await db.commit()
    return await get_program_detail(db, allocation.program_id)


async def create_tier(db: AsyncSession, allocation_id: UUID, data: TierCreate) -> ProgramDetailOut:
    allocation = await db.get(ProgramAllocation, allocation_id)
    if allocation is None:
        raise AllocationNotFoundError("Program allocation not found.")
    db.add(AllocationTier(allocation_id=allocation_id, **data.model_dump()))
    await db.commit()
    return await get_program_detail(db, allocation.program_id)


async def update_tier(db: AsyncSession, tier_id: UUID, data: TierUpdate) -> ProgramDetailOut:
    tier = await db.get(AllocationTier, tier_id)
    if tier is None:
        raise AllocationNotFoundError("Allocation tier not found.")
    allocation = await db.get(ProgramAllocation, tier.allocation_id)
    assert allocation is not None
    _apply_updates(tier, data.model_dump(exclude_unset=True))
    await db.commit()
    return await get_program_detail(db, allocation.program_id)


async def create_allocation_request(db: AsyncSession, data: AllocationRequestCreate) -> AllocationRequestOut:
    evaluation = await evaluate_property_fit(db, data)
    property_id = data.property_id
    if property_id is None:
        lot = await db.get(Lot, data.lot_id)
        assert lot is not None
        property_id = lot.property_id
    if data.status == "released":
        await _validate_unconditional_sale(db, data.lot_id)
    now = datetime.now(timezone.utc)
    request = AllocationRequest(
        allocation_id=data.allocation_id,
        lot_id=data.lot_id,
        property_id=property_id,
        appraisal_value=data.appraisal_value,
        estimated_sale_price=data.estimated_sale_price,
        basis_value=evaluation.basis_value,
        basis_source=evaluation.basis_source,
        suggested_amount=evaluation.suggested_amount,
        actual_amount=data.actual_amount,
        nearest_tier_id=evaluation.nearest_tier.id if evaluation.nearest_tier else None,
        status=data.status,
        requested_at=now if data.status in {"requested", "approved", "released"} else None,
        approved_at=now if data.status in {"approved", "released"} else None,
        released_at=now if data.status == "released" else None,
        notes=data.notes,
    )
    db.add(request)
    await db.commit()
    allocation = await db.get(ProgramAllocation, request.allocation_id)
    assert allocation is not None
    return await _request_out(db, request, await get_program_capacity(db, allocation.program_id))


async def update_allocation_request(
    db: AsyncSession, request_id: UUID, data: AllocationRequestUpdate
) -> AllocationRequestOut:
    request = await db.get(AllocationRequest, request_id)
    if request is None:
        raise AllocationRequestNotFoundError("Allocation request not found.")
    updates = data.model_dump(exclude_unset=True)
    value_fields = {"appraisal_value", "estimated_sale_price", "basis_value"}
    if value_fields.intersection(updates):
        appraisal = updates.get("appraisal_value", request.appraisal_value)
        estimate = updates.get("estimated_sale_price", request.estimated_sale_price)
        explicit = updates.get("basis_value")
        basis, source = derive_basis(
            appraisal_value=appraisal,
            estimated_sale_price=estimate,
            explicit_basis_value=explicit,
        )
        allocation = await db.get(ProgramAllocation, request.allocation_id)
        assert allocation is not None
        tiers = list((await db.scalars(select(AllocationTier).where(AllocationTier.allocation_id == allocation.id))).all())
        suggested = _money(basis * allocation.funding_percentage)
        nearest = min(tiers, key=lambda tier: (abs(tier.face_value - suggested), tier.face_value), default=None)
        request.appraisal_value = appraisal
        request.estimated_sale_price = estimate
        request.basis_value = basis
        request.basis_source = source
        request.suggested_amount = suggested
        request.nearest_tier_id = nearest.id if nearest else None
        updates = {key: value for key, value in updates.items() if key not in value_fields}
    new_status = updates.pop("status", None)
    if new_status == "released" and request.status != "released":
        await _validate_unconditional_sale(db, request.lot_id)
    _apply_updates(request, updates)
    if new_status is not None:
        _set_status(request, new_status)
    await db.commit()
    allocation = await db.get(ProgramAllocation, request.allocation_id)
    assert allocation is not None
    return await _request_out(db, request, await get_program_capacity(db, allocation.program_id))


async def _validate_unconditional_sale(db: AsyncSession, lot_id: UUID) -> None:
    qualifying = await db.scalar(
        select(func.count(SalesAgreement.id)).where(
            SalesAgreement.lot_id == lot_id,
            SalesAgreement.status.in_(UNCONDITIONAL_STATUSES),
        )
    )
    if not qualifying:
        raise ReleaseNotAllowedError(
            "Allocation can only be released after an unconditional sale "
            "(firm, build_started, or possession_complete)."
        )


def _set_status(request: AllocationRequest, status: str) -> None:
    now = datetime.now(timezone.utc)
    request.status = status
    if status == "draft":
        request.requested_at = None
        request.approved_at = None
        request.released_at = None
    elif status == "requested":
        request.requested_at = request.requested_at or now
        request.approved_at = None
        request.released_at = None
    elif status == "approved":
        request.requested_at = request.requested_at or now
        request.approved_at = request.approved_at or now
        request.released_at = None
    elif status == "released":
        request.requested_at = request.requested_at or now
        request.approved_at = request.approved_at or now
        request.released_at = request.released_at or now


async def _request_out(
    db: AsyncSession, request: AllocationRequest, capacity: ProgramCapacityOut
) -> AllocationRequestOut:
    lot = await db.get(Lot, request.lot_id)
    tier = await db.get(AllocationTier, request.nearest_tier_id) if request.nearest_tier_id else None
    allocation = next(item for item in capacity.allocations if item.id == request.allocation_id)
    flags: list[str] = []
    if tier is not None and request.suggested_amount > tier.face_value:
        flags.append("exceeds_nearest_tier")
    if allocation.max_per_unit is not None and request.suggested_amount > allocation.max_per_unit:
        flags.append("exceeds_max_per_unit")
    if allocation.consumed > allocation.allocation_limit:
        flags.append("exceeds_remaining_allocation")
    if allocation.units_used > allocation.max_units:
        flags.append("no_units_remaining")
    if capacity.consumed > capacity.umbrella_limit:
        flags.append("exceeds_umbrella")
    return AllocationRequestOut(
        id=request.id,
        allocation_id=request.allocation_id,
        lot_id=request.lot_id,
        property_id=request.property_id,
        address=(lot.civic_address or lot.legal_description_normalized) if lot else "Unknown lot",
        appraisal_value=request.appraisal_value,
        estimated_sale_price=request.estimated_sale_price,
        basis_value=request.basis_value,
        basis_source=request.basis_source,
        suggested_amount=request.suggested_amount,
        actual_amount=request.actual_amount,
        nearest_tier_id=request.nearest_tier_id,
        nearest_tier_face_value=tier.face_value if tier else None,
        status=request.status,
        requested_at=request.requested_at,
        approved_at=request.approved_at,
        released_at=request.released_at,
        notes=request.notes,
        flags=flags,
    )


def _apply_updates(record: Any, updates: dict[str, Any]) -> None:
    for field, value in updates.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(record, field, value)
