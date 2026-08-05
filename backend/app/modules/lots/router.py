"""
backend/app/modules/lots/router.py
Surfaces land.agreements + sales.agreements as unified Lot objects
for the Lot Dashboard frontend.

OTP timeline data audit:
- core.lots stores display/address fields and status, but no OTP date or deposit amount fields.
- sales.agreements stores agreement_date, condition_removal_date, possession_date, status, and sale_price.
- sales.deposit_schedule stores deposit_number, amount, due_date, held_by, paid_at, and paid_amount.
- land.agreements stores agreement_date and total_purchase_price.
- land.lot_terms stores purchase_price, balance_due_date, possession_date, and lot-specific notes.
- land.deposit_schedule stores deposit_number, amount, due_date, paid_at, and paid_amount.
- land.security_deposit stores rate_per_lot, maximum_amount, calculated_amount, paid_at, and paid_amount,
  but no fixed due date; due_trigger is rule text only.
- land.milestones stores expected_date and completed_at for named milestones.
TODO: sale firm date is inferred from condition_removal_date because sales.agreements has no separate firm_sale_date.
TODO: deposit #3 is supported from deposit_schedule rows if present, but the current promotion flow only creates
      land deposits #1/#2 and sale deposits found in the payment schedule.
TODO: construction dates such as framing_date and closing_date are currently exposed as null placeholders only.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/lots", tags=["lots"])
projects_router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class LotOut(BaseModel):
    id: str
    property_id: Optional[UUID] = None
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
    lender_type: Optional[str] = None
    lender_name: Optional[str] = None
    draw_available: Optional[Decimal] = None
    construction_stage: Optional[str] = None
    construction_stage_updated_at: Optional[datetime] = None


class TimelineEvent(BaseModel):
    id: str
    lot_id: UUID
    address: str
    client_name: str
    event_type: str
    event_label: str
    event_date: date
    amount: Decimal | None = None
    days_until: int
    urgency: str


async def _list_lots(db: AsyncSession, sale_filter: str) -> list[LotOut]:
    """
    Produce a unified lot list from core.lots with optional sales data.
    """
    if sale_filter not in {"without_sale", "with_sale"}:
        raise ValueError(f"Unsupported sale filter: {sale_filter}")

    sale_predicate = "sa.id IS NULL" if sale_filter == "without_sale" else "sa.id IS NOT NULL"
    query = text(f"""
        WITH lot_rows AS (
            SELECT
                l.*,
                btrim(regexp_replace(
                    upper(COALESCE(l.civic_address, l.legal_description_normalized, '')),
                    '[^A-Z0-9]+',
                    ' ',
                    'g'
                )) AS address_normalized
            FROM core.lots l
        )
        SELECT
            l.id::text AS id,
            l.property_id,
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
            sa.id::text AS sale_agreement_id,
            financing.lender_type,
            financing.lender_name,
            financing.draw_available,
            financing.construction_stage,
            financing.construction_stage_updated_at
        FROM lot_rows l
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
            SELECT string_agg(
                COALESCE(c.full_name, c.company_name),
                ', '
                ORDER BY sp.is_primary DESC, COALESCE(c.full_name, c.company_name)
            ) AS buyer_name
            FROM sales.parties sp
            JOIN core.contacts c ON c.id = sp.contact_id
            WHERE sp.agreement_id = sa.id
              AND sp.party_role IN ('buyer', 'co_buyer')
              AND COALESCE(c.full_name, c.company_name) IS NOT NULL
        ) buyers ON true
        LEFT JOIN LATERAL (
            SELECT
                matched.lender_type,
                matched.lender_name,
                CASE
                    WHEN matched.lender_type = 'CLIENT' THEN NULL::numeric
                    WHEN matched.stage_clean IS NULL OR matched.stage_clean IN ('', 'NA') THEN 0::numeric
                    WHEN matched.lender_type = 'PRO' AND matched.total_facility IS NOT NULL THEN
                        GREATEST(
                            0::numeric,
                            CASE
                                WHEN matched.stage_clean = 'FOUNDATION' THEN 125000::numeric
                                WHEN matched.stage_clean = 'LOCKUP' THEN matched.total_facility * 0.55::numeric
                                WHEN matched.stage_clean = 'DRYWALL' THEN matched.total_facility * 0.775::numeric
                                WHEN matched.stage_clean IN ('CABINETRY', 'COMPLETED') THEN matched.total_facility
                                ELSE 0::numeric
                            END - COALESCE(matched.already_drawn, 0::numeric)
                        )::numeric(15, 2)
                    WHEN matched.lender_type IN ('SCU', 'STRIDE', 'RSU') AND matched.opening_balance IS NOT NULL THEN
                        GREATEST(
                            0::numeric,
                            CASE
                                WHEN matched.stage_clean = 'FOUNDATION' THEN matched.opening_balance * 0.20::numeric
                                WHEN matched.stage_clean = 'LOCKUP' THEN matched.opening_balance * 0.38::numeric
                                WHEN matched.stage_clean = 'DRYWALL' THEN matched.opening_balance * 0.62::numeric
                                WHEN matched.stage_clean = 'CABINETRY' THEN matched.opening_balance * 0.82::numeric
                                WHEN matched.stage_clean = 'COMPLETED' THEN matched.opening_balance
                                ELSE 0::numeric
                            END - COALESCE(matched.already_drawn, 0::numeric)
                        )::numeric(15, 2)
                    ELSE NULL::numeric
                END AS draw_available,
                matched.stage_clean AS construction_stage,
                matched.last_synced_at AS construction_stage_updated_at
            FROM (
                SELECT
                    COALESCE(lf.lender_type, lf.lender, css.lender_type) AS lender_type,
                    lf.lender_name,
                    lf.total_facility,
                    lf.opening_balance,
                    lf.already_drawn,
                    NULLIF(upper(btrim(css.stage_clean)), '') AS stage_clean,
                    css.last_synced_at,
                    CASE WHEN lf.lot_id = l.id THEN 0 ELSE 1 END AS match_priority
                FROM core.lender_facilities lf
                LEFT JOIN core.properties p ON p.id = lf.property_id
                LEFT JOIN documents.construction_stage_sync css ON css.property_id = p.id
                WHERE lf.lot_id = l.id
                   OR btrim(regexp_replace(upper(COALESCE(p.address, lf.property_name, '')), '[^A-Z0-9]+', ' ', 'g')) = l.address_normalized

                UNION ALL

                SELECT
                    css.lender_type,
                    NULL::varchar AS lender_name,
                    NULL::numeric AS total_facility,
                    NULL::numeric AS opening_balance,
                    NULL::numeric AS already_drawn,
                    NULLIF(upper(btrim(css.stage_clean)), '') AS stage_clean,
                    css.last_synced_at,
                    2 AS match_priority
                FROM documents.construction_stage_sync css
                LEFT JOIN core.properties p ON p.id = css.property_id
                WHERE btrim(regexp_replace(upper(COALESCE(p.address, css.address_raw, '')), '[^A-Z0-9]+', ' ', 'g')) = l.address_normalized
            ) matched
            WHERE matched.lender_type IS NOT NULL
               OR matched.stage_clean IS NOT NULL
            ORDER BY matched.match_priority ASC, matched.last_synced_at DESC NULLS LAST
            LIMIT 1
        ) financing ON true
        WHERE d.org_id = :org_id
          AND {sale_predicate}
        ORDER BY l.created_at DESC
    """)

    result = await db.execute(query, {"org_id": str(settings.default_org_id)})
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
            lender_type=row.get("lender_type"),
            lender_name=row.get("lender_name"),
            draw_available=row.get("draw_available"),
            construction_stage=row.get("construction_stage"),
            construction_stage_updated_at=row.get("construction_stage_updated_at"),
        )
        for row in rows
    ]


@router.get("", response_model=List[LotOut])
async def list_lots(db: AsyncSession = Depends(get_db)):
    return await _list_lots(db, "without_sale")


@router.get("/timeline", response_model=list[TimelineEvent], dependencies=[Depends(verify_api_key)])
async def list_otp_timeline(db: AsyncSession = Depends(get_db)) -> list[TimelineEvent]:
    query = text("""
        WITH base_lots AS (
            SELECT
                l.id AS lot_id,
                COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
                COALESCE(buyers.buyer_name, '') AS client_name,
                latest_land_terms.id AS land_lot_terms_id,
                latest_land_terms.balance_due_date AS land_balance_due_date,
                latest_land_terms.possession_date AS land_possession_date,
                latest_sale.id AS sale_agreement_id,
                latest_sale.agreement_date AS sale_agreement_date,
                latest_sale.condition_removal_date AS sale_condition_removal_date,
                latest_sale.possession_date AS sale_possession_date
            FROM core.lots l
            JOIN core.developments d ON d.id = l.development_id
            LEFT JOIN LATERAL (
                SELECT id, agreement_id, balance_due_date, possession_date
                FROM land.lot_terms
                WHERE lot_id = l.id
                ORDER BY created_at DESC
                LIMIT 1
            ) latest_land_terms ON true
            LEFT JOIN LATERAL (
                SELECT id, agreement_date, condition_removal_date, possession_date, status
                FROM sales.agreements
                WHERE lot_id = l.id
                ORDER BY created_at DESC
                LIMIT 1
            ) latest_sale ON true
            LEFT JOIN LATERAL (
                SELECT string_agg(
                    COALESCE(c.full_name, c.company_name),
                    ', '
                    ORDER BY sp.is_primary DESC, COALESCE(c.full_name, c.company_name)
                ) AS buyer_name
                FROM sales.parties sp
                JOIN core.contacts c ON c.id = sp.contact_id
                WHERE sp.agreement_id = latest_sale.id
                  AND sp.party_role IN ('buyer', 'co_buyer')
                  AND COALESCE(c.full_name, c.company_name) IS NOT NULL
            ) buyers ON true
            WHERE d.org_id = :org_id
        ),
        sale_date_events AS (
            SELECT
                lot_id,
                address,
                client_name,
                'conditional_removal'::text AS event_type,
                'Conditional Removal'::text AS event_label,
                sale_condition_removal_date AS event_date,
                NULL::numeric AS amount
            FROM base_lots
            WHERE sale_condition_removal_date IS NOT NULL

            UNION ALL

            SELECT
                lot_id,
                address,
                client_name,
                'firm_sale'::text AS event_type,
                'Firm Sale'::text AS event_label,
                sale_condition_removal_date AS event_date,
                NULL::numeric AS amount
            FROM base_lots
            WHERE sale_condition_removal_date IS NOT NULL

            UNION ALL

            SELECT
                lot_id,
                address,
                client_name,
                'possession'::text AS event_type,
                'Possession'::text AS event_label,
                sale_possession_date AS event_date,
                NULL::numeric AS amount
            FROM base_lots
            WHERE sale_possession_date IS NOT NULL
        ),
        land_date_events AS (
            SELECT
                lot_id,
                address,
                client_name,
                'possession'::text AS event_type,
                'Land Possession'::text AS event_label,
                land_possession_date AS event_date,
                NULL::numeric AS amount
            FROM base_lots
            WHERE land_possession_date IS NOT NULL
              AND sale_possession_date IS NULL

            UNION ALL

            SELECT
                lot_id,
                address,
                client_name,
                'other'::text AS event_type,
                'Land Balance Due'::text AS event_label,
                land_balance_due_date AS event_date,
                NULL::numeric AS amount
            FROM base_lots
            WHERE land_balance_due_date IS NOT NULL
        ),
        sales_deposit_events AS (
            SELECT
                b.lot_id,
                b.address,
                b.client_name,
                CASE
                    WHEN sds.deposit_number = 1 THEN 'deposit_1'
                    WHEN sds.deposit_number = 2 THEN 'deposit_2'
                    WHEN sds.deposit_number = 3 THEN 'deposit_3'
                    ELSE 'other'
                END AS event_type,
                CASE
                    WHEN sds.deposit_number IN (1, 2, 3) THEN 'Deposit #' || sds.deposit_number || ' Due'
                    ELSE 'Deposit Due'
                END AS event_label,
                sds.due_date AS event_date,
                sds.amount
            FROM base_lots b
            JOIN sales.deposit_schedule sds ON sds.agreement_id = b.sale_agreement_id
            WHERE sds.due_date IS NOT NULL
        ),
        land_deposit_events AS (
            SELECT
                b.lot_id,
                b.address,
                b.client_name,
                CASE
                    WHEN lds.deposit_number = 1 THEN 'deposit_1'
                    WHEN lds.deposit_number = 2 THEN 'deposit_2'
                    WHEN lds.deposit_number = 3 THEN 'deposit_3'
                    ELSE 'other'
                END AS event_type,
                CASE
                    WHEN lds.deposit_number IN (1, 2, 3) THEN 'Land Deposit #' || lds.deposit_number || ' Due'
                    ELSE 'Land Deposit Due'
                END AS event_label,
                lds.due_date AS event_date,
                lds.amount
            FROM base_lots b
            JOIN land.deposit_schedule lds ON lds.lot_id = b.lot_id
            WHERE lds.due_date IS NOT NULL
        ),
        milestone_events AS (
            SELECT
                b.lot_id,
                b.address,
                b.client_name,
                'other'::text AS event_type,
                COALESCE(NULLIF(lm.milestone_name, ''), 'Milestone') AS event_label,
                lm.expected_date AS event_date,
                NULL::numeric AS amount
            FROM base_lots b
            JOIN land.milestones lm ON lm.lot_id = b.lot_id
            WHERE lm.expected_date IS NOT NULL
              AND lm.completed_at IS NULL
        ),
        events AS (
            SELECT * FROM sale_date_events
            UNION ALL
            SELECT * FROM land_date_events
            UNION ALL
            SELECT * FROM sales_deposit_events
            UNION ALL
            SELECT * FROM land_deposit_events
            UNION ALL
            SELECT * FROM milestone_events
        )
        SELECT
            lot_id,
            address,
            client_name,
            event_type,
            event_label,
            event_date,
            amount,
            (event_date - CURRENT_DATE)::int AS days_until,
            CASE
                WHEN (event_date - CURRENT_DATE)::int <= 0 THEN 'overdue'
                WHEN (event_date - CURRENT_DATE)::int <= 14 THEN 'soon'
                ELSE 'upcoming'
            END AS urgency
        FROM events
        ORDER BY event_date ASC, address ASC, event_label ASC
    """)

    rows = (await db.execute(query, {"org_id": str(settings.default_org_id)})).mappings().all()
    return [
        TimelineEvent(
            id=f"{row['lot_id']}-{_event_slug(row['event_type'], row['event_label'], row['event_date'])}-{index}",
            lot_id=row["lot_id"],
            address=row["address"],
            client_name=row["client_name"] or "",
            event_type=row["event_type"],
            event_label=row["event_label"],
            event_date=row["event_date"],
            amount=row["amount"],
            days_until=row["days_until"],
            urgency=row["urgency"],
        )
        for index, row in enumerate(rows, start=1)
    ]


def _event_slug(event_type: str, event_label: str, event_date: date) -> str:
    label = "".join(character.lower() if character.isalnum() else "-" for character in event_label)
    label = "-".join(part for part in label.split("-") if part)
    return f"{event_type}-{event_date.isoformat()}-{label}"


@projects_router.get("", response_model=List[LotOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    return await _list_lots(db, "with_sale")


@router.get("/{lot_id}", response_model=LotOut)
async def get_lot(lot_id: str, db: AsyncSession = Depends(get_db)):
    query = text("""
        SELECT
            l.id::text AS id,
            l.property_id,
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
            SELECT string_agg(
                COALESCE(c.full_name, c.company_name),
                ', '
                ORDER BY sp.is_primary DESC, COALESCE(c.full_name, c.company_name)
            ) AS buyer_name
            FROM sales.parties sp
            JOIN core.contacts c ON c.id = sp.contact_id
            WHERE sp.agreement_id = sa.id
              AND sp.party_role IN ('buyer', 'co_buyer')
              AND COALESCE(c.full_name, c.company_name) IS NOT NULL
        ) buyers ON true
        WHERE l.id = :lot_id
          AND d.org_id = :org_id
    """)

    result = await db.execute(query, {"lot_id": lot_id, "org_id": str(settings.default_org_id)})
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
