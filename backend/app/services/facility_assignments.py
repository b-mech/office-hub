from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.facility_assignments import FacilityAssignmentCreate
from app.schemas.financing import FacilityCreate
from app.schemas.financing import FacilityOut
from app.schemas.lenders import LenderCreate
from app.services import financing
from app.services import lenders


FACILITY_TYPES = {"SCU", "PRO", "STRIDE", "RSU", "CLIENT", "OTHER"}
OPENING_BALANCE_TYPES = {"SCU", "STRIDE", "RSU"}


class PropertyNotFoundError(ValueError):
    pass


class LenderNotFoundError(ValueError):
    pass


class ActiveFacilityExistsError(ValueError):
    pass


class InvalidFacilityAssignmentError(ValueError):
    pass


async def assign_facility(
    db: AsyncSession,
    property_id: UUID,
    data: FacilityAssignmentCreate,
) -> FacilityOut:
    facility_type = _normalize_facility_type(data.facility_type)
    if facility_type in OPENING_BALANCE_TYPES and data.opening_balance is None:
        raise InvalidFacilityAssignmentError(
            f"Opening balance is required for {facility_type} facilities."
        )

    property_exists = (
        await db.execute(
            text("SELECT 1 FROM core.properties WHERE id = :property_id"),
            {"property_id": property_id},
        )
    ).scalar_one_or_none()
    if property_exists is None:
        raise PropertyNotFoundError("Property not found.")

    active_facility = (
        await db.execute(
            text(
                """
                SELECT id
                FROM core.lender_facilities
                WHERE property_id = :property_id
                  AND status = 'active'
                LIMIT 1
                """
            ),
            {"property_id": property_id},
        )
    ).scalar_one_or_none()
    if active_facility is not None:
        raise ActiveFacilityExistsError(
            "This property already has an active lender facility. "
            "Mark it inactive before assigning another."
        )

    if data.lender_id is not None:
        lender = await lenders.get_lender(db, data.lender_id)
        if lender is None:
            raise LenderNotFoundError("Lender not found.")
    else:
        assert data.new_lender_name is not None
        lender = await lenders.create_lender(
            db,
            LenderCreate(name=data.new_lender_name),
        )

    facility_data = FacilityCreate(
        property_id=property_id,
        lender_type=facility_type,
        lender_name=lender.name,
        total_facility=data.total_facility,
        opening_balance=data.opening_balance,
        rate=data.rate,
        already_drawn=data.already_drawn,
        draw_eligible_override=data.draw_eligible_override,
        requested_draw_amount=data.requested_draw_amount,
        requested_draw_as_of=data.requested_draw_as_of,
        commitment_source=_trim(data.commitment_source),
        commitment_confirmed_at=data.commitment_confirmed_at,
        notes=_trim(data.notes),
    )
    try:
        return await financing.create_facility(db, facility_data)
    except IntegrityError as exc:
        await db.rollback()
        if "uq_core_lender_facilities_active_property" in str(exc):
            raise ActiveFacilityExistsError(
                "This property already has an active lender facility."
            ) from exc
        raise


def _normalize_facility_type(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    if normalized == "PROAUTO":
        normalized = "PRO"
    if normalized not in FACILITY_TYPES:
        raise InvalidFacilityAssignmentError(
            f"Unsupported facility type '{value}'."
        )
    return normalized


def _trim(value: str | None) -> str | None:
    trimmed = (value or "").strip()
    return trimmed or None
