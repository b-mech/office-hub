from __future__ import annotations

import asyncio
from uuid import UUID
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.financing import Property
from app.models.tendering import Contractor
from app.models.tendering import ContractorCategory
from app.models.tendering import TenderDocument
from app.models.tendering import TenderPackage
from app.schemas.tendering import ContractorCreate
from app.schemas.tendering import ContractorUpdate
from app.schemas.tendering import TenderDocumentType
from app.schemas.tendering import TenderPackageCreate
from app.schemas.tendering import TenderPackageUpdate
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
    await db.delete(document)
    await db.commit()
    await asyncio.to_thread(delete_financing_document, key=key)


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
    return select(TenderPackage).options(selectinload(TenderPackage.documents), selectinload(TenderPackage.category))
