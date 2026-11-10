from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.maintenance import MaintCategory
from app.services.maintenance.media import create_ticket_upload_token
from app.services.maintenance.rate_limit import RateLimitExceeded
from app.services.maintenance.turnstile import TurnstileError


class FakeDb:
    async def execute(self, statement): return None
    async def commit(self): return None
    async def rollback(self): return None


async def fake_db():
    yield FakeDb()


class PassLimiter:
    async def intake(self, token_hash: str, ip: str): return None


class FailingLimiter:
    async def intake(self, token_hash: str, ip: str):
        raise RateLimitExceeded("Too many submissions for this intake link; try again later")


@pytest.fixture
def configured_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "public_base_url", "https://maintenance.invalid")
    app.dependency_overrides[get_db] = fake_db
    yield app
    app.dependency_overrides.clear()


async def post_form() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post("/api/public/intake/token", data=form())


def form() -> dict[str, str]:
    return {
        "name": "Alex Tenant",
        "phone": "204 555 1234",
        "category": "plumbing",
        "description": "The kitchen tap is leaking steadily.",
        "entry_permission": "denied",
        "entry_notes": "Cat inside",
        "cf-turnstile-response": "XXXX.DUMMY.TOKEN.XXXX",
    }


@pytest.mark.asyncio
async def test_turnstile_failure_returns_422(configured_app, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routers.maintenance.resolve_intake_unit", _resolved)
    async def fail(*args, **kwargs): raise TurnstileError("The anti-spam check failed; please try again")
    monkeypatch.setattr("app.routers.maintenance.verify_turnstile", fail)
    response = await post_form()
    assert response.status_code == 422
    assert "anti-spam" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limit_returns_429(configured_app, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routers.maintenance.resolve_intake_unit", _resolved)
    async def pass_turnstile(*args, **kwargs): return None
    monkeypatch.setattr("app.routers.maintenance.verify_turnstile", pass_turnstile)
    monkeypatch.setattr("app.routers.maintenance.get_rate_limiter", lambda: FailingLimiter())
    response = await post_form()
    assert response.status_code == 429
    assert "Too many" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unmatched_phone_creates_unverified_ticket(configured_app, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}
    monkeypatch.setattr("app.routers.maintenance.resolve_intake_unit", _resolved)
    async def pass_turnstile(*args, **kwargs): return None
    async def no_lease(*args, **kwargs): return None
    async def create(db, data, actor, **kwargs):
        captured["data"] = data
        return SimpleNamespace(id=uuid4(), number="MT-00001", is_emergency=False)
    async def queue(*args, **kwargs): return SimpleNamespace(id=uuid4())
    monkeypatch.setattr("app.routers.maintenance.verify_turnstile", pass_turnstile)
    monkeypatch.setattr("app.routers.maintenance.get_rate_limiter", lambda: PassLimiter())
    monkeypatch.setattr("app.routers.maintenance._current_lease_for_phone", no_lease)
    monkeypatch.setattr("app.routers.maintenance.create_ticket", create)
    monkeypatch.setattr("app.routers.maintenance.queue_sms", queue)

    response = await post_form()
    assert response.status_code == 201
    assert response.json()["ticket_number"] == "MT-00001"
    assert response.json()["photo_upload_token"]
    assert captured["data"].reporter_verified is False
    assert captured["data"].category == MaintCategory.PLUMBING


@pytest.mark.asyncio
async def test_photos_upload_after_ticket_submission(
    configured_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket_id = uuid4()
    ticket = SimpleNamespace(
        id=ticket_id,
        source="tenant_qr",
        reporter_phone_e164="+12045551234",
    )
    db = PhotoDb(ticket, existing_count=0)

    async def photo_db():
        yield db

    captured = {}

    async def store(db, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), event_id=None)

    app.dependency_overrides[get_db] = photo_db
    monkeypatch.setattr("app.routers.maintenance.store_attachment", store)
    token = create_ticket_upload_token(ticket_id, settings.secret_key)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/public/intake/photos/{token}",
            files={"photos": ("leak.jpg", b"photo bytes", "image/jpeg")},
        )

    assert response.status_code == 201
    assert response.json() == {"uploaded": 1}
    assert captured["ticket_id"] == ticket_id
    assert captured["content"] == b"photo bytes"
    assert db.committed is True


class PhotoDb:
    def __init__(self, ticket, *, existing_count: int):
        self.results = [ticket, existing_count]
        self.committed = False

    async def scalar(self, statement):
        return self.results.pop(0)

    def add(self, item):
        return None

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        return None


async def _resolved(*args, **kwargs):
    return (
        SimpleNamespace(id=11, property_id=22, unit_label="2"),
        SimpleNamespace(id=22, group_name="Test Property", street_address="100 Test Street"),
    )
