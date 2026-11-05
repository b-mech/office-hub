"""Tenant access helpers for incremental router adoption.

An org is a tenant. Project access is tied to lots, whose org is inherited
from their development. Call these helpers before tenant-scoped reads/writes.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import current_user
from app.models.core import Development
from app.models.core import Lot
from app.models.core import Org
from app.models.core import ProjectMember
from app.models.core import ProjectRole
from app.models.core import User
from app.models.core import UserOrgMembership
from app.models.core import UserOrgRole


async def user_org_ids(user: User, db: AsyncSession) -> set[UUID]:
    """Return explicit org memberships; the legacy home org is not an implicit grant."""
    result = await db.scalars(
        select(UserOrgMembership.org_id).where(UserOrgMembership.user_id == user.id)
    )
    return set(result.all())


async def has_org_access(user: User, org_id: UUID, db: AsyncSession) -> bool:
    if user.is_superadmin:
        return True
    return org_id in await user_org_ids(user, db)


async def resolve_current_org(request: Request, db: AsyncSession) -> Org:
    """Resolve the selected slug/UUID, or the authenticated user's home org."""
    user = current_user(request)
    selected = request.headers.get("X-OfficeHub-Org")
    if selected:
        try:
            selected_id = UUID(selected)
        except ValueError:
            org = await db.scalar(select(Org).where(Org.slug == selected))
        else:
            org = await db.get(Org, selected_id)
    else:
        org = await db.get(Org, user.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    if not await has_org_access(user, org.id, db):
        raise HTTPException(status_code=403, detail="Org access denied")
    return org


async def require_project_access(
    user: User, lot_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> None:
    """Require org membership and a project grant, unless tenant admin or superadmin."""
    if user.is_superadmin:
        return
    org_id = await db.scalar(
        select(Development.org_id)
        .join(Lot, Lot.development_id == Development.id)
        .where(Lot.id == lot_id)
    )
    if org_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = await db.scalar(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == user.id,
            UserOrgMembership.org_id == org_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Project access denied")
    if membership.role == UserOrgRole.TENANT_ADMIN:
        return
    project_member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.user_id == user.id, ProjectMember.lot_id == lot_id
        )
    )
    rank = {ProjectRole.VIEWER: 1, ProjectRole.EDITOR: 2, ProjectRole.OWNER: 3}
    if project_member is None or rank[project_member.role] < rank[min_role]:
        raise HTTPException(status_code=403, detail="Project access denied")
