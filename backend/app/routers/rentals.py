from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.rentals import RentalLeaseImportBatch, RentalLeaseImportRow, RentalProperty, RentalUnit
from app.schemas.rentals import BulkApprovalOut, LeaseImportBatchOut, LeaseImportRowOut, LeaseImportRowPatch
from app.services import rental_lease_imports


router = APIRouter(prefix="/api/rentals/lease-import", tags=["rentals"])


@router.get("/units")
async def list_units(db: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    rows = (await db.execute(select(RentalUnit.id, RentalProperty.street_address, RentalUnit.unit_label).join(RentalProperty).order_by(RentalProperty.street_address, RentalUnit.unit_label))).all()
    return [{"id": row.id, "street_address": row.street_address, "unit_label": row.unit_label} for row in rows]


@router.get("/template")
async def download_template(db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    content = await rental_lease_imports.generate_template(db)
    headers = {"Content-Disposition": 'attachment; filename="office-hub-rental-lease-import.xlsx"'}
    return StreamingResponse(BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@router.post("/upload", response_model=LeaseImportBatchOut)
async def upload_template(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> LeaseImportBatchOut:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="Upload an .xlsx lease-import template")
    try:
        batch = await rental_lease_imports.upload_and_extract(db, file.filename, await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _batch_out(db, batch)


@router.get("/batches", response_model=list[LeaseImportBatchOut])
async def list_batches(db: AsyncSession = Depends(get_db)) -> list[LeaseImportBatchOut]:
    batches = list((await db.scalars(select(RentalLeaseImportBatch).order_by(RentalLeaseImportBatch.uploaded_at.desc()))).all())
    return [LeaseImportBatchOut.model_validate(batch) for batch in batches]


@router.get("/batches/{batch_id}", response_model=LeaseImportBatchOut)
async def batch_detail(batch_id: int, db: AsyncSession = Depends(get_db)) -> LeaseImportBatchOut:
    batch = await db.get(RentalLeaseImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lease import batch not found")
    return await _batch_out(db, batch)


@router.patch("/rows/{row_id}", response_model=LeaseImportRowOut)
async def edit_row(row_id: int, patch: LeaseImportRowPatch, db: AsyncSession = Depends(get_db)) -> LeaseImportRowOut:
    row = await _row(db, row_id)
    return LeaseImportRowOut.model_validate(await rental_lease_imports.patch_row(db, row, patch))


@router.post("/rows/{row_id}/approve", response_model=LeaseImportRowOut)
async def approve_row(row_id: int, db: AsyncSession = Depends(get_db)) -> LeaseImportRowOut:
    row = await _row(db, row_id)
    try:
        return LeaseImportRowOut.model_validate(await rental_lease_imports.approve_row(db, row))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rows/{row_id}/reject", response_model=LeaseImportRowOut)
async def reject_row(row_id: int, db: AsyncSession = Depends(get_db)) -> LeaseImportRowOut:
    row = await _row(db, row_id)
    try:
        return LeaseImportRowOut.model_validate(await rental_lease_imports.reject_row(db, row))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/approve-all", response_model=BulkApprovalOut)
async def approve_all(batch_id: int, db: AsyncSession = Depends(get_db)) -> BulkApprovalOut:
    if not await db.get(RentalLeaseImportBatch, batch_id):
        raise HTTPException(status_code=404, detail="Lease import batch not found")
    approved, skipped = await rental_lease_imports.approve_all_clean(db, batch_id)
    return BulkApprovalOut(approved=approved, skipped_for_review=skipped)


async def _row(db: AsyncSession, row_id: int) -> RentalLeaseImportRow:
    row = await db.get(RentalLeaseImportRow, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lease import row not found")
    return row


async def _batch_out(db: AsyncSession, batch: RentalLeaseImportBatch) -> LeaseImportBatchOut:
    rows = list((await db.scalars(select(RentalLeaseImportRow).where(RentalLeaseImportRow.batch_id == batch.id).order_by(RentalLeaseImportRow.source_row_number))).all())
    result = LeaseImportBatchOut.model_validate(batch)
    result.rows = [LeaseImportRowOut.model_validate(row) for row in rows]
    return result
