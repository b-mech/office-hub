from __future__ import annotations

from decimal import Decimal
import logging
import re
from pydantic import BaseModel
from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.addresses import normalize_address
from app.schemas.financing import ClientDrawRequestOut
from app.schemas.financing import ClientDrawScheduleOut
from app.schemas.financing import ClientDrawScheduleReviewRequest
from app.schemas.financing import ClientDrawStatusRequest
from app.schemas.financing import ClientPrepDrawConfirmRequest
from app.schemas.financing import ClientPrepDrawOut
from app.schemas.financing import ConstructionMilestoneOut
from app.schemas.financing import ConstructionMilestoneUpdate
from app.schemas.financing import ConfirmDocumentRequest
from app.schemas.financing import DocumentUploadOut
from app.schemas.financing import FacilityCreate
from app.schemas.financing import FacilityDocumentOut
from app.schemas.financing import FacilityOut
from app.schemas.financing import FacilityStatementSnapshotOut
from app.schemas.financing import FacilityUpdate
from app.schemas.financing import FinancingDashboardOut
from app.schemas.financing import FinancingPropertyOut
from app.schemas.financing import LenderStatementDetailOut
from app.schemas.financing import LenderStatementOut
from app.schemas.financing import ManualStatementSnapshotCreate
from app.schemas.financing import ProFacilityOut
from app.schemas.financing import ProLedgerOut
from app.schemas.financing import ProDrawRequestCreate
from app.schemas.financing import ProDrawBatchCreate
from app.schemas.financing import ProDrawRequestOut
from app.schemas.financing import ProDrawRequestStatusUpdate
from app.schemas.financing import SyncResult
from app.services import financing
from app.services.document_extractor import extract_financing_document
from app.services.document_extractor import requires_review
from app.services.minio_financing import FINANCING_BUCKET
from app.services.minio_financing import financing_key
from app.services.minio_financing import upload_financing_document
from app.services.sheets_sync import sync_from_sheet


router = APIRouter(prefix="/api/v1/financing", tags=["financing"])
logger = logging.getLogger(__name__)


class LinkFacilityRequest(BaseModel):
    facility_id: UUID


@router.post("/sync-from-sheet", response_model=SyncResult)
async def sync_sheet(db: AsyncSession = Depends(get_db)) -> SyncResult:
    return SyncResult(**await sync_from_sheet(db))


@router.get("/dashboard", response_model=FinancingDashboardOut)
async def dashboard(db: AsyncSession = Depends(get_db)) -> FinancingDashboardOut:
    return await financing.get_dashboard(db)


@router.get("/properties", response_model=list[FinancingPropertyOut])
async def properties(db: AsyncSession = Depends(get_db)) -> list[FinancingPropertyOut]:
    return (await financing.get_dashboard(db)).properties


