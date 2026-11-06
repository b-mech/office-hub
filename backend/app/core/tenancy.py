"""Central tenant resolution and project/land access checks.

An org is a tenant. A *project* is a ``core.lots`` row whose org is derived
from ``lots.development_id -> core.developments.org_id``; there is no projects
table. Every tenant-aware route resolves a :class:`TenantContext` first and then
asks this module whether the actor may see or change an object.

Rules (release 1):

* The actor is the authenticated ``request.state.user``. When
  ``AUTH_ENFORCED`` is true and there is no user the request fails with 401.
  When ``AUTH_ENFORCED`` is explicitly false (dev/test and today's single-user
  install) an anonymous request is attributed to the legacy fallback actor: the
  oldest active admin of the default org. The fallback is pinned to the default
  org; ``X-OfficeHub-Org`` can never widen it, so the header is never a form of
  authentication.
* ``X-OfficeHub-Org`` (or the ``org`` query parameter for plain browser
  downloads) only *selects* an org. The actor must hold a membership in it, or
  be a superadmin. Without a selection the actor's home org is used when they
  belong to it, otherwise their oldest membership.
* Objects outside the selected org are invisible (404), including for
  superadmins, who must select the other org explicitly.
* Inside the org: superadmin and ``tenant_admin`` are owners. Plain members get
  editor (viewer for ``users.role = readonly``) on every project when the org's
  ``member_project_scope`` is ``org`` (Connection Homes); with ``assigned``
  (Potterstone) they need a ``core.project_members`` row.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from uuid import UUID

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.core import Development
from app.models.core import Lot
from app.models.core import Org
from app.models.core import OrgProjectScope
from app.models.core import ProjectMember
from app.models.core import ProjectRole
from app.models.core import User
from app.models.core import UserOrgMembership
from app.models.core import UserOrgRole
from app.models.core import UserRole


logger = logging.getLogger(__name__)

ORG_HEADER = "X-OfficeHub-Org"
ORG_QUERY_PARAM = "org"
ROLE_RANK = {ProjectRole.VIEWER: 1, ProjectRole.EDITOR: 2, ProjectRole.OWNER: 3}


@dataclass
class TenantContext:
    user: User
    org: Org
    membership_role: UserOrgRole | None
    is_superadmin: bool
    is_fallback: bool
    explicit_org: bool
    _project_roles: dict[UUID, ProjectRole | None] = field(default_factory=dict, repr=False)

    @property
    def org_id(self) -> UUID:
        return self.org.id

    @property
    def is_org_admin(self) -> bool:
        return self.is_superadmin or self.membership_role == UserOrgRole.TENANT_ADMIN

    @property
    def is_readonly(self) -> bool:
        return self.user.role == UserRole.READONLY

    @property
    def org_wide_projects(self) -> bool:
        """True when the actor may see every project of the org without a grant."""
        return self.is_org_admin or _scope(self.org) == OrgProjectScope.ORG

    @property
    def org_wide_role(self) -> ProjectRole | None:
        if self.is_org_admin:
            return ProjectRole.VIEWER if self.is_readonly else ProjectRole.OWNER
        if _scope(self.org) == OrgProjectScope.ORG:
            return ProjectRole.VIEWER if self.is_readonly else ProjectRole.EDITOR
        return None

    @property
    def can_access_land(self) -> bool:
        return bool(self.org.land_enabled) and self.org_wide_projects

    @property
    def can_manage_clients(self) -> bool:
        return self.org_wide_projects and not self.is_readonly

    @property
    def is_legacy_org(self) -> bool:
        return self.org.id == settings.default_org_id

    @property
    def can_access_rentals(self) -> bool:
        """Rental tables are not org-owned yet; they stay with the legacy default org."""
        if not self.is_legacy_org:
            return False
        if self.is_superadmin or self.user.role == UserRole.ADMIN:
            return True
        return (self.user.permissions or {}).get("rentals") in {"viewer", "editor"}


def _scope(org: Org) -> OrgProjectScope:
    value = getattr(org, "member_project_scope", None) or OrgProjectScope.ASSIGNED
    return OrgProjectScope(value)


async def fallback_actor(db: AsyncSession) -> User | None:
    """Legacy single-user actor used only when AUTH_ENFORCED is false."""
    return await db.scalar(
        select(User)
        .where(
            User.is_active.is_(True),
            User.role == UserRole.ADMIN,
            User.org_id == settings.default_org_id,
        )
        .order_by(User.created_at, User.id)
        .limit(1)
    )


async def resolve_actor(request: Request, db: AsyncSession) -> tuple[User, bool]:
    user: User | None = getattr(request.state, "user", None)
    if user is not None:
        return user, False
    if settings.auth_enforced:
        raise HTTPException(status_code=401, detail="Office Hub sign-in is required")
    fallback = await fallback_actor(db)
    if fallback is None:
        raise HTTPException(status_code=401, detail="Office Hub sign-in is required")
    return fallback, True


def _selected_org(request: Request) -> str | None:
    selected = (request.headers.get(ORG_HEADER) or "").strip()
    if not selected and request.method in {"GET", "HEAD"}:
        selected = (request.query_params.get(ORG_QUERY_PARAM) or "").strip()
    return selected or None


async def _find_org(db: AsyncSession, selected: str) -> Org | None:
    try:
        selected_id = UUID(selected)
    except ValueError:
        return await db.scalar(select(Org).where(Org.slug == selected))
    return await db.get(Org, selected_id)


async def user_org_ids(user: User, db: AsyncSession) -> set[UUID]:
    """Return explicit org memberships; the legacy home org is not an implicit grant."""
    result = await db.scalars(
        select(UserOrgMembership.org_id).where(UserOrgMembership.user_id == user.id)
    )
    return set(result.all())


async def _membership(db: AsyncSession, user: User, org_id: UUID) -> UserOrgMembership | None:
    return await db.scalar(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == user.id,
            UserOrgMembership.org_id == org_id,
        )
    )


async def has_org_access(user: User, org_id: UUID, db: AsyncSession) -> bool:
    if user.is_superadmin:
        return True
    return org_id in await user_org_ids(user, db)


async def resolve_tenant(request: Request, db: AsyncSession) -> TenantContext:
    cached = getattr(request.state, "tenant", None)
    if isinstance(cached, TenantContext):
        return cached
    user, is_fallback = await resolve_actor(request, db)
    selected = _selected_org(request)

    if is_fallback:
        org = await db.get(Org, settings.default_org_id)
        if org is None:
            raise HTTPException(status_code=401, detail="Office Hub sign-in is required")
        if selected is not None:
            chosen = await _find_org(db, selected)
            if chosen is None or chosen.id != org.id:
                raise HTTPException(status_code=401, detail="Sign in to select another organization")
        membership = await _membership(db, user, org.id)
        role = membership.role if membership else UserOrgRole.TENANT_ADMIN
        context = TenantContext(user=user, org=org, membership_role=UserOrgRole(role),
                                is_superadmin=False, is_fallback=True, explicit_org=False)
        request.state.tenant = context
        return context

    if selected is not None:
        org = await _find_org(db, selected)
        if org is None:
            raise HTTPException(status_code=404, detail="Org not found")
    else:
        org = None
        if await _membership(db, user, user.org_id) is not None or user.is_superadmin:
            org = await db.get(Org, user.org_id)
        if org is None:
            first = await db.scalar(
                select(UserOrgMembership)
                .where(UserOrgMembership.user_id == user.id)
                .order_by(UserOrgMembership.created_at, UserOrgMembership.id)
                .limit(1)
            )
            if first is not None:
                org = await db.get(Org, first.org_id)
        if org is None:
            logger.warning("tenant denied: user=%s has no org membership", user.id)
            raise HTTPException(status_code=403, detail="No organization membership")

    membership = await _membership(db, user, org.id)
    if membership is None and not user.is_superadmin:
        logger.warning("tenant denied: user=%s org=%s", user.id, org.id)
        raise HTTPException(status_code=403, detail="Org access denied")
    context = TenantContext(
        user=user,
        org=org,
        membership_role=UserOrgRole(membership.role) if membership else None,
        is_superadmin=bool(user.is_superadmin),
        is_fallback=False,
        explicit_org=selected is not None,
    )
    request.state.tenant = context
    return context


async def resolve_current_org(request: Request, db: AsyncSession) -> Org:
    return (await resolve_tenant(request, db)).org


async def get_tenant(request: Request, db: AsyncSession = Depends(get_db)) -> TenantContext:
    return await resolve_tenant(request, db)


async def lot_org_id(db: AsyncSession, lot_id: UUID) -> UUID | None:
    return await db.scalar(
        select(Development.org_id)
        .join(Lot, Lot.development_id == Development.id)
        .where(Lot.id == lot_id)
    )


async def project_role(ctx: TenantContext, lot_id: UUID, db: AsyncSession) -> ProjectRole | None:
    """Effective role of the actor on a lot inside the selected org, or None."""
    if lot_id in ctx._project_roles:
        return ctx._project_roles[lot_id]
    role: ProjectRole | None = None
    org_id = await lot_org_id(db, lot_id)
    if org_id is not None and org_id == ctx.org_id:
        role = ctx.org_wide_role
        if role is None:
            member = await db.scalar(
                select(ProjectMember).where(
                    ProjectMember.user_id == ctx.user.id, ProjectMember.lot_id == lot_id
                )
            )
            if member is not None:
                role = ProjectRole(member.role)
                if ctx.is_readonly:
                    role = ProjectRole.VIEWER
    ctx._project_roles[lot_id] = role
    return role


def _deny(ctx: TenantContext, object_id: UUID, status_code: int, detail: str) -> HTTPException:
    logger.warning("tenant denied: user=%s org=%s object=%s", ctx.user.id, ctx.org_id, object_id)
    return HTTPException(status_code=status_code, detail=detail)


async def require_lot_role(
    ctx: TenantContext,
    lot_id: UUID,
    min_role: ProjectRole,
    db: AsyncSession,
    *,
    not_found: str = "Project not found",
) -> ProjectRole:
    role = await project_role(ctx, lot_id, db)
    if role is None:
        raise _deny(ctx, lot_id, 404, not_found)
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise _deny(ctx, lot_id, 403, "Project access denied")
    return role


def require_land(ctx: TenantContext) -> None:
    if not ctx.can_access_land:
        raise HTTPException(status_code=403, detail="Land is not available for this organization")


def require_rentals(ctx: TenantContext) -> None:
    if not ctx.can_access_rentals:
        raise HTTPException(status_code=403, detail="Rentals are not available for this organization")


def lot_scope_sql(ctx: TenantContext, alias: str = "l", dev_alias: str = "d") -> tuple[str, dict[str, object]]:
    """SQL predicate limiting lots to the actor's accessible projects in the org.

    Callers must join ``core.developments {dev_alias}`` on ``{alias}.development_id``.
    """
    params: dict[str, object] = {"tenant_org_id": str(ctx.org_id)}
    predicate = f"{dev_alias}.org_id = CAST(:tenant_org_id AS uuid)"
    if not ctx.org_wide_projects:
        params["tenant_user_id"] = str(ctx.user.id)
        predicate += (
            f" AND EXISTS (SELECT 1 FROM core.project_members tpm"
            f" WHERE tpm.lot_id = {alias}.id AND tpm.user_id = CAST(:tenant_user_id AS uuid))"
        )
    return predicate, params


async def require_project_access(
    user: User, lot_id: UUID, min_role: ProjectRole, db: AsyncSession
) -> None:
    """Back-compat helper (spike API): check a lot against the lot's own org.

    New routes should use :func:`resolve_tenant` + :func:`require_lot_role`.
    """
    if user.is_superadmin:
        return
    org_id = await lot_org_id(db, lot_id)
    if org_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = await _membership(db, user, org_id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Project access denied")
    if membership.role == UserOrgRole.TENANT_ADMIN:
        return
    org = await db.get(Org, org_id)
    if org is not None and _scope(org) == OrgProjectScope.ORG:
        if min_role == ProjectRole.VIEWER or user.role != UserRole.READONLY:
            return
        raise HTTPException(status_code=403, detail="Project access denied")
    project_member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.user_id == user.id, ProjectMember.lot_id == lot_id
        )
    )
    if project_member is None or ROLE_RANK[ProjectRole(project_member.role)] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="Project access denied")
