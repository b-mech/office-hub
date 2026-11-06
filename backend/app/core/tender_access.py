"""Resolve tender objects to their owning project lot and enforce tenant access.

Chain: tender object -> tender package -> ``core.properties`` -> ``core.lots``
(``lots.property_id`` is unique) -> development org. A package whose property is
not linked to a lot has no tenant owner and is refused for everyone (fail
closed); it is never served as a global object.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.core.tenancy import require_lot_role
from app.models.core import Lot
from app.models.core import ProjectRole
from app.models.tendering import TenderBid
from app.models.tendering import TenderBidDocument
from app.models.tendering import TenderDocument
from app.models.tendering import TenderDocumentMarkup
from app.models.tendering import TenderPackage
from app.services import tendering


async def lot_id_for_property(db: AsyncSession, property_id: UUID) -> UUID | None:
    return await db.scalar(select(Lot.id).where(Lot.property_id == property_id))


async def require_property(
    ctx: TenantContext, property_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> UUID:
    lot_id = await lot_id_for_property(db, property_id)
    if lot_id is None:
        raise HTTPException(status_code=404, detail="Property not found")
    await require_lot_role(ctx, lot_id, min_role, db, not_found="Property not found")
    return lot_id


async def require_package(
    ctx: TenantContext, package_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> TenderPackage:
    package = await tendering.get_tender_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    lot_id = await lot_id_for_property(db, package.property_id)
    if lot_id is None:
        raise HTTPException(status_code=404, detail="Tender package not found")
    await require_lot_role(ctx, lot_id, min_role, db, not_found="Tender package not found")
    return package


async def _require_package_id(
    ctx: TenantContext, package_id: UUID, min_role: ProjectRole, db: AsyncSession, not_found: str
) -> None:
    property_id = await db.scalar(select(TenderPackage.property_id).where(TenderPackage.id == package_id))
    lot_id = await lot_id_for_property(db, property_id) if property_id is not None else None
    if lot_id is None:
        raise HTTPException(status_code=404, detail=not_found)
    await require_lot_role(ctx, lot_id, min_role, db, not_found=not_found)


async def require_document(
    ctx: TenantContext, document_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> TenderDocument:
    document = await db.get(TenderDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Tender document not found")
    await _require_package_id(ctx, document.tender_package_id, min_role, db, "Tender document not found")
    return document


async def require_markup(
    ctx: TenantContext, markup_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> TenderDocumentMarkup:
    markup = await db.get(TenderDocumentMarkup, markup_id)
    if markup is None:
        raise HTTPException(status_code=404, detail="Tender document markup not found")
    package_id = await db.scalar(
        select(TenderDocument.tender_package_id).where(TenderDocument.id == markup.tender_document_id)
    )
    if package_id is None:
        raise HTTPException(status_code=404, detail="Tender document markup not found")
    await _require_package_id(ctx, package_id, min_role, db, "Tender document markup not found")
    return markup


async def require_bid(
    ctx: TenantContext, bid_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> TenderBid | None:
    bid = await tendering.get_tender_bid(db, bid_id)
    if bid is None:
        return None
    await _require_package_id(ctx, bid.tender_package_id, min_role, db, "Tender bid not found")
    return bid


async def require_bid_document(
    ctx: TenantContext, document_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> TenderBidDocument:
    document = await db.get(TenderBidDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Tender bid document not found")
    package_id = await db.scalar(
        select(TenderBid.tender_package_id).where(TenderBid.id == document.tender_bid_id)
    )
    if package_id is None:
        raise HTTPException(status_code=404, detail="Tender bid document not found")
    await _require_package_id(ctx, package_id, min_role, db, "Tender bid document not found")
    return document
