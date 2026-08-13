from __future__ import annotations

from io import BytesIO

import asyncio
import secrets
from datetime import date, datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import func
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.rentals import RentalInspection, RentalInspectionPhoto, RentalInspectionReport, RentalInspectionReportComment, RentalInspectionReportItem, RentalLeaseImportBatch, RentalLeaseImportRow, RentalProperty, RentalUnit
from app.schemas.rental_inspections import InspectionCreate, InspectionOut, InspectionPatch, PhotoOut, ReportCommentCreate, ReportCreate, ReportNotePatch, ReportSend
from app.services import rental_inspections, rental_inspection_reports
from app.services.box import download_file
from app.schemas.rentals import BulkApprovalOut, LeaseImportBatchOut, LeaseImportRowOut, LeaseImportRowPatch
from app.services import rental_lease_imports


router = APIRouter(prefix="/api/rentals/lease-import", tags=["rentals"])
inspections_router = APIRouter(prefix="/api/rentals", tags=["rentals"])

async def _report_payload(db:AsyncSession,report:RentalInspectionReport,token:str|None=None)->dict[str,object]:
    rows=(await db.execute(select(RentalInspectionReportItem,RentalInspection,RentalUnit,RentalProperty).join(RentalInspection,RentalInspection.id==RentalInspectionReportItem.inspection_id).join(RentalUnit,RentalUnit.id==RentalInspection.unit_id).join(RentalProperty,RentalProperty.id==RentalUnit.property_id).where(RentalInspectionReportItem.report_id==report.id).order_by(RentalInspectionReportItem.sort_order))).all()
    items=[]
    for report_item,inspection,unit,prop in rows:
        photos=list((await db.scalars(select(RentalInspectionPhoto).where(RentalInspectionPhoto.inspection_id==inspection.id).order_by(RentalInspectionPhoto.id))).all())
        comments=list((await db.scalars(select(RentalInspectionReportComment).where(RentalInspectionReportComment.report_item_id==report_item.id).order_by(RentalInspectionReportComment.created_at,RentalInspectionReportComment.id))).all())
        items.append({"id":str(report_item.id),"inspection_id":inspection.id,"address":prop.street_address,"unit_label":unit.unit_label,"inspection_date":inspection.inspection_date,"inspection_type":inspection.inspection_type,"front_yard_score":inspection.front_yard_score,"front_yard_notes":inspection.front_yard_notes,"back_yard_score":inspection.back_yard_score,"back_yard_notes":inspection.back_yard_notes,"building_condition":inspection.building_condition,"building_notes":inspection.building_notes,"occupancy_flag":inspection.occupancy_flag,"general_notes":inspection.general_notes,"notes":report_item.notes,"notes_submitted_at":report_item.notes_submitted_at,"comments":[{"id":str(comment.id),"author_name":comment.author_name,"body":comment.body,"created_at":comment.created_at} for comment in comments],"photos":[{"id":photo.id,"caption":photo.caption,"url":f"/api/rentals/reports/public/{token}/photos/{photo.id}" if token else None} for photo in photos]})
    return {"id":str(report.id),"title":report.title,"status":report.status,"recipient_email":report.recipient_email,"expires_at":report.expires_at,"sent_at":report.sent_at,"items":items}

async def _public_report(db:AsyncSession,token:str)->RentalInspectionReport:
    report=await db.scalar(select(RentalInspectionReport).where(RentalInspectionReport.token_hash==rental_inspection_reports.token_hash(token)))
    if not report: raise HTTPException(404,"Report link not found")
    expires_at=report.expires_at if report.expires_at.tzinfo else report.expires_at.replace(tzinfo=timezone.utc)
    if expires_at<=datetime.now(timezone.utc): raise HTTPException(410,"This report link has expired")
    return report

@inspections_router.get("/reports/candidates")
async def report_candidates(db:AsyncSession=Depends(get_db))->list[dict[str,object]]:
    rows=(await db.execute(select(RentalInspection,RentalUnit,RentalProperty).join(RentalUnit,RentalUnit.id==RentalInspection.unit_id).join(RentalProperty,RentalProperty.id==RentalUnit.property_id).where(RentalInspection.status=="submitted").order_by(RentalProperty.street_address,RentalInspection.inspection_date.desc(),RentalInspection.id.desc()))).all(); seen=set(); result=[]
    for inspection,unit,prop in rows:
        if prop.id in seen: continue
        seen.add(prop.id); result.append({"inspection_id":inspection.id,"property_id":prop.id,"address":prop.street_address,"unit_label":unit.unit_label,"inspection_date":inspection.inspection_date,"front_yard_score":inspection.front_yard_score,"back_yard_score":inspection.back_yard_score})
    return result

@inspections_router.post("/reports")
async def create_report(data:ReportCreate,db:AsyncSession=Depends(get_db))->dict[str,object]:
    try: report,_=await rental_inspection_reports.create_report(db,data.title,data.inspection_ids,data.expires_in_days)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    return await _report_payload(db,report)

@inspections_router.get("/reports")
async def list_reports(db:AsyncSession=Depends(get_db))->list[dict[str,object]]:
    reports=list((await db.scalars(select(RentalInspectionReport).order_by(RentalInspectionReport.created_at.desc()))).all())
    return [await _report_payload(db,report) for report in reports]

@inspections_router.delete("/reports/{report_id}",status_code=204)
async def delete_report(report_id:UUID,db:AsyncSession=Depends(get_db))->Response:
    report=await db.get(RentalInspectionReport,report_id)
    if not report: raise HTTPException(404,"Report not found")
    await db.delete(report); await db.commit()
    return Response(status_code=204)