@router.get("/properties/{property_id}", response_model=FinancingPropertyOut)
async def property_detail(property_id: UUID, db: AsyncSession = Depends(get_db)) -> FinancingPropertyOut:
    item = await financing.get_property_detail(db, property_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return item


@router.get("/pro-draw-requests", response_model=list[ProDrawRequestOut])
async def pro_draw_requests(
    property_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ProDrawRequestOut]:
    return await financing.list_pro_draw_requests(db, property_id)


@router.post("/properties/{property_id}/pro-draw-requests", response_model=ProDrawRequestOut)
async def create_pro_draw_request(
    property_id: UUID,
    data: ProDrawRequestCreate,
    db: AsyncSession = Depends(get_db),
) -> ProDrawRequestOut:
    try:
        return await financing.create_pro_draw_request(
            db,
            property_id,
            amount=data.amount,
            notes=data.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pro-draw-requests/batch", response_model=list[ProDrawRequestOut])
async def create_pro_draw_request_batch(
    data: ProDrawBatchCreate,
    db: AsyncSession = Depends(get_db),
) -> list[ProDrawRequestOut]:
    try:
        return await financing.create_pro_draw_request_batch(db, data.property_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/pro-draw-requests/{request_id}", response_model=ProDrawRequestOut)
async def update_pro_draw_request(
    request_id: UUID,
    data: ProDrawRequestStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProDrawRequestOut:
    try:
        result = await financing.update_pro_draw_request_status(
            db,
            request_id,
            status=data.status,
            notes=data.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="PRO draw request not found")
    return result


@router.patch("/pro-draw-request-batches/{batch_id}", response_model=list[ProDrawRequestOut])
async def update_pro_draw_request_batch(
    batch_id: UUID,
    data: ProDrawRequestStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> list[ProDrawRequestOut]:
    try:
        rows = await financing.update_pro_draw_batch_status(
            db,
            batch_id,
            status=data.status,
            notes=data.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not rows:
        raise HTTPException(status_code=404, detail="PRO draw request batch not found")
    return rows


@router.patch(
    "/milestones/{milestone_id}",
    response_model=ConstructionMilestoneOut,
)
async def update_milestone(
    milestone_id: UUID,
    data: ConstructionMilestoneUpdate,
    db: AsyncSession = Depends(get_db),
) -> ConstructionMilestoneOut:
    milestone = await financing.update_construction_milestone(
        db,
        milestone_id,
        data,
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="Construction milestone not found")
    return milestone


@router.post("/properties/{property_id}/otp", response_model=ClientDrawScheduleOut)
async def upload_client_otp(
    property_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> ClientDrawScheduleOut:
    property_detail = await financing.get_property_detail(db, property_id)
    if property_detail is None:
        raise HTTPException(status_code=404, detail="Property not found")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    filename = file.filename or "otp-sale.pdf"
    canonical = normalize_address(property_detail.address).canonical_key
    key = f"financing/client-otp/{_safe_path(canonical)}/{_safe_path(filename)}"
    try:
        upload_financing_document(key=key, content=content, content_type=file.content_type or "application/pdf")
        schedule = await financing.create_client_otp_upload(
            db,
            property_id=property_id,
            minio_bucket=FINANCING_BUCKET,
            minio_key=key,
            original_filename=filename,
            content_length=len(content),
        )
        background_tasks.add_task(
            financing.extract_client_otp_schedule_background,
            schedule.id,
            content=content,
            content_type=file.content_type or "application/pdf",
        )
        return schedule
    except Exception as exc:
        logger.exception("Client OTP upload failed")
        raise HTTPException(status_code=500, detail=f"Client OTP upload failed: {exc}") from exc


@router.get("/properties/{property_id}/otp", response_model=ClientDrawScheduleOut | None)
async def get_client_otp(property_id: UUID, db: AsyncSession = Depends(get_db)) -> ClientDrawScheduleOut | None:
    return await financing.get_active_client_draw_schedule(db, property_id)


@router.patch("/otp/{schedule_id}/review", response_model=ClientDrawScheduleOut)
async def review_client_otp(
    schedule_id: UUID,
    data: ClientDrawScheduleReviewRequest,
    db: AsyncSession = Depends(get_db),
) -> ClientDrawScheduleOut:
    reviewed = await financing.review_client_draw_schedule(db, schedule_id, data.model_dump())
    if reviewed is None:
        raise HTTPException(status_code=404, detail="OTP schedule not found")
    return reviewed


@router.post("/otp/{schedule_id}/prepare-official-review")
async def prepare_official_otp_review(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, UUID]:
    document_id = await financing.prepare_client_otp_official_review(
        db,
        schedule_id,
    )
    if document_id is None:
        raise HTTPException(status_code=404, detail="OTP schedule not found")
    return {"document_id": document_id}


@router.get("/properties/{property_id}/draw-requests", response_model=list[ClientDrawRequestOut])
async def client_draw_requests(property_id: UUID, db: AsyncSession = Depends(get_db)) -> list[ClientDrawRequestOut]:
    return await financing.list_client_draw_requests(db, property_id)


@router.post("/properties/{property_id}/prep-draw", response_model=ClientPrepDrawOut)
async def prep_client_draw(property_id: UUID, db: AsyncSession = Depends(get_db)) -> ClientPrepDrawOut:
    try:
        return await financing.prep_client_draw(db, property_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/properties/{property_id}/prep-draw/confirm", response_model=ClientDrawRequestOut)
async def confirm_client_prep_draw(
    property_id: UUID,
    data: ClientPrepDrawConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> ClientDrawRequestOut:
    try:
        return await financing.confirm_client_prep_draw(
            db,
            property_id,
            draw_items=data.draw_items,
            amount=data.amount,
            notes=data.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/prep-draw/requests/{request_id}/status", response_model=ClientDrawRequestOut)
async def update_client_draw_status(
    request_id: UUID,
    data: ClientDrawStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> ClientDrawRequestOut:
    try:
        updated = await financing.update_client_draw_request_status(db, request_id, status=data.status, notes=data.notes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Draw request not found")
    return updated


@router.post("/facilities", response_model=FacilityOut)
async def create_facility(data: FacilityCreate, db: AsyncSession = Depends(get_db)) -> FacilityOut:
    return await financing.create_facility(db, data)


@router.get("/facilities", response_model=list[ProFacilityOut])
async def facilities(lender: str | None = None, db: AsyncSession = Depends(get_db)) -> list[ProFacilityOut]:
    if (lender or "").upper() != "PRO":
        raise HTTPException(status_code=400, detail="Only lender=PRO is supported by this endpoint")
    return await financing.list_pro_facilities(db)


@router.get("/facilities/{facility_id}/ledger", response_model=ProLedgerOut)
async def facility_ledger(facility_id: UUID, db: AsyncSession = Depends(get_db)) -> ProLedgerOut:
    ledger = await financing.get_pro_ledger(db, facility_id)
    if ledger is None:
        raise HTTPException(status_code=404, detail="PRO facility not found")
    return ledger


@router.put("/facilities/{facility_id}", response_model=FacilityOut)
async def update_facility(
    facility_id: UUID,
    data: FacilityUpdate,
    db: AsyncSession = Depends(get_db),
) -> FacilityOut:
    updated = await financing.update_facility(db, facility_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    return updated


@router.patch("/facilities/{facility_id}", response_model=FacilityOut)
async def patch_facility(
    facility_id: UUID,
    data: FacilityUpdate,
    db: AsyncSession = Depends(get_db),
) -> FacilityOut:
    return await update_facility(facility_id, data, db)


@router.delete("/facilities/{facility_id}")
async def delete_facility(facility_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    deleted = await financing.delete_facility(db, facility_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Facility not found")
    return {"deleted": True}


@router.post("/statements", response_model=LenderStatementOut)
async def upload_statement(
    lender: str = Form(...),
    period: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> LenderStatementOut:
    if lender.upper() != "PRO":
        raise HTTPException(status_code=400, detail="Only PRO statements are supported")
    if not period or len(period) != 7:
        raise HTTPException(status_code=400, detail="period must be YYYY-MM")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename or "statement.pdf"
    key = f"financing/pro/statements/{period}/{filename}"
    upload_financing_document(key=key, content=content, content_type=file.content_type or "application/pdf")
    statement_id = await financing.record_statement(
        db,
        lender="PRO",
        period=period,
        minio_object_key=key,
        original_filename=filename,
    )
    await financing.parse_and_reconcile_statement(db, statement_id, content)
    statement = await financing.get_statement(db, statement_id)
    if statement is None:
        raise HTTPException(status_code=500, detail="Statement upload could not be loaded after save")
    return LenderStatementOut(**statement.model_dump(exclude={"parse_payload", "snapshots"}))


@router.get("/statements", response_model=list[LenderStatementOut])
async def statements(lender: str | None = None, db: AsyncSession = Depends(get_db)) -> list[LenderStatementOut]:
    return await financing.list_statements(db, lender.upper() if lender else None)


@router.get("/statements/{statement_id}", response_model=LenderStatementDetailOut)
async def statement_detail(statement_id: UUID, db: AsyncSession = Depends(get_db)) -> LenderStatementDetailOut:
    statement = await financing.get_statement(db, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return statement


@router.post(
    "/statements/{statement_id}/retry",
    response_model=LenderStatementDetailOut,
)
async def retry_statement(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> LenderStatementDetailOut:
    statement = await financing.retry_statement_parse(db, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return statement


@router.post(
    "/statements/{statement_id}/manual-snapshots",
    response_model=LenderStatementDetailOut,
)
async def create_manual_snapshot(
    statement_id: UUID,
    data: ManualStatementSnapshotCreate,
    db: AsyncSession = Depends(get_db),
) -> LenderStatementDetailOut:
    try:
        statement = await financing.create_manual_statement_snapshot(
            db,
            statement_id,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if statement is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return statement


@router.post("/statements/snapshots/{snapshot_id}/approve-draws", response_model=FacilityStatementSnapshotOut)
async def approve_statement_draws(snapshot_id: UUID, db: AsyncSession = Depends(get_db)) -> FacilityStatementSnapshotOut:
    snapshot = await financing.approve_snapshot_draws(db, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found or not linked")
    return snapshot


@router.post("/statements/snapshots/{snapshot_id}/link-facility", response_model=FacilityStatementSnapshotOut)
async def link_statement_facility(
    snapshot_id: UUID,
    data: LinkFacilityRequest,
    db: AsyncSession = Depends(get_db),
) -> FacilityStatementSnapshotOut:
    snapshot = await financing.link_snapshot_facility(db, snapshot_id, data.facility_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@router.post("/documents/upload", response_model=DocumentUploadOut)
async def upload_document(
    lender_type: str = Form(...),
    property_id: UUID | None = Form(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadOut:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename or "document"
    property_detail = await financing.get_property_detail(db, property_id) if property_id else None

    key = financing_key(lender_type, filename, property_detail.address if property_detail else None)
    try:
        upload_financing_document(key=key, content=content, content_type=file.content_type or "application/octet-stream")
        extracted = await extract_financing_document(
            lender_type=lender_type,
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
        financing_doc_id, review_document_id = await financing.record_document(
            db,
            facility_id=property_detail.facility_id if property_detail else None,
            lender_type=lender_type.upper(),
            document_type=_document_type(lender_type, file.content_type),
            minio_bucket=FINANCING_BUCKET,
            minio_key=key,
            original_filename=filename,
            content=content,
            extracted_values=extracted,
        )
    except Exception as exc:
        logger.exception("Financing document upload failed")
        raise HTTPException(status_code=500, detail=f"Document upload failed: {exc}") from exc
    return DocumentUploadOut(
        doc_id=financing_doc_id,
        review_document_id=review_document_id,
        lender_type=lender_type.upper(),
        minio_key=key,
        extracted=extracted,
        requires_review=requires_review(extracted),
    )


@router.get("/documents/{facility_id}", response_model=list[FacilityDocumentOut])
async def documents(facility_id: UUID, db: AsyncSession = Depends(get_db)) -> list[FacilityDocumentOut]:
    return await financing.list_documents(db, facility_id)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    deleted = await financing.delete_document(db, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}


@router.post("/documents/{doc_id}/confirm", response_model=FacilityOut)
async def confirm_document(
    doc_id: UUID,
    data: ConfirmDocumentRequest,
    db: AsyncSession = Depends(get_db),
) -> FacilityOut:
    facility_id = data.facility_id
    if facility_id is None:
        raise HTTPException(status_code=400, detail="facility_id is required")

    values = data.values
    update_values = {}
    for target, keys in {
        "total_facility": ("total_facility", "total_commitment"),
        "opening_balance": ("opening_balance", "available_balance"),
        "already_drawn": ("already_drawn", "current_balance"),
    }.items():
        value = next((values[key] for key in keys if values.get(key) not in (None, "")), None)
        if value is not None:
            update_values[target] = _decimal(value)

    updated = await financing.update_facility(db, facility_id, FacilityUpdate(**update_values))
    if updated is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    await db.execute(
        text(
            "UPDATE documents.lender_facility_documents SET confirmed_at = now(), facility_id = :facility_id WHERE id = :doc_id"
        ),
        {"facility_id": facility_id, "doc_id": doc_id},
    )
    await db.commit()
    return updated


def _document_type(lender_type: str, content_type: str | None) -> str:
    lender = lender_type.upper()
    if lender == "PRO":
        return "PRO_BREAKDOWN"
    if lender == "RSU":
        return "RSU_MANUAL"
    return f"{lender}_SCREENSHOT" if content_type != "application/pdf" else f"{lender}_STATEMENT"


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value).replace(",", ""))


def _safe_path(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned[:160] or "file"
