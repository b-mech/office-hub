from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.rentals import RentalInspection, RentalInspectionPhoto, RentalLeaseImportBatch, RentalLeaseImportRow, RentalProperty, RentalUnit
from app.schemas.rental_inspections import InspectionCreate, InspectionOut, InspectionPatch, PhotoOut
from app.services import rental_inspections
from app.schemas.rentals import BulkApprovalOut, LeaseImportBatchOut, LeaseImportRowOut, LeaseImportRowPatch
from app.services import rental_lease_imports


router = APIRouter(prefix="/api/rentals/lease-import", tags=["rentals"])
inspections_router = APIRouter(prefix="/api/rentals", tags=["rentals"])

@inspections_router.get("/units")
async def rental_units(q:str|None=Query(None),db:AsyncSession=Depends(get_db))->list[dict[str,object]]:
    stmt=select(RentalUnit,RentalProperty).join(RentalProperty)
    if q: stmt=stmt.where((RentalProperty.street_address.ilike(f"%{q}%"))|(RentalProperty.group_name.ilike(f"%{q}%")))
    rows=(await db.execute(stmt.order_by(RentalProperty.group_name,RentalProperty.street_address,RentalUnit.unit_label))).all(); result=[]
    for unit,prop in rows:
        last=await db.scalar(select(RentalInspection).where(RentalInspection.unit_id==unit.id).order_by(RentalInspection.inspection_date.desc(),RentalInspection.id.desc()).limit(1))
        result.append({"id":unit.id,"street_address":prop.street_address,"group_name":prop.group_name,"unit_label":unit.unit_label,"last_inspection":None if not last else {"id":last.id,"inspection_date":last.inspection_date,"inspection_type":last.inspection_type,"status":last.status}})
    return result
@inspections_router.get("/units/{unit_id}/inspections",response_model=list[InspectionOut])
async def history(unit_id:int,db:AsyncSession=Depends(get_db))->list[InspectionOut]: return [await _inspection_out(db,x) for x in (await db.scalars(select(RentalInspection).where(RentalInspection.unit_id==unit_id).order_by(RentalInspection.inspection_date.desc()))).all()]
@inspections_router.post("/inspections",response_model=InspectionOut)
async def create_inspection(data:InspectionCreate,db:AsyncSession=Depends(get_db))->InspectionOut:
    try:return await _inspection_out(db,await rental_inspections.create(db,data))
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@inspections_router.get("/inspections/{inspection_id}",response_model=InspectionOut)
async def inspection_detail(inspection_id:int,db:AsyncSession=Depends(get_db))->InspectionOut:return await _inspection_out(db,await _inspection(db,inspection_id))
@inspections_router.patch("/inspections/{inspection_id}",response_model=InspectionOut)
async def patch_inspection(inspection_id:int,data:InspectionPatch,db:AsyncSession=Depends(get_db))->InspectionOut:
    try:return await _inspection_out(db,await rental_inspections.patch(db,await _inspection(db,inspection_id),data))
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@inspections_router.post("/inspections/{inspection_id}/submit",response_model=InspectionOut)
async def submit_inspection(inspection_id:int,db:AsyncSession=Depends(get_db))->InspectionOut:
    try:return await _inspection_out(db,await rental_inspections.submit(db,await _inspection(db,inspection_id)))
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@inspections_router.post("/inspections/{inspection_id}/photos",response_model=list[PhotoOut])
async def photos(inspection_id:int,files:list[UploadFile]=File(...),caption:list[str]=Form(default=[]),db:AsyncSession=Depends(get_db))->list[PhotoOut]:
    try:
        made=await rental_inspections.upload_photos(db,await _inspection(db,inspection_id),[(f.filename or "photo.jpg",await f.read()) for f in files],caption)
        return [_photo_out(x) for x in made]
    except (ValueError,RuntimeError) as exc:raise HTTPException(502 if isinstance(exc,RuntimeError) else 422,str(exc)) from exc
@inspections_router.delete("/inspections/{inspection_id}/photos/{photo_id}",status_code=204)
async def delete_photo(inspection_id:int,photo_id:int,db:AsyncSession=Depends(get_db))->Response:
    photo=await db.get(RentalInspectionPhoto,photo_id)
    if not photo or photo.inspection_id!=inspection_id:raise HTTPException(404,"Photo not found")
    try:await rental_inspections.remove_photo(db,photo)
    except RuntimeError as exc:raise HTTPException(502,str(exc)) from exc
    return Response(status_code=204)

async def _inspection(db:AsyncSession,item_id:int)->RentalInspection:
    item=await db.get(RentalInspection,item_id)
    if not item:raise HTTPException(404,"Inspection not found")
    return item
def _photo_out(photo:RentalInspectionPhoto)->PhotoOut:return PhotoOut.model_validate(photo).model_copy(update={"preview_url":f"https://app.box.com/file/{photo.box_file_id}" if photo.box_file_id else None})
async def _inspection_out(db:AsyncSession,item:RentalInspection)->InspectionOut:
    result=InspectionOut.model_validate(item); photos=list((await db.scalars(select(RentalInspectionPhoto).where(RentalInspectionPhoto.inspection_id==item.id))).all()); result.photos=[_photo_out(p) for p in photos]; return result


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
