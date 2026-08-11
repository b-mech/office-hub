from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.core import Development
from app.models.core import DevelopmentType
from app.services.developments import DevelopmentService


router = APIRouter(prefix="/api/v1/developments", tags=["developments"])


class DevelopmentCreate(BaseModel):
    name: str = Field(min_length=1)
    development_type: DevelopmentType
    parent_id: UUID | None = None
    municipality: str | None = None
    province: str | None = None
    developer_contact_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DevelopmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    development_type: DevelopmentType | None = None
    parent_id: UUID | None = None
    municipality: str | None = None
    province: str | None = None
    metadata: dict[str, Any] | None = None


def _serialize(development: Development, full_path: str) -> dict[str, Any]:
    return {
        "id": development.id,
        "name": development.name,
        "name_normalized": development.name_normalized,
        "development_type": development.development_type.value,
        "parent_id": development.parent_id,
        "full_path": full_path,
        "municipality": development.municipality,
        "province": development.province,
        "developer_contact_id": development.developer_contact_id,
        "metadata": development.metadata_,
    }


async def _serialize_one(service: DevelopmentService, development: Development) -> dict[str, Any]:
    rows = await service.list_with_paths(development.org_id)
    paths = {row.id: path for row, path in rows}
    return _serialize(development, paths[development.id])


@router.get("")
async def list_developments(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    service = DevelopmentService(db)
    rows = await service.list_with_paths(settings.default_org_id)
    return [_serialize(development, full_path) for development, full_path in rows]


@router.post("", status_code=201)
async def create_development(
    body: DevelopmentCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = DevelopmentService(db)
    try:
        development = await service.create(
            org_id=settings.default_org_id,
            name=body.name,
            development_type=body.development_type,
            parent_id=body.parent_id,
            municipality=body.municipality,
            province=body.province,
            developer_contact_id=body.developer_contact_id,
            metadata=body.metadata,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _serialize_one(service, development)


@router.patch("/{development_id}")
async def update_development(
    development_id: UUID,
    body: DevelopmentUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = DevelopmentService(db)
    fields_set = body.model_fields_set
    try:
        development = await service.update(
            development_id,
            name=body.name,
            development_type=body.development_type,
            parent_id=body.parent_id,
            parent_supplied="parent_id" in fields_set,
            municipality=body.municipality,
            province=body.province,
            metadata=body.metadata,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        status_code = 404 if str(exc) == "Development not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return await _serialize_one(service, development)
