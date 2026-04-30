"""
backend/app/modules/lots/router.py
Surfaces land.agreements + sales.agreements as unified Lot objects
for the Lot Dashboard frontend.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(prefix="/api/v1/lots", tags=["lots"])

DEFAULT_ORG_ID = UUID("ed83acdb-7a3a-4999-b5b0-4d41ee24a99d")


class LotOut(BaseModel):
    id: str
    address: str
    lot_number: Optional[str] = None
    community: str
    buyer_name: Optional[str] = None
    agreement_date: Optional[str] = None
    condition_removal_date: Optional[str] = None
    possession_date: Optional[str] = None
    framing_date: Optional[str] = None
    closing_date: Optional[str] = None
    status: str
    land_agreement_id: Optional[str] = None
    sale_agreement_id: Optional[str] = None


@router.get("", response_model=List[LotOut])
async def list_lots(db: AsyncSession = Depends(get_db)):
    """
    Produce a unified lot list from core.lots with optional sales data.
    """
    query = text("""
        SELECT
            l.id::text AS id,
            COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
            l.lot_number::text,
            COALESCE(d.name, d.municipality, 'Unknown Community') AS community,
            buyers.buyer_name,
            sa.agreement_date::text,
            sa.condition_removal_date::text,
            sa.possession_date::text,
            NULL::text AS framing_date,
            NULL::text AS closing_date,
            CASE
                WHEN sa.possession_date IS NOT NULL AND sa.possession_date <= CURRENT_DATE THEN 'possession'
                WHEN l.status IN ('possession', 'warranty') OR sa.status = 'possession_complete' THEN 'complete'
                ELSE 'active'
            END AS status,
            lt.agreement_id::text AS land_agreement_id,
            sa.id::text AS sale_agreement_id
        FROM core.lots l
        JOIN core.developments d ON d.id = l.development_id
        LEFT JOIN LATERAL (
            SELECT agreement_id
            FROM land.lot_terms
            WHERE lot_id = l.id
            ORDER BY created_at DESC
            LIMIT 1
        ) lt ON true
        LEFT JOIN LATERAL (
            SELECT id, agreement_date, possession_date, condition_removal_date, status
            FROM sales.agreements
            WHERE lot_id = l.id
            ORDER BY created_at DESC
            LIMIT 1
        ) sa ON true
        LEFT JOIN LATERAL (
            SELECT string_agg(c.full_name, ', ' ORDER BY sp.is_primary DESC, c.full_name) AS buyer_name
            FROM sales.parties sp
            JOIN core.contacts c ON c.id = sp.contact_id
            WHERE sp.agreement_id = sa.id
              AND sp.party_role IN ('buyer', 'co_buyer')
        ) buyers ON true
        WHERE d.org_id = :org_id
        ORDER BY l.created_at DESC
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
            agreement_date=row.get("agreement_date"),
            condition_removal_date=row.get("condition_removal_date"),
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
            l.id::text AS id,
            COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
            l.lot_number::text,
            COALESCE(d.name, d.municipality, 'Unknown Community') AS community,
            buyers.buyer_name,
            sa.agreement_date::text,
            sa.condition_removal_date::text,
            sa.possession_date::text,
            NULL::text AS framing_date,
            NULL::text AS closing_date,
            CASE
                WHEN sa.possession_date IS NOT NULL AND sa.possession_date <= CURRENT_DATE THEN 'possession'
                WHEN l.status IN ('possession', 'warranty') OR sa.status = 'possession_complete' THEN 'complete'
                ELSE 'active'
            END AS status,
            lt.agreement_id::text AS land_agreement_id,
            sa.id::text AS sale_agreement_id
        FROM core.lots l
        JOIN core.developments d ON d.id = l.development_id
        LEFT JOIN LATERAL (
            SELECT agreement_id
            FROM land.lot_terms
            WHERE lot_id = l.id
            ORDER BY created_at DESC
            LIMIT 1
        ) lt ON true
        LEFT JOIN LATERAL (
            SELECT id, agreement_date, possession_date, condition_removal_date, status
            FROM sales.agreements
            WHERE lot_id = l.id
            ORDER BY created_at DESC
            LIMIT 1
        ) sa ON true
        LEFT JOIN LATERAL (
            SELECT string_agg(c.full_name, ', ' ORDER BY sp.is_primary DESC, c.full_name) AS buyer_name
            FROM sales.parties sp
            JOIN core.contacts c ON c.id = sp.contact_id
            WHERE sp.agreement_id = sa.id
              AND sp.party_role IN ('buyer', 'co_buyer')
        ) buyers ON true
        WHERE l.id = :lot_id
          AND d.org_id = :org_id
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
        agreement_date=row.get("agreement_date"),
        condition_removal_date=row.get("condition_removal_date"),
        possession_date=row.get("possession_date"),
        framing_date=row.get("framing_date"),
        closing_date=row.get("closing_date"),
        status=row["status"],
        land_agreement_id=row.get("land_agreement_id"),
        sale_agreement_id=row.get("sale_agreement_id"),
    )
