from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.addresses import normalize_address
from app.models.sales import ChangeOrder
from app.schemas.financial_summaries import FinancialSummaryChangeOrders
from app.schemas.financial_summaries import FinancialSummaryDraw
from app.schemas.financial_summaries import FinancialSummaryLender
from app.schemas.financial_summaries import FinancialSummaryPrepDraw
from app.schemas.financial_summaries import PropertyFinancialSummary
from app.services import financing


async def get_property_financial_summary(
    db: AsyncSession,
    property_id: UUID,
) -> PropertyFinancialSummary | None:
    property_row = (
        await db.execute(
            text(
                """
                SELECT id, address, canonical_address_key
                FROM core.properties
                WHERE id = :property_id
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().one_or_none()
    if property_row is None:
        return None

    facility = (
        await db.execute(
            text(
                """
                SELECT
                    facility.id,
                    facility.lender_id,
                    COALESCE(lender.name, facility.lender_name) AS lender_name,
                    facility.lender_type
                FROM core.lender_facilities facility
                LEFT JOIN core.lenders lender ON lender.id = facility.lender_id
                WHERE facility.property_id = :property_id
                  AND facility.status = 'active'
                LIMIT 1
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().one_or_none()

    draw: FinancialSummaryDraw | None = None
    if facility is not None:
        detail = await financing.get_property_detail(db, property_id)
        document_count = (
            await db.execute(
                text(
                    """
                    SELECT count(*)
                    FROM documents.lender_facility_documents
                    WHERE facility_id = :facility_id
                    """
                ),
                {"facility_id": facility["id"]},
            )
        ).scalar_one()
        draw = FinancialSummaryDraw(
            opening_balance=detail.opening_balance if detail else None,
            drawn_to_date=detail.already_drawn if detail else None,
            remaining=detail.funds_remaining if detail else None,
            current_stage=detail.stage if detail else None,
            next_eligible_draw=detail.draw_eligible if detail else None,
            last_draw_date=detail.last_draw_date if detail else None,
            facility_document_count=document_count,
        )

    prep = await financing.prep_client_draw(db, property_id)
    if prep.schedule is None:
        prep_summary = FinancialSummaryPrepDraw(
            state="no_active_schedule",
            ready_to_request=False,
        )
    elif prep.schedule.reviewed_at is None:
        prep_summary = FinancialSummaryPrepDraw(
            state="pending_review",
            ready_to_request=False,
        )
    else:
        ready = bool(prep.requestable_items) and (prep.requestable_total or Decimal("0")) > 0
        prep_summary = FinancialSummaryPrepDraw(
            state="ready_to_request" if ready else "pending_review",
            ready_to_request=ready,
        )

    property_key = property_row["canonical_address_key"] or normalize_address(
        property_row["address"]
    ).canonical_key
    change_orders = (
        await db.execute(
            select(ChangeOrder)
            .where(ChangeOrder.archived_at.is_(None))
            .options(selectinload(ChangeOrder.line_items))
        )
    ).scalars().all()
    matching_orders = [
        order
        for order in change_orders
        if normalize_address(order.address).canonical_key == property_key
    ]
    signed_orders = [
        order for order in matching_orders if order.status in {"signed", "complete"}
    ]
    filed_orders = [order for order in matching_orders if order.box_file_id]
    change_order_summary = FinancialSummaryChangeOrders(
        count=len(matching_orders),
        pending_signature_count=sum(order.status == "sent" for order in matching_orders),
        total_value=sum((order.total for order in matching_orders), Decimal("0")),
        last_signed_at=max((order.updated_at for order in signed_orders), default=None),
        box_filed=None if not matching_orders else bool(filed_orders),
        box_unfiled=any(order.box_unfiled for order in matching_orders),
    )

    return PropertyFinancialSummary(
        property_id=property_id,
        lender=FinancialSummaryLender(
            has_lender=facility is not None,
            lender_id=facility["lender_id"] if facility else None,
            lender_name=facility["lender_name"] if facility else None,
            facility_type=facility["lender_type"] if facility else None,
        ),
        draw=draw,
        prep_draw=prep_summary,
        change_orders=change_order_summary,
    )
