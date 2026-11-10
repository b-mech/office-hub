from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import httpx
import pytest

from app.core.database import get_db
from app.main import app


class FakeDb:
    pass


async def fake_db():
    yield FakeDb()


@pytest.mark.asyncio
async def test_calendar_api_returns_visits_and_backlog_with_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignee_id = uuid4()
    captured: dict[str, object] = {}

    async def view(db: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "timezone": "America/Winnipeg",
            "visits": [{"id": "visit-one"}],
            "unscheduled": [{"id": "backlog-one"}],
            "properties": [],
            "assignees": [],
        }

    monkeypatch.setattr("app.routers.maintenance.calendar_view", view)
    app.dependency_overrides[get_db] = fake_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/maintenance/calendar",
                params={
                    "start": "2026-10-12T00:00:00-05:00",
                    "end": "2026-10-19T00:00:00-05:00",
                    "property_id": "42",
                    "assignee_id": str(assignee_id),
                    "visit_type": "tenant_consent",
                    "status": "scheduled",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["visits"] == [{"id": "visit-one"}]
    assert response.json()["unscheduled"] == [{"id": "backlog-one"}]
    assert captured == {
        "start": datetime.fromisoformat("2026-10-12T00:00:00-05:00"),
        "end": datetime.fromisoformat("2026-10-19T00:00:00-05:00"),
        "property_id": 42,
        "assignee_id": assignee_id,
        "visit_type": "tenant_consent",
        "status": "scheduled",
    }


@pytest.mark.asyncio
async def test_calendar_api_rejects_invalid_range(monkeypatch: pytest.MonkeyPatch) -> None:
    async def view(db: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("Calendar range end must be after start")

    monkeypatch.setattr("app.routers.maintenance.calendar_view", view)
    app.dependency_overrides[get_db] = fake_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/maintenance/calendar?start=2026-10-19T00:00:00Z&end=2026-10-12T00:00:00Z"
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["detail"] == "Calendar range end must be after start"
