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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core import tender_access as access
from app.core.tenancy import TenantContext
from app.core.tenancy import get_tenant
from app.models.core import ProjectRole
from app.modules.costbook.models import Budget
from app.schemas.tendering import CategoryOut
from app.schemas.tendering import ContractorCreate
from app.schemas.tendering import ContractorOut
from app.schemas.tendering import ContractorUpdate
from app.schemas.tendering import TenderDocumentOut
from app.schemas.tendering import TenderDocumentType
from app.schemas.tendering import TenderDocumentMarkupCreate
from app.schemas.tendering import TenderDocumentMarkupOut
from app.schemas.tendering import TenderDocumentMarkupSummary
from app.schemas.tendering import TenderPackageCreate
from app.schemas.tendering import TenderPackageOut
from app.schemas.tendering import TenderPackageUpdate
from app.schemas.tendering import TenderAwardCreate, TenderAwardOut, TenderBidCreate, TenderBidOut, TenderBidUpdate, TenderComparisonOut, PurchaseOrderSummary
from app.services import tendering
from app.services import tender_markups


router = APIRouter(prefix="/api", tags=["tendering"])
VIEW = ProjectRole.VIEWER
EDIT = ProjectRole.EDITOR
Tenant = Annotated[TenantContext, Depends(get_tenant)]


def _require_contractor_directory(ctx: TenantContext) -> None:
    """Contractors have no org_id yet; the directory stays with the legacy org."""
    if not (ctx.is_legacy_org and (ctx.org_wide_projects or ctx.is_superadmin)):
        raise HTTPException(status_code=403, detail="The contractor directory is not available for this organization")


