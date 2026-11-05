from __future__ import annotations

import unittest
import os
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
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

from app.core.tenancy import require_project_access
from app.core.tenancy import resolve_current_org
from app.core.tenancy import user_org_ids
from app.models.core import Org
from app.models.core import ProjectMember
from app.models.core import ProjectRole
from app.models.core import User
from app.models.core import UserOrgMembership
from app.models.core import UserOrgRole


def make_request(user: User, selected_org: str | None = None) -> Request:
    headers = [] if selected_org is None else [(b"x-officehub-org", selected_org.encode())]
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": headers})
    request.state.user = user
    return request


class TenancySpikeTest(unittest.IsolatedAsyncioTestCase):
    async def test_membership_required_for_org_switch(self) -> None:
        home = uuid4()
        other = Org(id=uuid4(), name="Potterstone Builders", slug="potterstone-builders")
        user = User(id=uuid4(), org_id=home, is_superadmin=False)
        db = AsyncMock()
        db.scalar.return_value = other
        db.scalars.return_value = MagicMock(all=lambda: [home])

        with self.assertRaises(HTTPException) as error:
            await resolve_current_org(make_request(user, other.slug), db)
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(await user_org_ids(user, db), {home})

        db.scalars.return_value = MagicMock(all=lambda: [home, other.id])
        self.assertEqual((await resolve_current_org(make_request(user, other.slug), db)).id, other.id)

    async def test_superadmin_can_resolve_seeded_org_by_slug_or_uuid(self) -> None:
        user = User(id=uuid4(), org_id=uuid4(), is_superadmin=True)
        for slug in ("potterstone-builders", "privi-holdings"):
            org = Org(id=uuid4(), name=slug, slug=slug)
            db = AsyncMock()
            db.scalar.return_value = org
            db.get.return_value = org
            self.assertEqual((await resolve_current_org(make_request(user, slug), db)).id, org.id)
            self.assertEqual((await resolve_current_org(make_request(user, str(org.id)), db)).id, org.id)
            db.scalars.assert_not_awaited()

    async def test_project_owner_allowed_and_stranger_denied(self) -> None:
        org_id, lot_id = uuid4(), uuid4()
        owner = User(id=uuid4(), org_id=org_id, is_superadmin=False)
        db = AsyncMock()
        db.scalar.side_effect = [
            org_id,
            UserOrgMembership(user_id=owner.id, org_id=org_id, role=UserOrgRole.MEMBER),
            ProjectMember(lot_id=lot_id, user_id=owner.id, role=ProjectRole.OWNER),
        ]
        await require_project_access(owner, lot_id, ProjectRole.EDITOR, db)

        stranger = User(id=uuid4(), org_id=org_id, is_superadmin=False)
        db.scalar.side_effect = [org_id, None]
        with self.assertRaises(HTTPException) as error:
            await require_project_access(stranger, lot_id, ProjectRole.VIEWER, db)
        self.assertEqual(error.exception.status_code, 403)

    async def test_superadmin_and_tenant_admin_allowed(self) -> None:
        org_id, lot_id = uuid4(), uuid4()
        db = AsyncMock()
        superadmin = User(id=uuid4(), org_id=uuid4(), is_superadmin=True)
        await require_project_access(superadmin, lot_id, ProjectRole.OWNER, db)
        db.scalar.assert_not_awaited()

        admin = User(id=uuid4(), org_id=org_id, is_superadmin=False)
        db.scalar.side_effect = [
            org_id,
            UserOrgMembership(user_id=admin.id, org_id=org_id, role=UserOrgRole.TENANT_ADMIN),
        ]
        await require_project_access(admin, lot_id, ProjectRole.OWNER, db)
        self.assertEqual(db.scalar.await_count, 2)

    async def test_member_without_project_membership_denied(self) -> None:
        org_id, lot_id = uuid4(), uuid4()
        member = User(id=uuid4(), org_id=org_id, is_superadmin=False)
        db = AsyncMock()
        db.scalar.side_effect = [
            org_id,
            UserOrgMembership(user_id=member.id, org_id=org_id, role=UserOrgRole.MEMBER),
            None,
        ]
        with self.assertRaises(HTTPException) as error:
            await require_project_access(member, lot_id, ProjectRole.VIEWER, db)
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
