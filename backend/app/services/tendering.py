from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.financing import Property
from app.models.tendering import Contractor
from app.models.tendering import ContractorCategory
from app.models.tendering import TenderDocument
from app.models.tendering import TenderDocumentMarkup
from app.models.tendering import TenderPackage
from app.models.tendering import TenderAward, TenderBid, TenderBidDocument
from app.modules.costbook import service as costbook_service
from app.modules.costbook.models import Budget, BudgetLine, PurchaseOrder
from app.modules.costbook.schemas import PurchaseOrderCreate
from app.core.config import settings
from app.schemas.tendering import ContractorCreate
from app.schemas.tendering import ContractorUpdate
from app.schemas.tendering import TenderDocumentType
from app.schemas.tendering import TenderPackageCreate
from app.schemas.tendering import TenderPackageUpdate
from app.schemas.tendering import TenderAwardCreate, TenderBidCreate, TenderBidUpdate
from app.services.document_extractor import extract_tender_quote_document
from app.services.minio_financing import delete_financing_document
from app.services.minio_financing import financing_key
from app.services.minio_financing import get_financing_document
from app.services.minio_financing import upload_financing_document


async def list_categories(db: AsyncSession) -> list[ContractorCategory]:
    return list((await db.execute(select(ContractorCategory).order_by(ContractorCategory.name))).scalars())


async def list_contractors(db: AsyncSession, category_id: UUID | None, active: bool | None) -> list[Contractor]:
    statement = select(Contractor).options(selectinload(Contractor.categories)).order_by(Contractor.name)
    if category_id is not None:
        statement = statement.where(Contractor.categories.any(ContractorCategory.id == category_id))
    if active is not None:
        statement = statement.where(Contractor.active == active)
    return list((await db.execute(statement)).scalars().unique())


async def get_contractor(db: AsyncSession, contractor_id: UUID) -> Contractor | None:
    return (await db.execute(select(Contractor).where(Contractor.id == contractor_id).options(selectinload(Contractor.categories)))).scalar_one_or_none()


async def create_contractor(db: AsyncSession, data: ContractorCreate) -> Contractor:
    categories = await _categories(db, data.category_ids)
    values = data.model_dump(exclude={"category_ids"})
    values["name"] = data.name.strip()
    contractor = Contractor(**_trim_values(values), categories=categories)
    db.add(contractor)
    await db.commit()
    return await get_contractor(db, contractor.id)  # type: ignore[return-value]


async def update_contractor(db: AsyncSession, contractor: Contractor, data: ContractorUpdate) -> Contractor:
    values = data.model_dump(exclude_unset=True, exclude={"category_ids"})
    for field, value in _trim_values(values).items():
        setattr(contractor, field, value)
    if data.category_ids is not None:
        contractor.categories = await _categories(db, data.category_ids)
    await db.commit()
    return await get_contractor(db, contractor.id)  # type: ignore[return-value]


async def deactivate_contractor(db: AsyncSession, contractor: Contractor) -> Contractor:
    contractor.active = False
    await db.commit()
    return await get_contractor(db, contractor.id)  # type: ignore[return-value]


async def list_tender_packages(db: AsyncSession, property_id: UUID) -> list[TenderPackage]:
    return list((await db.execute(_package_query().where(TenderPackage.property_id == property_id).order_by(TenderPackage.created_at.desc()))).scalars().unique())


async def get_tender_package(db: AsyncSession, package_id: UUID) -> TenderPackage | None:
    return (await db.execute(_package_query().where(TenderPackage.id == package_id))).scalars().unique().one_or_none()


async def create_tender_package(db: AsyncSession, property_id: UUID, data: TenderPackageCreate) -> TenderPackage:
    if await db.get(Property, property_id) is None:
        raise ValueError("Property not found")
    if await db.get(ContractorCategory, data.category_id) is None:
        raise ValueError("Contractor category not found")
    package = TenderPackage(property_id=property_id, category_id=data.category_id, scope_description=data.scope_description.strip(), due_date=data.due_date)
    db.add(package)
    await db.commit()
    return await get_tender_package(db, package.id)  # type: ignore[return-value]


async def update_tender_package(db: AsyncSession, package: TenderPackage, data: TenderPackageUpdate) -> TenderPackage:
    values = data.model_dump(exclude_unset=True)
    if "category_id" in values and await db.get(ContractorCategory, values["category_id"]) is None:
        raise ValueError("Contractor category not found")
    if "scope_description" in values:
        values["scope_description"] = values["scope_description"].strip()
    for field, value in values.items():
        setattr(package, field, value)
    await db.commit()
    return await get_tender_package(db, package.id)  # type: ignore[return-value]


