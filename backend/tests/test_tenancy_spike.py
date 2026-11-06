"""Unit tests for tenant context rules (no database).

End-to-end API isolation is covered by tests/test_workspace_tenancy_integration.py.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

for key, value in {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/test",
    "MINIO_URL": "http://localhost:9000",
    "MINIO_ROOT_USER": "test",
    "MINIO_ROOT_PASSWORD": "test",
    "IMAP_HOST": "localhost",
    "IMAP_USER": "test",
    "IMAP_PASSWORD": "test",
    "IMAP_FOLDER": "INBOX",
    "ANTHROPIC_API_KEY": "test",
    "OPENAI_API_KEY": "test",
    "ACTIVE_MODEL_PROVIDER": "test",
    "SECRET_KEY": "test",
    "OFFICE_HUB_API_KEY": "test",
    "DEFAULT_ORG_ID": "00000000-0000-0000-0000-000000000001",
    "ENVIRONMENT": "test",
}.items():
    os.environ.setdefault(key, value)

from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import settings
from app.core.tenancy import TenantContext
from app.core.tenancy import lot_scope_sql
from app.core.tenancy import resolve_actor
from app.core.tenancy import resolve_tenant
from app.models.core import Org
from app.models.core import OrgProjectScope
from app.models.core import ProjectRole
from app.models.core import User
from app.models.core import UserOrgRole
from app.models.core import UserRole


def org(scope: OrgProjectScope, land: bool = False) -> Org:
    return Org(id=uuid4(), name="Org", slug=f"org-{uuid4().hex[:6]}", member_project_scope=scope, land_enabled=land)


def ctx(scope: OrgProjectScope, role: UserOrgRole | None, *, user_role: UserRole = UserRole.STAFF,
        superadmin: bool = False, land: bool = False) -> TenantContext:
    user = User(id=uuid4(), org_id=uuid4(), role=user_role, is_superadmin=superadmin, permissions={})
    return TenantContext(user=user, org=org(scope, land), membership_role=role, is_superadmin=superadmin,
                         is_fallback=False, explicit_org=False)


def request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "query_string": b""})


class TenantContextRulesTest(unittest.TestCase):
    def test_org_scope_member_gets_editor_without_grants(self) -> None:
        context = ctx(OrgProjectScope.ORG, UserOrgRole.MEMBER, land=True)
        self.assertTrue(context.org_wide_projects)
        self.assertEqual(context.org_wide_role, ProjectRole.EDITOR)
        self.assertTrue(context.can_access_land)
        predicate, params = lot_scope_sql(context)
        self.assertNotIn("project_members", predicate)
        self.assertEqual(params, {"tenant_org_id": str(context.org_id)})

    def test_readonly_member_is_viewer(self) -> None:
        context = ctx(OrgProjectScope.ORG, UserOrgRole.MEMBER, user_role=UserRole.READONLY)
        self.assertEqual(context.org_wide_role, ProjectRole.VIEWER)
        self.assertFalse(context.can_manage_clients)

    def test_assigned_scope_member_needs_project_grants(self) -> None:
        context = ctx(OrgProjectScope.ASSIGNED, UserOrgRole.MEMBER, land=True)
        self.assertFalse(context.org_wide_projects)
        self.assertIsNone(context.org_wide_role)
        self.assertFalse(context.can_access_land)
        predicate, params = lot_scope_sql(context)
        self.assertIn("core.project_members", predicate)
        self.assertEqual(params["tenant_user_id"], str(context.user.id))

    def test_tenant_admin_and_superadmin_are_owners(self) -> None:
        self.assertEqual(ctx(OrgProjectScope.ASSIGNED, UserOrgRole.TENANT_ADMIN).org_wide_role, ProjectRole.OWNER)
        self.assertEqual(ctx(OrgProjectScope.ASSIGNED, None, superadmin=True).org_wide_role, ProjectRole.OWNER)

    def test_land_requires_land_enabled_org(self) -> None:
        self.assertFalse(ctx(OrgProjectScope.ORG, UserOrgRole.MEMBER, land=False).can_access_land)

    def test_rentals_only_for_legacy_org_with_permission(self) -> None:
        context = ctx(OrgProjectScope.ORG, UserOrgRole.MEMBER, user_role=UserRole.ADMIN)
        self.assertFalse(context.can_access_rentals)
        context.org.id = settings.default_org_id
        self.assertTrue(context.can_access_rentals)
        staff = ctx(OrgProjectScope.ORG, UserOrgRole.MEMBER)
        staff.org.id = settings.default_org_id
        self.assertFalse(staff.can_access_rentals)
        staff.user.permissions = {"rentals": "viewer"}
        self.assertTrue(staff.can_access_rentals)


class ActorResolutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_enforced_without_user_is_unauthorized(self) -> None:
        previous = settings.auth_enforced
        settings.auth_enforced = True
        try:
            with self.assertRaises(HTTPException) as error:
                await resolve_actor(request({"X-OfficeHub-Org": "connection-homes"}), AsyncMock())
            self.assertEqual(error.exception.status_code, 401)
        finally:
            settings.auth_enforced = previous

    async def test_disabled_without_admin_is_unauthorized(self) -> None:
        previous = settings.auth_enforced
        settings.auth_enforced = False
        try:
            db = AsyncMock()
            db.scalar.return_value = None
            with self.assertRaises(HTTPException) as error:
                await resolve_actor(request(), db)
            self.assertEqual(error.exception.status_code, 401)
        finally:
            settings.auth_enforced = previous

    async def test_fallback_actor_cannot_select_another_org(self) -> None:
        previous = settings.auth_enforced
        settings.auth_enforced = False
        try:
            home = Org(id=settings.default_org_id, name="CH", slug="connection-homes",
                       member_project_scope=OrgProjectScope.ORG, land_enabled=True)
            other = Org(id=uuid4(), name="PS", slug="potterstone-builders")
            admin = User(id=uuid4(), org_id=home.id, role=UserRole.ADMIN, is_superadmin=True, permissions={})
            db = AsyncMock()
            db.get.return_value = home
            db.scalar.side_effect = [admin, other]
            with self.assertRaises(HTTPException) as error:
                await resolve_tenant(request({"X-OfficeHub-Org": other.slug}), db)
            self.assertEqual(error.exception.status_code, 401)

            db.scalar.side_effect = [admin, None]
            context = await resolve_tenant(request(), db)
            self.assertTrue(context.is_fallback)
            self.assertFalse(context.is_superadmin)
            self.assertEqual(context.org_id, home.id)
        finally:
            settings.auth_enforced = previous


if __name__ == "__main__":
    unittest.main()
