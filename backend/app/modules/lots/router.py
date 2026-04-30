"""
backend/app/modules/lots/router.py
Surfaces land.agreements + sales.agreements as unified Lot objects
for the Lot Dashboard frontend.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter(prefix="/api/v1/lots", tags=["lots"])

DEFAULT_ORG_ID = UUID("ed83acdb-7a3a-4999-b5b0-4d41ee24a99d")


class LotOut(BaseModel):
    id: str
    address: str
    lot_number: Optional[str] = None
    community: str
    buyer_name: Optional[str] = None
    possession_date: Optional[str] = None
    framing_date: Optional[str] = None
    closing_date: Optional[str] = None
    status: str
    land_agreement_id: Optional[str] = None
    sale_agreement_id: Optional[str] = None


@router.get("", response_model=List[LotOut])
async def list_lots(db: AsyncSession = Depends(get_db)):
    """
    Join land.agreements and sales.agreements to produce a unified lot list.

    NOTE: This query makes reasonable assumptions about the column names in
    land.agreements and sales.agreements based on the OTP ingestion pipeline.
    Adjust column names if they differ in your actual schema.
    """
    query = text("""
        SELECT
            la.id::text                                         AS id,
            COALESCE(la.property_address, la.address, 'Unknown Address') AS address,
            la.lot_number::text,
            COALESCE(la.community, la.development_name, 'Unknown Community') AS community,
            CONCAT_WS(' ', sa.buyer_first_name, sa.buyer_last_name) AS buyer_name,
            sa.possession_date::text,
            sa.framing_date::text,
            sa.closing_date::text,
            CASE
                WHEN sa.possession_date IS NOT NULL AND sa.possession_date <= CURRENT_DATE THEN 'possession'
                WHEN la.status = 'complete' OR sa.status = 'complete'                     THEN 'complete'
                ELSE 'active'
            END AS status,
            la.id::text  AS land_agreement_id,
            sa.id::text  AS sale_agreement_id
        FROM land.agreements la
        LEFT JOIN sales.agreements sa ON sa.land_agreement_id = la.id
        WHERE la.org_id = :org_id
        ORDER BY la.created_at DESC
    """)

    result = await db.execute(query, {"org_id": str(DEFAULT_ORG_ID)})
    rows = result.mappings().all()

    return [
        LotOut(
            id=row["id"],
            address=row["address"],
            lot_number=row.get("lot_number"),
            community=row["community"],
            buyer_name=row.get("buyer_name") or None,
            possession_date=row.get("possession_date"),
            framing_date=row.get("framing_date"),
            closing_date=row.get("closing_date"),
            status=row["status"],
            land_agreement_id=row.get("land_agreement_id"),
            sale_agreement_id=row.get("sale_agreement_id"),
        )
        for row in rows
    ]


@router.get("/{lot_id}", response_model=LotOut)
async def get_lot(lot_id: str, db: AsyncSession = Depends(get_db)):
    query = text("""
        SELECT
            la.id::text                                         AS id,
            COALESCE(la.property_address, la.address, 'Unknown Address') AS address,
            la.lot_number::text,
            COALESCE(la.community, la.development_name, 'Unknown Community') AS community,
            CONCAT_WS(' ', sa.buyer_first_name, sa.buyer_last_name) AS buyer_name,
            sa.possession_date::text,
            sa.framing_date::text,
            sa.closing_date::text,
            CASE
                WHEN sa.possession_date IS NOT NULL AND sa.possession_date <= CURRENT_DATE THEN 'possession'
                WHEN la.status = 'complete' OR sa.status = 'complete'                     THEN 'complete'
                ELSE 'active'
            END AS status,
            la.id::text  AS land_agreement_id,
            sa.id::text  AS sale_agreement_id
        FROM land.agreements la
        LEFT JOIN sales.agreements sa ON sa.land_agreement_id = la.id
        WHERE la.id = :lot_id
          AND la.org_id = :org_id
    """)

    result = await db.execute(query, {"lot_id": lot_id, "org_id": str(DEFAULT_ORG_ID)})
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Lot not found")

    return LotOut(
        id=row["id"],
        address=row["address"],
        lot_number=row.get("lot_number"),
        community=row["community"],
        buyer_name=row.get("buyer_name") or None,
        possession_date=row.get("possession_date"),
        framing_date=row.get("framing_date"),
        closing_date=row.get("closing_date"),
        status=row["status"],
        land_agreement_id=row.get("land_agreement_id"),
        sale_agreement_id=row.get("sale_agreement_id"),
    )