async def upload_tender_document(db: AsyncSession, package: TenderPackage, document_type: TenderDocumentType, file: UploadFile) -> TenderDocument:
    filename = file.filename or "document.pdf"
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise ValueError("Tender documents must be PDF files")
    content = await file.read()
    if not content:
        raise ValueError("Uploaded PDF is empty")
    key = financing_key("tendering", f"{package.id}-{uuid4()}-{filename}")
    await asyncio.to_thread(upload_financing_document, key=key, content=content, content_type="application/pdf")
    document = TenderDocument(tender_package_id=package.id, document_type=document_type, file_path=key, original_filename=filename)
    try:
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document
    except Exception:
        await asyncio.to_thread(delete_financing_document, key=key)
        raise


async def list_tender_documents(db: AsyncSession, package_id: UUID) -> list[TenderDocument]:
    return list((await db.execute(select(TenderDocument).where(TenderDocument.tender_package_id == package_id).order_by(TenderDocument.uploaded_at.desc()))).scalars())


async def delete_tender_document(db: AsyncSession, document: TenderDocument) -> None:
    key = document.file_path
    markup_keys = list(
        (
            await db.execute(
                select(TenderDocumentMarkup.flattened_pdf_path).where(
                    TenderDocumentMarkup.tender_document_id == document.id
                )
            )
        ).scalars()
    )
    await db.delete(document)
    await db.commit()
    await asyncio.to_thread(delete_financing_document, key=key)
    for markup_key in markup_keys:
        await asyncio.to_thread(delete_financing_document, key=markup_key)


async def get_tender_document_content(document: TenderDocument) -> bytes:
    return await asyncio.to_thread(get_financing_document, key=document.file_path)


async def _categories(db: AsyncSession, ids: list[UUID]) -> list[ContractorCategory]:
    if not ids:
        return []
    categories = list((await db.execute(select(ContractorCategory).where(ContractorCategory.id.in_(set(ids))))).scalars())
    if len(categories) != len(set(ids)):
        raise ValueError("One or more contractor categories were not found")
    return categories


def _trim_values(values: dict[str, object]) -> dict[str, object]:
    return {key: value.strip() if isinstance(value, str) else value for key, value in values.items()}


def _package_query():
    return select(TenderPackage).options(
        selectinload(TenderPackage.documents),
        selectinload(TenderPackage.category),
        selectinload(TenderPackage.bids).selectinload(TenderBid.documents),
        selectinload(TenderPackage.award),
    )


def _bid_query():
    return select(TenderBid).options(selectinload(TenderBid.documents), selectinload(TenderBid.contractor))


async def list_tender_bids(db: AsyncSession, package_id: UUID, *, include_cancelled: bool = False) -> list[TenderBid]:
    statement = _bid_query().where(TenderBid.tender_package_id == package_id)
    if not include_cancelled:
        statement = statement.where(TenderBid.status != "cancelled")
    return list((await db.execute(statement.order_by(TenderBid.created_at))).scalars().unique())


async def get_tender_bid(db: AsyncSession, bid_id: UUID) -> TenderBid | None:
    return (await db.execute(_bid_query().where(TenderBid.id == bid_id))).scalars().unique().one_or_none()


