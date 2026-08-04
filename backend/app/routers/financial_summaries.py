from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.financial_summaries import PropertyFinancialSummary
from app.services import financial_summaries


router = APIRouter(
    prefix="/api/v1/financing/properties",
    tags=["financing"],
)


@router.get("/{property_id}/financial-summary", response_model=PropertyFinancialSummary)
async def property_financial_summary(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PropertyFinancialSummary:
    summary = await financial_summaries.get_property_financial_summary(db, property_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return summary
