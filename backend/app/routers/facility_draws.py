from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.tenancy import TenantContext, get_tenant
from app.schemas.facility_draws import FacilityDrawCreate, FacilityDrawHistory, FacilityDrawImportOut, FacilityDrawDeleteOut
from app.services import facility_draws

router = APIRouter(prefix="/facilities", tags=["financing"])
DrawBatch = Annotated[list[FacilityDrawCreate], Field(min_length=1, max_length=1000)]


def require_access(tenant: TenantContext, *, write=False):
    # Financing tables are legacy/org-less: do not expose them to another org.
    if not tenant.is_legacy_org:
        raise HTTPException(403, "Financing is available only in the Connection Homes organization")
    if write and tenant.is_readonly:
        raise HTTPException(403, "Readonly users cannot modify draw history")


@router.get("/{facility_id}/draws", response_model=FacilityDrawHistory)
async def get_draws(facility_id: UUID, db: AsyncSession = Depends(get_db), tenant: TenantContext = Depends(get_tenant)):
    require_access(tenant)
    return await facility_draws.get_history(db, facility_id)


@router.post("/{facility_id}/draws", response_model=FacilityDrawImportOut)
async def post_draws(facility_id: UUID, data: FacilityDrawCreate | DrawBatch, db: AsyncSession = Depends(get_db), tenant: TenantContext = Depends(get_tenant)):
    require_access(tenant, write=True)
    return await facility_draws.create_history(db, facility_id, data if isinstance(data, list) else [data])


@router.delete("/{facility_id}/draws/{txn_id}", response_model=FacilityDrawDeleteOut)
async def delete_draw(facility_id: UUID, txn_id: UUID, db: AsyncSession = Depends(get_db), tenant: TenantContext = Depends(get_tenant)):
    require_access(tenant, write=True)
    return await facility_draws.delete_history(db, facility_id, txn_id)
