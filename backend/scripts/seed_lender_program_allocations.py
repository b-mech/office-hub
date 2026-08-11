from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costbook.models import PurchaseOrder  # noqa: F401 - registers ORM relationship target
from app.core.addresses import normalize_address
from app.core.database import AsyncSessionLocal
from app.models.core import Lot
from app.models.lenders import Lender
from app.models.financing import Property
from app.models.program_allocations import AllocationRequest
from app.models.program_allocations import AllocationTier
from app.models.program_allocations import LenderProgram
from app.models.program_allocations import ProgramAllocation


@dataclass(frozen=True)
class SeedRequest:
    address: str
    allocation: str
    basis: Decimal
    suggested: Decimal
    actual: Decimal | None
    status: str
    basis_source: str


REQUESTS = (
    SeedRequest("22 Oak Meadow Drive", "Lot/Land", Decimal("107900"), Decimal("86320"), Decimal("84000"), "approved", "lot_purchase_price"),
    SeedRequest("24 Oak Meadow Drive", "Lot/Land", Decimal("108900"), Decimal("87120"), Decimal("84000"), "approved", "lot_purchase_price"),
    SeedRequest("27 Morning Glory Way", "Spec", Decimal("562374"), Decimal("449899"), None, "requested", "appraisal"),
    SeedRequest("245 Blossom Way", "Spec", Decimal("576694"), Decimal("461355"), None, "requested", "appraisal"),
    SeedRequest("256 Middlechurch Gate", "Spec", Decimal("576694"), Decimal("461355"), None, "requested", "appraisal"),
    SeedRequest("187 Middlechurch Gate", "Spec", Decimal("710997"), Decimal("568798"), None, "requested", "appraisal"),
    SeedRequest("87 Grove Crescent", "Spec", Decimal("1100000"), Decimal("880000"), None, "requested", "appraisal"),
    SeedRequest("14 Grove Crescent", "Spec", Decimal("1300000"), Decimal("1040000"), None, "requested", "appraisal"),
)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        lender = await db.scalar(select(Lender).where(Lender.name == "Steinbach Credit Union"))
        if lender is None:
            raise RuntimeError("Steinbach Credit Union lender does not exist; seed aborted.")

        program = await db.scalar(
            select(LenderProgram).where(
                LenderProgram.lender_id == lender.id,
                LenderProgram.name == "SCU Umbrella",
            )
        )
        if program is None:
            program = LenderProgram(
                lender_id=lender.id,
                name="SCU Umbrella",
                umbrella_limit=Decimal("19000000"),
                notes="Umbrella program; 1.6x land-titles cushion is reference-only.",
                active=True,
            )
            db.add(program)
            await db.flush()

        spec = await _allocation(
            db,
            program.id,
            name="Spec",
            allocation_limit=Decimal("5020000"),
            max_units=10,
            max_per_unit=None,
            funding_percentage=Decimal("0.80"),
        )
        lot_land = await _allocation(
            db,
            program.id,
            name="Lot/Land",
            allocation_limit=Decimal("832000"),
            max_units=4,
            max_per_unit=Decimal("208000"),
            funding_percentage=Decimal("0.80"),
        )
        await _tier(db, spec.id, Decimal("500000"), 4, None)
        await _tier(db, spec.id, Decimal("600000"), 4, None)
        await _tier(db, spec.id, Decimal("310000"), 2, "Duplex")

        lots = list((await db.scalars(select(Lot))).all())
        properties = list((await db.scalars(select(Property))).all())
        by_key: dict[str, list[Lot]] = {}
        properties_by_key: dict[str, list[Property]] = {}
        for lot in lots:
            for candidate in (lot.civic_address, lot.legal_description_raw):
                if candidate:
                    by_key.setdefault(normalize_address(candidate).canonical_key, []).append(lot)
        for property_record in properties:
            key = property_record.canonical_address_key or normalize_address(property_record.address).canonical_key
            properties_by_key.setdefault(key, []).append(property_record)

        allocations = {"Spec": spec, "Lot/Land": lot_land}
        seeded = 0
        skipped: list[str] = []
        for item in REQUESTS:
            matches = list({lot.id: lot for lot in by_key.get(normalize_address(item.address).canonical_key, [])}.values())
            if len(matches) != 1:
                key = normalize_address(item.address).canonical_key
                property_matches = properties_by_key.get(key, [])
                if not matches and len(property_matches) == 1:
                    reason = f"property {property_matches[0].id} exists but has no core.lots record"
                elif not matches:
                    reason = "unmatched"
                else:
                    reason = f"ambiguous ({len(matches)} lot matches)"
                skipped.append(f"{item.address}: {reason}")
                continue
            lot = matches[0]
            allocation = allocations[item.allocation]
            existing = await db.scalar(
                select(AllocationRequest).where(
                    AllocationRequest.allocation_id == allocation.id,
                    AllocationRequest.lot_id == lot.id,
                )
            )
            if existing is not None:
                skipped.append(f"{item.address}: already seeded")
                continue
            tiers = list((await db.scalars(select(AllocationTier).where(AllocationTier.allocation_id == allocation.id))).all())
            nearest = min(tiers, key=lambda tier: (abs(tier.face_value - item.suggested), tier.face_value), default=None)
            db.add(
                AllocationRequest(
                    allocation_id=allocation.id,
                    lot_id=lot.id,
                    property_id=lot.property_id,
                    appraisal_value=item.basis if item.basis_source == "appraisal" else None,
                    basis_value=item.basis,
                    basis_source=item.basis_source,
                    suggested_amount=item.suggested,
                    actual_amount=item.actual,
                    nearest_tier_id=nearest.id if nearest else None,
                    status=item.status,
                    requested_at=lot.updated_at,
                    approved_at=lot.updated_at if item.status == "approved" else None,
                    notes="Initial SCU allocation seed.",
                )
            )
            seeded += 1
        await db.commit()
        print(f"Program: {program.name} ({program.id})")
        print(f"Seeded requests: {seeded}")
        if skipped:
            print("Skipped:")
            for message in skipped:
                print(f"- {message}")


async def _allocation(
    db: AsyncSession,
    program_id: UUID,
    *,
    name: str,
    allocation_limit: Decimal,
    max_units: int,
    max_per_unit: Decimal | None,
    funding_percentage: Decimal,
) -> ProgramAllocation:
    allocation = await db.scalar(
        select(ProgramAllocation).where(
            ProgramAllocation.program_id == program_id,
            ProgramAllocation.name == name,
        )
    )
    if allocation is None:
        allocation = ProgramAllocation(
            program_id=program_id,
            name=name,
            allocation_limit=allocation_limit,
            max_units=max_units,
            max_per_unit=max_per_unit,
            funding_percentage=funding_percentage,
        )
        db.add(allocation)
        await db.flush()
    return allocation


async def _tier(
    db: AsyncSession, allocation_id: UUID, face_value: Decimal, slot_count: int, label: str | None
) -> AllocationTier:
    tier = await db.scalar(
        select(AllocationTier).where(
            AllocationTier.allocation_id == allocation_id,
            AllocationTier.face_value == face_value,
            AllocationTier.label == label,
        )
    )
    if tier is None:
        tier = AllocationTier(
            allocation_id=allocation_id,
            face_value=face_value,
            slot_count=slot_count,
            label=label,
        )
        db.add(tier)
        await db.flush()
    return tier


if __name__ == "__main__":
    asyncio.run(main())
