from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.construction_stage_history import list_stage_history


router = APIRouter(prefix="/api/v1/financing", tags=["financing"])


class ConstructionStageHistoryOut(BaseModel):
    id: UUID
    property_id: UUID
    previous_stage: str | None
    new_stage: str
    changed_at: datetime
    synced_at: datetime


@router.get(
    "/properties/{property_id}/construction-stage-history",
    response_model=list[ConstructionStageHistoryOut],
)
async def property_construction_stage_history(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ConstructionStageHistoryOut]:
    return [ConstructionStageHistoryOut.model_validate(row) for row in await list_stage_history(db, property_id)]