@inspections_router.post("/reports/{report_id}/send")
async def send_report(report_id:UUID,data:ReportSend,db:AsyncSession=Depends(get_db))->dict[str,object]:
    report=await db.get(RentalInspectionReport,report_id)
    if not report: raise HTTPException(404,"Report not found")
    token=secrets.token_urlsafe(32); report.token_hash=rental_inspection_reports.token_hash(token)
    public_url=f"{data.public_base_url.rstrip('/')}/rentals/reports/{token}"
    try: await rental_inspection_reports.send_report_email(db,report,data.recipient_email,public_url)
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(503,str(exc)) from exc
    return {"report":await _report_payload(db,report),"public_url":public_url}

@inspections_router.get("/reports/public/{token}")
async def public_report(token:str,db:AsyncSession=Depends(get_db))->dict[str,object]: return await _report_payload(db,await _public_report(db,token),token)

@inspections_router.patch("/reports/public/{token}/items/{item_id}")
async def save_report_note(token:str,item_id:UUID,data:ReportNotePatch,db:AsyncSession=Depends(get_db))->dict[str,object]:
    report=await _public_report(db,token); item=await db.get(RentalInspectionReportItem,item_id)
    if not item or item.report_id!=report.id: raise HTTPException(404,"Report item not found")
    item.notes=data.notes.strip() or None; item.notes_submitted_at=datetime.now(timezone.utc); await db.commit()
    return {"id":str(item.id),"notes":item.notes,"notes_submitted_at":item.notes_submitted_at}

@inspections_router.post("/reports/public/{token}/items/{item_id}/comments",status_code=201)
async def add_report_comment(token:str,item_id:UUID,data:ReportCommentCreate,db:AsyncSession=Depends(get_db))->dict[str,object]:
    report=await _public_report(db,token); item=await db.get(RentalInspectionReportItem,item_id)
    if not item or item.report_id!=report.id: raise HTTPException(404,"Report item not found")
    comment=RentalInspectionReportComment(report_item_id=item.id,author_name=data.author_name.strip(),body=data.body.strip())
    db.add(comment); await db.commit(); await db.refresh(comment)
    return {"id":str(comment.id),"author_name":comment.author_name,"body":comment.body,"created_at":comment.created_at}

@inspections_router.get("/reports/public/{token}/photos/{photo_id}")
async def public_report_photo(token:str,photo_id:int,db:AsyncSession=Depends(get_db))->StreamingResponse:
    report=await _public_report(db,token)
    photo=await db.scalar(select(RentalInspectionPhoto).join(RentalInspectionReportItem,RentalInspectionReportItem.inspection_id==RentalInspectionPhoto.inspection_id).where(RentalInspectionReportItem.report_id==report.id,RentalInspectionPhoto.id==photo_id))
    if not photo or not photo.box_file_id: raise HTTPException(404,"Photo not found")
    try: content=await asyncio.to_thread(download_file,photo.box_file_id)
    except RuntimeError as exc: raise HTTPException(502,"Could not load photo from Box") from exc
    return StreamingResponse(iter([content]),media_type="image/jpeg")

@inspections_router.get("/units")
async def rental_units(q:str|None=Query(None),property_id:int|None=Query(None),db:AsyncSession=Depends(get_db))->list[dict[str,object]]:
    stmt=select(RentalUnit,RentalProperty).join(RentalProperty)
    if q: stmt=stmt.where((RentalProperty.street_address.ilike(f"%{q}%"))|(RentalProperty.group_name.ilike(f"%{q}%")))
    if property_id is not None: stmt=stmt.where(RentalProperty.id==property_id)
    rows=(await db.execute(stmt.order_by(RentalProperty.group_name,RentalProperty.street_address,RentalUnit.unit_label))).all(); result=[]
    for unit,prop in rows:
        last=await db.scalar(select(RentalInspection).where(RentalInspection.unit_id==unit.id,RentalInspection.status=="submitted").order_by(RentalInspection.inspection_date.desc(),RentalInspection.id.desc()).limit(1))
        result.append({"id":unit.id,"street_address":prop.street_address,"group_name":prop.group_name,"unit_label":unit.unit_label,"last_inspection":None if not last else {"id":last.id,"inspection_date":last.inspection_date,"inspection_type":last.inspection_type,"status":last.status}})
    return result

@inspections_router.get("/properties/map")
async def property_map(db:AsyncSession=Depends(get_db))->list[dict[str,object]]:
    properties=list((await db.scalars(select(RentalProperty).order_by(RentalProperty.street_address))).all());result=[];today=date.today()
    for prop in properties:
        unit_ids=select(RentalUnit.id).where(RentalUnit.property_id==prop.id)
        unit_count=int(await db.scalar(select(func.count()).select_from(RentalUnit).where(RentalUnit.property_id==prop.id)) or 0)
        last=await db.scalar(select(func.max(RentalInspection.inspection_date)).where(RentalInspection.unit_id.in_(unit_ids),RentalInspection.status=="submitted"))
        age=(today-last).days if last else None
        status="never" if age is None else "current" if age<=183 else "due" if age<=365 else "overdue"
        result.append({"property_id":prop.id,"street_address":prop.street_address,"group_name":prop.group_name,"latitude":prop.latitude,"longitude":prop.longitude,"unit_count":unit_count,"last_inspection_date":last,"inspection_status":status})
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
@inspections_router.delete("/inspections/{inspection_id}",status_code=204)
async def delete_inspection(inspection_id:int,db:AsyncSession=Depends(get_db))->Response:
    try: await rental_inspections.delete(db,await _inspection(db,inspection_id))
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from exc
    return Response(status_code=204)
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
