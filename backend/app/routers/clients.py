from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import TenantContext
from app.core.tenancy import get_tenant
from app.schemas.clients import ClientCreate
from app.schemas.clients import ClientDetail
from app.schemas.clients import ClientList
from app.schemas.clients import ClientStageValue
from app.schemas.clients import ClientUpdate
from app.schemas.clients import ContactSummary
from app.schemas.clients import ProjectClientUpdate
from app.services import clients as client_service


router = APIRouter(prefix="/api/v1/clients", tags=["clients"])
project_client_router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
Tenant = Annotated[TenantContext, Depends(get_tenant)]


@router.get("", response_model=ClientList)
async def list_clients(
    ctx: Tenant,
    q: str | None = Query(default=None, max_length=200),
    stage: ClientStageValue | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ClientList:
    return await client_service.list_clients(db, ctx, q=q, stage=stage, limit=limit, offset=offset)


@router.post("", response_model=ClientDetail, status_code=201)
async def create_client(data: ClientCreate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> ClientDetail:
    client = await client_service.create_client(db, ctx, data)
    return await client_service.client_detail(db, ctx, client)


@router.get("/contact-options", response_model=list[ContactSummary])
async def contact_options(
    ctx: Tenant, q: str | None = Query(default=None, max_length=200), db: AsyncSession = Depends(get_db)
) -> list[ContactSummary]:
    return await client_service.contact_options(db, ctx, q)


@router.get("/{client_id}", response_model=ClientDetail)
async def client_detail(client_id: UUID, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> ClientDetail:
    client = await client_service.get_visible_client(db, ctx, client_id)
    return await client_service.client_detail(db, ctx, client)


@router.patch("/{client_id}", response_model=ClientDetail)
async def update_client(client_id: UUID, data: ClientUpdate, ctx: Tenant, db: AsyncSession = Depends(get_db)) -> ClientDetail:
    client = await client_service.get_visible_client(db, ctx, client_id)
    client = await client_service.update_client(db, ctx, client, data)
    return await client_service.client_detail(db, ctx, client)


@project_client_router.put("/{lot_id}/client", response_model=ProjectClientUpdate)
async def set_project_client(
    lot_id: UUID, data: ProjectClientUpdate, ctx: Tenant, db: AsyncSession = Depends(get_db)
) -> ProjectClientUpdate:
    lot = await client_service.set_project_client(db, ctx, lot_id, data.client_id)
    return ProjectClientUpdate(client_id=lot.client_id)
