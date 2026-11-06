from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.core import UserRole
from app.routers import lease_agreements


class FakeDb:
    def __init__(self, admin: SimpleNamespace | None) -> None:
        self.admin = admin

    async def scalar(self, query: object) -> object:
        if query.column_descriptions[0]["name"] == "User":  # type: ignore[attr-defined]
            return self.admin
        return None

    async def scalars(self, query: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: [])


@pytest.fixture
def lease_app(monkeypatch: pytest.MonkeyPatch):
    admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN, is_active=True, permissions={})
    db = FakeDb(admin)

    async def fake_db():
        yield db

    async def unit_property(db: FakeDb, unit_id: int):
        return (SimpleNamespace(id=unit_id, unit_label="1"),
                SimpleNamespace(id=7, street_address="1 Main St", municipality="Winnipeg",
                                city="Winnipeg", is_multiplex=False, is_condo=False,
                                lease_utility_override=None))

    app.dependency_overrides[get_db] = fake_db
    monkeypatch.setattr(lease_agreements.lease_workflow, "unit_property", unit_property)
    yield admin
    app.dependency_overrides.clear()


async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_lease_unit_without_auth_when_disabled(lease_app: SimpleNamespace,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", False)
    response = await request("GET", "/api/rentals/leases/units/1")
    assert response.status_code == 200
    assert response.json()["leases"] == []


@pytest.mark.asyncio
async def test_lease_unit_without_auth_when_enforced(lease_app: SimpleNamespace,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", True)
    response = await request("GET", "/api/rentals/leases/units/1")
    assert response.status_code == 401
    assert response.json() == {"detail": "Office Hub sign-in is required"}


@pytest.mark.asyncio
async def test_lease_create_uses_admin_actor_when_auth_disabled(lease_app: SimpleNamespace,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", False)
    captured = {}

    async def create(db: FakeDb, unit_id: int, user_id: object, copy_id: object) -> SimpleNamespace:
        captured["user_id"] = user_id
        return SimpleNamespace(created_by=user_id)

    monkeypatch.setattr(lease_agreements.lease_workflow, "create", create)
    monkeypatch.setattr(lease_agreements, "output", lambda lease: {"created_by": str(lease.created_by)})
    response = await request("POST", "/api/rentals/leases", json={"unit_id": 1})
    assert response.status_code == 200
    assert captured["user_id"] == lease_app.id
    assert response.json()["created_by"] == str(lease_app.id)
