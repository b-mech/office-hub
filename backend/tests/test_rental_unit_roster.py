"""Read-only Rental Units roster: occupancy, current lease choice, tenants, rent and flags."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.core import UserRole
from app.services import rental_units
from app.services.rental_units import build_roster, lease_flag, pick_leases

TODAY = date(2026, 11, 12)


def unit(uid: int, label: str | None = "Main") -> SimpleNamespace:
    return SimpleNamespace(id=uid, unit_label=label, is_basement=False, status="unknown")


def prop(pid: int = 1, address: str = "166 Clubhouse Dr") -> SimpleNamespace:
    return SimpleNamespace(id=pid, street_address=address, group_name="Clubhouse", city="Niverville")


def lease(lid: int, unit_id: int, status: str = "active", start: date | None = date(2026, 1, 1),
          end: date | None = date(2027, 1, 1), rent: str = "1850.00", discount: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=lid, unit_id=unit_id, status=status, lease_start=start, lease_end=end,
                           rent=Decimal(rent), rent_discount_amount=Decimal(discount) if discount else None,
                           deposit=Decimal("900"))


def test_pick_leases_prefers_newest_current_and_tracks_latest_any_status() -> None:
    leases = [lease(1, 10, start=date(2024, 1, 1)), lease(2, 10, start=date(2025, 6, 1)),
              lease(3, 10, status="expired", start=date(2026, 6, 1)), lease(4, 11, status="expired")]
    current, latest = pick_leases(leases)
    assert current[10].id == 2 and 11 not in current
    assert latest[10].id == 3 and latest[11].id == 4


@pytest.mark.parametrize("item,expected", [
    (None, None),
    (lease(1, 1, status="month_to_month", end=date(2025, 1, 1)), "month_to_month"),
    (lease(1, 1, end=date(2026, 11, 1)), "past_end"),
    (lease(1, 1, end=date(2027, 1, 11)), "ending_soon"),
    (lease(1, 1, end=date(2027, 1, 12)), None),
    (lease(1, 1, end=None), None),
])
def test_lease_flag(item, expected) -> None:
    assert lease_flag(item, TODAY) == expected


def test_build_roster_reports_occupied_and_vacant_units_with_tenants_and_net_rent() -> None:
    rows = [(unit(10, "Up"), prop()), (unit(11, None), prop()), (unit(12, "Down"), prop(2, "5 Gray Pl"))]
    leases = [lease(1, 10, discount="50"), lease(2, 11, status="expired", end=date(2026, 8, 31))]
    roster = build_roster(rows, leases, {1: [("Zed Tenant", False), ("Amy Primary", True)]}, {10: 2},
                          {12: "draft"}, today=TODAY)
    up, main, down = roster
    assert up["occupancy"] == "occupied" and up["tenants"] == ["Amy Primary", "Zed Tenant"]
    assert up["primary_tenant"] == "Amy Primary" and up["open_maintenance_tickets"] == 2
    assert up["lease"]["rent"] == "1850.00" and up["lease"]["net_rent"] == "1800.00"
    assert up["lease"]["days_to_end"] == 50 and up["lease"]["flag"] == "ending_soon"
    assert main["occupancy"] == "vacant" and main["unit_label"] == "Main building" and main["lease"] is None
    assert main["last_lease_end"] == date(2026, 8, 31) and main["last_lease_status"] == "expired"
    assert down["occupancy"] == "vacant" and down["last_lease_end"] is None
    assert down["lease_agreement_status"] == "draft"


class FakeDb:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN, is_active=True, permissions={})

    async def scalar(self, query):
        return self.admin

    async def execute(self, query):
        self.statements.append(str(query))
        rows = [(unit(10, "Up"), prop())] if len(self.statements) == 1 else []
        return SimpleNamespace(all=lambda: rows)

    async def scalars(self, query):
        self.statements.append(str(query))
        return SimpleNamespace(all=lambda: [lease(1, 10)])


@pytest.fixture
def roster_api(monkeypatch):
    db = FakeDb()

    async def dep():
        yield db

    app.dependency_overrides[get_db] = dep
    yield db
    app.dependency_overrides.clear()


async def get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_roster_endpoint_is_read_only_and_returns_units(roster_api, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", False)
    response = await get("/api/rentals/units/roster?property_id=1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[0]["unit_id"] == 10 and body[0]["occupancy"] == "occupied" and body[0]["lease"]["rent"] == "1850.00"
    assert "rental_properties.id = " in roster_api.statements[0]
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in roster_api.statements)


@pytest.mark.asyncio
async def test_roster_requires_sign_in_when_auth_enforced(roster_api, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", True)
    response = await get("/api/rentals/units/roster")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_roster_route_does_not_shadow_unit_inspection_history() -> None:
    paths = [route.path for route in app.routes]
    assert "/api/rentals/units/roster" in paths and "/api/rentals/units/{unit_id}/inspections" in paths


@pytest.mark.asyncio
async def test_unit_roster_empty_without_units() -> None:
    class Empty:
        async def execute(self, query):
            return SimpleNamespace(all=lambda: [])

    assert await rental_units.unit_roster(Empty()) == []  # type: ignore[arg-type]