async def create_tender_bid(db: AsyncSession, package: TenderPackage, data: TenderBidCreate) -> TenderBid:
    active_count = await db.scalar(select(func.count()).select_from(TenderBid).where(TenderBid.tender_package_id == package.id, TenderBid.status != "cancelled"))
    if (active_count or 0) >= 3:
        raise ValueError("A tender package can have at most 3 active bids")
    contractor = await get_contractor(db, data.contractor_id)
    if contractor is None or not contractor.active:
        raise ValueError("Active contractor not found")
    if not any(category.id == package.category_id for category in contractor.categories):
        raise ValueError("Contractor is not assigned to this tender package's trade category")
    existing = (await db.execute(select(TenderBid).where(TenderBid.tender_package_id == package.id, TenderBid.contractor_id == data.contractor_id))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is not None:
        if existing.status != "cancelled":
            raise ValueError("This contractor already has a bid for the tender package")
        existing.status, existing.invited_at = "invited", now
        existing.quote_amount = existing.extracted_amount = None
        existing.extracted_line_items = None
        existing.excluded_scope_notes = existing.reviewer_notes = None
        existing.received_at = None
        bid = existing
    else:
        bid = TenderBid(tender_package_id=package.id, contractor_id=data.contractor_id, status="invited", invited_at=now)
        db.add(bid)
    if package.status == "draft":
        package.status = "sent"
    await db.commit()
    return await get_tender_bid(db, bid.id)  # type: ignore[return-value]


async def cancel_tender_bid(db: AsyncSession, bid: TenderBid) -> None:
    bid.status = "cancelled"
    await db.commit()


async def update_tender_bid(db: AsyncSession, bid: TenderBid, data: TenderBidUpdate) -> TenderBid:
    values = data.model_dump(exclude_unset=True)
    if "extracted_line_items" in values and values["extracted_line_items"] is not None:
        values["extracted_line_items"] = [{"description": item["description"].strip(), "amount": str(item["amount"])} for item in values["extracted_line_items"]]
    for field, value in _trim_values(values).items():
        setattr(bid, field, value)
    if "quote_amount" in values and values["quote_amount"] is not None:
        bid.status = "reviewed"
    await db.commit()
    return await get_tender_bid(db, bid.id)  # type: ignore[return-value]


async def upload_tender_bid_document(db: AsyncSession, bid: TenderBid, file: UploadFile) -> TenderBid:
    filename = file.filename or "quote.pdf"
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise ValueError("Bid quotes must be PDF files")
    content = await file.read()
    if not content:
        raise ValueError("Uploaded PDF is empty")
    key = financing_key("tendering/bids", f"{bid.id}-{uuid4()}-{filename}")
    await asyncio.to_thread(upload_financing_document, key=key, content=content, content_type="application/pdf")
    document = TenderBidDocument(tender_bid_id=bid.id, file_path=key, original_filename=filename)
    db.add(document)
    try:
        extracted = await extract_tender_quote_document(content=content, content_type="application/pdf")
        bid.extracted_amount = _decimal_or_none(extracted.get("total"))
        bid.extracted_line_items = _normalise_line_items(extracted.get("line_items"))
        exclusions = extracted.get("exclusions")
        bid.excluded_scope_notes = exclusions.strip() if isinstance(exclusions, str) and exclusions.strip() else None
        bid.status = "received"
        bid.received_at = datetime.now(timezone.utc)
        package = await db.get(TenderPackage, bid.tender_package_id)
        if package is not None and package.status in {"draft", "sent"}:
            package.status = "bids_in"
        await db.commit()
    except Exception:
        await db.rollback()
        await asyncio.to_thread(delete_financing_document, key=key)
        raise
    return await get_tender_bid(db, bid.id)  # type: ignore[return-value]


async def get_tender_bid_document_content(document: TenderBidDocument) -> bytes:
    return await asyncio.to_thread(get_financing_document, key=document.file_path)


async def award_tender_package(db: AsyncSession, package: TenderPackage, data: TenderAwardCreate) -> tuple[TenderAward, PurchaseOrder]:
    if package.award is not None:
        raise ValueError("This tender package has already been awarded")
    bid = await get_tender_bid(db, data.winning_bid_id)
    if bid is None or bid.tender_package_id != package.id or bid.status != "reviewed" or bid.quote_amount is None:
        raise ValueError("Winning bid must be a reviewed bid from this tender package")
    budget = await db.get(Budget, data.budget_id)
    line = await db.get(BudgetLine, data.budget_line_id)
    if budget is None:
        raise ValueError("Budget not found")
    if line is None or line.budget_id != budget.id:
        raise ValueError("Budget line does not belong to the selected budget")
    po = await costbook_service.create_purchase_order(db, settings.default_org_id, budget.id, PurchaseOrderCreate(
        budget_line_id=line.id,
        vendor_name_adhoc=bid.contractor.name,
        description=package.scope_description,
        amount=bid.quote_amount,
        notes=data.award_instructions.strip(),
    ))
    award = TenderAward(
        tender_package_id=package.id, winning_bid_id=bid.id, po_id=po.id,
        award_instructions=data.award_instructions.strip(), project_start_date=data.project_start_date,
        contractor_start_date=data.contractor_start_date,
    )
    db.add(award)
    package.status = "awarded"
    await db.commit()
    await db.refresh(award)
    return award, po


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _normalise_line_items(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or not str(item.get("description", "")).strip():
            continue
        amount = _decimal_or_none(item.get("amount"))
        if amount is not None:
            result.append({"description": str(item["description"]).strip(), "amount": str(amount)})
    return result
