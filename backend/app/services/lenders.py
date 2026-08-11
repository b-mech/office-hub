from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.lenders import LenderCreate
from app.schemas.lenders import LenderDetail
from app.schemas.lenders import LenderFacilityLink
from app.schemas.lenders import LenderListItem
from app.schemas.lenders import LenderUpdate


class DuplicateLenderNameError(ValueError):
    pass


class LinkedFacilitiesError(ValueError):
    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            f"This lender cannot be deleted because {count} "
            f"linked facilit{'y' if count == 1 else 'ies'} exist."
        )


class LinkedProgramsError(ValueError):
    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            f"This lender cannot be deleted because {count} "
            f"linked program{' exists' if count == 1 else 's exist'}."
        )


async def list_lenders(db: AsyncSession) -> list[LenderListItem]:
    rows = (
        await db.execute(
            text(
                """
                SELECT lender.*,
                       count(facility.id) FILTER (WHERE facility.status = 'active')::int
                           AS active_facility_count
                FROM core.lenders AS lender
                LEFT JOIN core.lender_facilities AS facility
                  ON facility.lender_id = lender.id
                GROUP BY lender.id
                ORDER BY lower(lender.name), lender.id
                """
            )
        )
    ).mappings().all()
    return [LenderListItem(**row) for row in rows]


async def get_lender(db: AsyncSession, lender_id: UUID) -> LenderDetail | None:
    row = (
        await db.execute(
            text(
                """
                SELECT lender.*,
                       count(facility.id) FILTER (WHERE facility.status = 'active')::int
                           AS active_facility_count
                FROM core.lenders AS lender
                LEFT JOIN core.lender_facilities AS facility
                  ON facility.lender_id = lender.id
                WHERE lender.id = :lender_id
                GROUP BY lender.id
                """
            ),
            {"lender_id": lender_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return None

    facility_rows = (
        await db.execute(
            text(
                """
                SELECT facility.id AS facility_id,
                       facility.property_id,
                       property.address AS property_address,
                       facility.lender_type,
                       facility.status,
                       facility.total_facility,
                       facility.opening_balance
                FROM core.lender_facilities AS facility
                LEFT JOIN core.properties AS property
                  ON property.id = facility.property_id
                WHERE facility.lender_id = :lender_id
                ORDER BY lower(coalesce(property.address, facility.property_name, '')),
                         facility.created_at,
                         facility.id
                """
            ),
            {"lender_id": lender_id},
        )
    ).mappings().all()
    facilities = [
        LenderFacilityLink(
            **{
                **facility,
                "total_facility": _decimal_string(facility["total_facility"]),
                "opening_balance": _decimal_string(facility["opening_balance"]),
            }
        )
        for facility in facility_rows
    ]
    return LenderDetail(**row, facilities=facilities)


async def create_lender(db: AsyncSession, data: LenderCreate) -> LenderDetail:
    values = _clean_values(data.model_dump())
    try:
        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO core.lenders (
                        name, contact_name, contact_email, contact_phone, notes
                    )
                    VALUES (
                        :name, :contact_name, :contact_email, :contact_phone, :notes
                    )
                    RETURNING id
                    """
                ),
                values,
            )
        ).mappings().one()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateLenderNameError("A lender with this name already exists.") from exc
    created = await get_lender(db, row["id"])
    assert created is not None
    return created


async def update_lender(
    db: AsyncSession,
    lender_id: UUID,
    data: LenderUpdate,
) -> LenderDetail | None:
    updates = _clean_values(data.model_dump(exclude_unset=True))
    if not updates:
        return await get_lender(db, lender_id)
    assignments = ", ".join(f"{field} = :{field}" for field in updates)
    try:
        lender_exists = (
            await db.execute(
                text(
                    f"""
                    UPDATE core.lenders
                    SET {assignments}, updated_at = now()
                    WHERE id = :lender_id
                    RETURNING id
                    """
                ),
                {**updates, "lender_id": lender_id},
            )
        ).scalar_one_or_none()
        if lender_exists is None:
            await db.rollback()
            return None
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateLenderNameError("A lender with this name already exists.") from exc
    return await get_lender(db, lender_id)


async def delete_lender(db: AsyncSession, lender_id: UUID) -> bool:
    linked_count = (
        await db.execute(
            text(
                """
                SELECT count(*)
                FROM core.lender_facilities
                WHERE lender_id = :lender_id
                """
            ),
            {"lender_id": lender_id},
        )
    ).scalar_one()
    if linked_count:
        raise LinkedFacilitiesError(linked_count)
    program_count = (
        await db.execute(
            text("SELECT count(*) FROM financing.lender_programs WHERE lender_id = :lender_id"),
            {"lender_id": lender_id},
        )
    ).scalar_one()
    if program_count:
        raise LinkedProgramsError(program_count)
    deleted = (
        await db.execute(
            text("DELETE FROM core.lenders WHERE id = :lender_id RETURNING id"),
            {"lender_id": lender_id},
        )
    ).scalar_one_or_none()
    await db.commit()
    return deleted is not None


def _clean_values(values: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field, value in values.items():
        if isinstance(value, str):
            value = value.strip() or None
        cleaned[field] = value
    if "name" in cleaned and cleaned["name"] is None:
        raise ValueError("Lender name is required.")
    return cleaned


def _decimal_string(value: Any) -> str | None:
    return format(value, "f") if value is not None else None
