from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.lenders import LenderCreate
from app.schemas.lenders import LenderDetail
from app.schemas.lenders import LenderListItem
from app.schemas.lenders import LenderUpdate
from app.services import lenders


router = APIRouter(prefix="/api/v1/financing/lenders", tags=["financing-lenders"])


@router.get("", response_model=list[LenderListItem])
@router.get("/", response_model=list[LenderListItem], include_in_schema=False)
async def list_lenders(db: AsyncSession = Depends(get_db)) -> list[LenderListItem]:
    return await lenders.list_lenders(db)


@router.post("", response_model=LenderDetail, status_code=201)
@router.post("/", response_model=LenderDetail, status_code=201, include_in_schema=False)
async def create_lender(
    data: LenderCreate,
    db: AsyncSession = Depends(get_db),
) -> LenderDetail:
    try:
        return await lenders.create_lender(db, data)
    except (lenders.DuplicateLenderNameError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{lender_id}", response_model=LenderDetail)
async def lender_detail(
    lender_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> LenderDetail:
    lender = await lenders.get_lender(db, lender_id)
    if lender is None:
        raise HTTPException(status_code=404, detail="Lender not found")
    return lender


@router.patch("/{lender_id}", response_model=LenderDetail)
async def update_lender(
    lender_id: UUID,
    data: LenderUpdate,
    db: AsyncSession = Depends(get_db),
) -> LenderDetail:
    try:
        lender = await lenders.update_lender(db, lender_id, data)
    except (lenders.DuplicateLenderNameError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if lender is None:
        raise HTTPException(status_code=404, detail="Lender not found")
    return lender


@router.delete("/{lender_id}", status_code=204)
async def delete_lender(
    lender_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        deleted = await lenders.delete_lender(db, lender_id)
    except lenders.LinkedFacilitiesError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Lender not found")
    return Response(status_code=204)
