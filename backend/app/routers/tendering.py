from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.tendering import TenderDocument
from app.models.tendering import TenderBidDocument
from app.schemas.tendering import CategoryOut
from app.schemas.tendering import ContractorCreate
from app.schemas.tendering import ContractorOut
from app.schemas.tendering import ContractorUpdate
from app.schemas.tendering import TenderDocumentOut
from app.schemas.tendering import TenderDocumentType
from app.schemas.tendering import TenderPackageCreate
from app.schemas.tendering import TenderPackageOut
from app.schemas.tendering import TenderPackageUpdate
from app.schemas.tendering import TenderAwardCreate, TenderAwardOut, TenderBidCreate, TenderBidOut, TenderBidUpdate, TenderComparisonOut, PurchaseOrderSummary
from app.services import tendering


router = APIRouter(prefix="/api", tags=["tendering"])


@router.get("/contractor-categories", response_model=list[CategoryOut])
async def contractor_categories(db: AsyncSession = Depends(get_db)) -> list[CategoryOut]:
    return [CategoryOut.model_validate(item) for item in await tendering.list_categories(db)]


@router.get("/contractors", response_model=list[ContractorOut])
async def contractors(
    category_id: UUID | None = None,
    active: Annotated[bool | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
) -> list[ContractorOut]:
    return [ContractorOut.model_validate(item) for item in await tendering.list_contractors(db, category_id, active)]


@router.post("/contractors", response_model=ContractorOut, status_code=201)
async def create_contractor(data: ContractorCreate, db: AsyncSession = Depends(get_db)) -> ContractorOut:
    try:
        return ContractorOut.model_validate(await tendering.create_contractor(db, data))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/contractors/{contractor_id}", response_model=ContractorOut)
async def contractor_detail(contractor_id: UUID, db: AsyncSession = Depends(get_db)) -> ContractorOut:
    contractor = await tendering.get_contractor(db, contractor_id)
    if contractor is None:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return ContractorOut.model_validate(contractor)


@router.patch("/contractors/{contractor_id}", response_model=ContractorOut)
async def update_contractor(contractor_id: UUID, data: ContractorUpdate, db: AsyncSession = Depends(get_db)) -> ContractorOut:
    contractor = await tendering.get_contractor(db, contractor_id)
    if contractor is None:
        raise HTTPException(status_code=404, detail="Contractor not found")
    try:
        return ContractorOut.model_validate(await tendering.update_contractor(db, contractor, data))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/contractors/{contractor_id}", response_model=ContractorOut)
async def deactivate_contractor(contractor_id: UUID, db: AsyncSession = Depends(get_db)) -> ContractorOut:
    contractor = await tendering.get_contractor(db, contractor_id)
    if contractor is None:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return ContractorOut.model_validate(await tendering.deactivate_contractor(db, contractor))


@router.get("/properties/{property_id}/tender-packages", response_model=list[TenderPackageOut])
async def property_tender_packages(property_id: UUID, db: AsyncSession = Depends(get_db)) -> list[TenderPackageOut]:
    return [TenderPackageOut.model_validate(item) for item in await tendering.list_tender_packages(db, property_id)]


@router.post("/properties/{property_id}/tender-packages", response_model=TenderPackageOut, status_code=201)
async def create_tender_package(property_id: UUID, data: TenderPackageCreate, db: AsyncSession = Depends(get_db)) -> TenderPackageOut:
    try:
        return TenderPackageOut.model_validate(await tendering.create_tender_package(db, property_id, data))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tender-packages/{package_id}", response_model=TenderPackageOut)
async def tender_package_detail(package_id: UUID, db: AsyncSession = Depends(get_db)) -> TenderPackageOut:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    return TenderPackageOut.model_validate(package)


@router.patch("/tender-packages/{package_id}", response_model=TenderPackageOut)
async def update_tender_package(package_id: UUID, data: TenderPackageUpdate, db: AsyncSession = Depends(get_db)) -> TenderPackageOut:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    try:
        return TenderPackageOut.model_validate(await tendering.update_tender_package(db, package, data))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tender-packages/{package_id}/documents", response_model=TenderDocumentOut, status_code=201)
async def upload_tender_document(
    package_id: UUID,
    document_type: Annotated[TenderDocumentType, Form()],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> TenderDocumentOut:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    try:
        return TenderDocumentOut.model_validate(await tendering.upload_tender_document(db, package, document_type, file))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tender-packages/{package_id}/documents", response_model=list[TenderDocumentOut])
async def tender_documents(package_id: UUID, db: AsyncSession = Depends(get_db)) -> list[TenderDocumentOut]:
    if await tendering.get_tender_package(db, package_id) is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    return [TenderDocumentOut.model_validate(item) for item in await tendering.list_tender_documents(db, package_id)]


@router.get("/tender-documents/{document_id}/content")
async def tender_document_content(document_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    document = await db.get(TenderDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Tender document not found")
    content = await tendering.get_tender_document_content(document)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{document.original_filename}"'})


@router.delete("/tender-documents/{document_id}", status_code=204)
async def delete_tender_document(document_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    document = await db.get(TenderDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Tender document not found")
    await tendering.delete_tender_document(db, document)
    return Response(status_code=204)


@router.post("/tender-packages/{package_id}/bids", response_model=TenderBidOut, status_code=201)
async def create_tender_bid(package_id: UUID, data: TenderBidCreate, db: AsyncSession = Depends(get_db)) -> TenderBidOut:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    try:
        return TenderBidOut.model_validate(await tendering.create_tender_bid(db, package, data))
    except ValueError as exc:
        status_code = 409 if "at most 3" in str(exc) or "already has" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/tender-packages/{package_id}/bids", response_model=list[TenderBidOut])
async def tender_bids(package_id: UUID, db: AsyncSession = Depends(get_db)) -> list[TenderBidOut]:
    if await tendering.get_tender_package(db, package_id) is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    return [TenderBidOut.model_validate(item) for item in await tendering.list_tender_bids(db, package_id)]


@router.post("/tender-bids/{bid_id}/documents", response_model=TenderBidOut)
async def upload_tender_bid_document(bid_id: UUID, file: Annotated[UploadFile, File()], db: AsyncSession = Depends(get_db)) -> TenderBidOut:
    bid = await tendering.get_tender_bid(db, bid_id)
    if bid is None or bid.status == "cancelled":
        raise HTTPException(status_code=404, detail="Active tender bid not found")
    try:
        return TenderBidOut.model_validate(await tendering.upload_tender_bid_document(db, bid, file))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tender-bid-documents/{document_id}/content")
async def tender_bid_document_content(document_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    document = await db.get(TenderBidDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Tender bid document not found")
    content = await tendering.get_tender_bid_document_content(document)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{document.original_filename}"'})


@router.patch("/tender-bids/{bid_id}", response_model=TenderBidOut)
async def update_tender_bid(bid_id: UUID, data: TenderBidUpdate, db: AsyncSession = Depends(get_db)) -> TenderBidOut:
    bid = await tendering.get_tender_bid(db, bid_id)
    if bid is None or bid.status == "cancelled":
        raise HTTPException(status_code=404, detail="Active tender bid not found")
    return TenderBidOut.model_validate(await tendering.update_tender_bid(db, bid, data))


@router.delete("/tender-bids/{bid_id}", status_code=204)
async def cancel_tender_bid(bid_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    bid = await tendering.get_tender_bid(db, bid_id)
    if bid is None:
        raise HTTPException(status_code=404, detail="Tender bid not found")
    await tendering.cancel_tender_bid(db, bid)
    return Response(status_code=204)


@router.get("/tender-packages/{package_id}/comparison", response_model=TenderComparisonOut)
async def tender_comparison(package_id: UUID, db: AsyncSession = Depends(get_db)) -> TenderComparisonOut:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    bids = await tendering.list_tender_bids(db, package_id)
    bid_models = [TenderBidOut.model_validate(item) for item in bids]
    return TenderComparisonOut(package=TenderPackageOut.model_validate(package), bids=bid_models, bid_count=len(bids), received_count=sum(item.status in {"received", "reviewed"} for item in bids))


@router.post("/tender-packages/{package_id}/award", response_model=TenderAwardOut, status_code=201)
async def award_tender_package(package_id: UUID, data: TenderAwardCreate, db: AsyncSession = Depends(get_db)) -> TenderAwardOut:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    try:
        award, po = await tendering.award_tender_package(db, package, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = TenderAwardOut.model_validate(award)
    return result.model_copy(update={"purchase_order": PurchaseOrderSummary.model_validate(po)})