@router.get("/contractor-categories", response_model=list[CategoryOut])
async def contractor_categories(ctx: Tenant, db: AsyncSession = Depends(get_db)) -> list[CategoryOut]:
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
async def property_tender_packages(property_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> list[TenderPackageOut]:
    await access.require_property(ctx, property_id, VIEW, db)
    return [TenderPackageOut.model_validate(item) for item in await tendering.list_tender_packages(db, property_id)]


@router.post("/properties/{property_id}/tender-packages", response_model=TenderPackageOut, status_code=201)
async def create_tender_package(property_id: UUID, data: TenderPackageCreate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderPackageOut:
    await access.require_property(ctx, property_id, EDIT, db)
    try:
        return TenderPackageOut.model_validate(await tendering.create_tender_package(db, property_id, data))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tender-packages/{package_id}", response_model=TenderPackageOut)
async def tender_package_detail(package_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderPackageOut:
    package = await access.require_package(ctx, package_id, VIEW, db)
    return TenderPackageOut.model_validate(package)


@router.patch("/tender-packages/{package_id}", response_model=TenderPackageOut)
async def update_tender_package(package_id: UUID, data: TenderPackageUpdate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderPackageOut:
    package = await access.require_package(ctx, package_id, EDIT, db)
    try:
        return TenderPackageOut.model_validate(await tendering.update_tender_package(db, package, data))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tender-packages/{package_id}/documents", response_model=TenderDocumentOut, status_code=201)
async def upload_tender_document(
    package_id: UUID,
    document_type: Annotated[TenderDocumentType, Form()],
    file: Annotated[UploadFile, File()],
    ctx: Tenant,
    db: AsyncSession = Depends(get_db),
) -> TenderDocumentOut:
    package = await access.require_package(ctx, package_id, EDIT, db)
    try:
        return TenderDocumentOut.model_validate(await tendering.upload_tender_document(db, package, document_type, file))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tender-packages/{package_id}/documents", response_model=list[TenderDocumentOut])
async def tender_documents(package_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> list[TenderDocumentOut]:
    await access.require_package(ctx, package_id, VIEW, db)
    return [TenderDocumentOut.model_validate(item) for item in await tendering.list_tender_documents(db, package_id)]


@router.get("/tender-documents/{document_id}/content")
async def tender_document_content(document_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> Response:
    document = await access.require_document(ctx, document_id, VIEW, db)
    content = await tendering.get_tender_document_content(document)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{document.original_filename}"'})


@router.delete("/tender-documents/{document_id}", status_code=204)
async def delete_tender_document(document_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> Response:
    document = await access.require_document(ctx, document_id, EDIT, db)
    await tendering.delete_tender_document(db, document)
    return Response(status_code=204)


@router.post(
    "/tender-documents/{document_id}/markups",
    response_model=TenderDocumentMarkupOut,
    status_code=201,
)
async def create_tender_document_markup(
    document_id: UUID,
    data: TenderDocumentMarkupCreate,
    ctx: Tenant,
    db: AsyncSession = Depends(get_db),
) -> TenderDocumentMarkupOut:
    document = await access.require_document(ctx, document_id, EDIT, db)
    try:
        return TenderDocumentMarkupOut.model_validate(
            await tender_markups.create_markup(db, document, data)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/tender-documents/{document_id}/markups",
    response_model=list[TenderDocumentMarkupSummary],
)
async def tender_document_markups(
    document_id: UUID,
    ctx: Tenant,
    db: AsyncSession = Depends(get_db),
) -> list[TenderDocumentMarkupSummary]:
    await access.require_document(ctx, document_id, VIEW, db)
    return [
        TenderDocumentMarkupSummary.model_validate(item)
        for item in await tender_markups.list_markups(db, document_id)
    ]


@router.get(
    "/tender-document-markups/{markup_id}",
    response_model=TenderDocumentMarkupOut,
)
async def tender_document_markup(
    markup_id: UUID,
    ctx: Tenant,
    db: AsyncSession = Depends(get_db),
) -> TenderDocumentMarkupOut:
    markup = await access.require_markup(ctx, markup_id, VIEW, db)
    return TenderDocumentMarkupOut.model_validate(markup)


@router.get("/tender-document-markups/{markup_id}/flattened")
async def tender_document_markup_flattened(
    markup_id: UUID,
    ctx: Tenant,
    db: AsyncSession = Depends(get_db),
) -> Response:
    markup = await access.require_markup(ctx, markup_id, VIEW, db)
    content = await tender_markups.get_flattened_pdf(markup)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="tender-markup-v{markup.version_number}.pdf"'},
    )


@router.post("/tender-packages/{package_id}/bids", response_model=TenderBidOut, status_code=201)
async def create_tender_bid(package_id: UUID, data: TenderBidCreate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderBidOut:
    package = await access.require_package(ctx, package_id, EDIT, db)
    _require_contractor_directory(ctx)
    try:
        return TenderBidOut.model_validate(await tendering.create_tender_bid(db, package, data))
    except ValueError as exc:
        status_code = 409 if "at most 3" in str(exc) or "already has" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/tender-packages/{package_id}/bids", response_model=list[TenderBidOut])
async def tender_bids(package_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> list[TenderBidOut]:
    await access.require_package(ctx, package_id, VIEW, db)
    return [TenderBidOut.model_validate(item) for item in await tendering.list_tender_bids(db, package_id)]


@router.post("/tender-bids/{bid_id}/documents", response_model=TenderBidOut)
async def upload_tender_bid_document(bid_id: UUID, file: Annotated[UploadFile, File()], ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderBidOut:
    bid = await access.require_bid(ctx, bid_id, EDIT, db)
    if bid is None or bid.status == "cancelled":
        raise HTTPException(status_code=404, detail="Active tender bid not found")
    try:
        return TenderBidOut.model_validate(await tendering.upload_tender_bid_document(db, bid, file))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tender-bid-documents/{document_id}/content")
async def tender_bid_document_content(document_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> Response:
    document = await access.require_bid_document(ctx, document_id, VIEW, db)
    content = await tendering.get_tender_bid_document_content(document)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{document.original_filename}"'})


@router.patch("/tender-bids/{bid_id}", response_model=TenderBidOut)
async def update_tender_bid(bid_id: UUID, data: TenderBidUpdate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderBidOut:
    bid = await access.require_bid(ctx, bid_id, EDIT, db)
    if bid is None or bid.status == "cancelled":
        raise HTTPException(status_code=404, detail="Active tender bid not found")
    return TenderBidOut.model_validate(await tendering.update_tender_bid(db, bid, data))


@router.delete("/tender-bids/{bid_id}", status_code=204)
async def cancel_tender_bid(bid_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> Response:
    bid = await access.require_bid(ctx, bid_id, EDIT, db)
    if bid is None:
        raise HTTPException(status_code=404, detail="Tender bid not found")
    await tendering.cancel_tender_bid(db, bid)
    return Response(status_code=204)


@router.get("/tender-packages/{package_id}/comparison", response_model=TenderComparisonOut)
async def tender_comparison(package_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderComparisonOut:
    package = await access.require_package(ctx, package_id, VIEW, db)
    bids = await tendering.list_tender_bids(db, package_id)
    bid_models = [TenderBidOut.model_validate(item) for item in bids]
    return TenderComparisonOut(package=TenderPackageOut.model_validate(package), bids=bid_models, bid_count=len(bids), received_count=sum(item.status in {"received", "reviewed"} for item in bids))


@router.post("/tender-packages/{package_id}/award", response_model=TenderAwardOut, status_code=201)
async def award_tender_package(package_id: UUID, data: TenderAwardCreate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> TenderAwardOut:
    package = await access.require_package(ctx, package_id, EDIT, db)
    if not ctx.is_legacy_org:
        # Costbook purchase orders are still written to the legacy org.
        raise HTTPException(status_code=403, detail="Costbook awards are not available for this organization")
    budget_org = await db.scalar(select(Budget.org_id).where(Budget.id == data.budget_id))
    if budget_org is not None and budget_org != ctx.org_id:
        raise HTTPException(status_code=422, detail="Budget not found")
    try:
        award, po = await tendering.award_tender_package(db, package, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = TenderAwardOut.model_validate(award)
    return result.model_copy(update={"purchase_order": PurchaseOrderSummary.model_validate(po)})
