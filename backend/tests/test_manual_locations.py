from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.config import settings
from app.core.database import get_db
from app.core.tenancy import TenantContext, get_tenant
from app.models.core import UserRole, UserOrgRole, OrgProjectScope
from app.modules.lots.router import router as lots_router
from app.routers.rentals import inspections_router
from app.schemas.locations import LocationPatch
from app.services.locations import apply_location


def row():
    return SimpleNamespace(id=uuid4(),latitude=Decimal("49.980809"),longitude=Decimal("-97.088781"),geocode_precision="street",geocode_source="osm_nominatim",geocoded_at=datetime(2026,11,9,tzinfo=timezone.utc),location_set_by=None,geocode_snapshot=None,trigger_type=None,cancelled=False)


def context(*,org=None,role=UserRole.ADMIN,permission="editor"):
    org=org or settings.default_org_id
    return TenantContext(user=SimpleNamespace(id=uuid4(),role=role,permissions={"rentals":permission}),org=SimpleNamespace(id=org,land_enabled=True,member_project_scope=OrgProjectScope.ORG),membership_role=UserOrgRole.TENANT_ADMIN,is_superadmin=False,is_fallback=True,explicit_org=False)


def client(ctx,db):
    app=FastAPI();app.include_router(lots_router);app.include_router(inspections_router)
    app.dependency_overrides[get_tenant]=lambda:ctx
    app.dependency_overrides[get_db]=lambda:db
    return TestClient(app)


def test_lot_save_range_warning_actor_and_reset_roundtrip():
    r=row();ctx=context();old=(r.latitude,r.longitude,r.geocoded_at)
    db=SimpleNamespace(scalar=AsyncMock(side_effect=[ctx.org_id,r,r]),get=AsyncMock(return_value=r),commit=AsyncMock())
    c=client(ctx,db)
    saved=c.patch(f"/api/v1/lots/{r.id}/location",json={"latitude":48.5,"longitude":-97.1})
    assert saved.status_code==200,saved.text
    assert saved.json()["geocode_precision"]=="manual"
    assert saved.json()["location_set_by"]==str(ctx.user.id)
    assert saved.json()["warnings"] and saved.json()["actor_is_fallback"]
    reset=c.patch(f"/api/v1/lots/{r.id}/location",json={"action":"reset"})
    assert reset.status_code==200,reset.text
    assert reset.json()["geocode_precision"]=="street"
    assert (r.latitude,r.longitude,r.geocoded_at)==old
    assert r.location_set_by is None and r.geocode_snapshot is None
    assert db.commit.await_count==2


@pytest.mark.parametrize("payload",[{"latitude":91,"longitude":-97},{"latitude":49,"longitude":181},{"latitude":49},{"action":"clear","latitude":49},{"action":"unknown"},{"latitude":49,"longitude":-97,"location_set_by":str(uuid4())}])
def test_lot_endpoint_rejects_invalid_or_actor_spoofed_payload(payload):
    db=SimpleNamespace(scalar=AsyncMock(),get=AsyncMock(),commit=AsyncMock())
    response=client(context(),db).patch(f"/api/v1/lots/{uuid4()}/location",json=payload)
    assert response.status_code==422
    db.commit.assert_not_awaited()


def test_lot_cross_org_is_404_and_never_writes():
    db=SimpleNamespace(scalar=AsyncMock(return_value=uuid4()),get=AsyncMock(),commit=AsyncMock())
    response=client(context(),db).patch(f"/api/v1/lots/{uuid4()}/location",json={"latitude":49.9,"longitude":-97.1})
    assert response.status_code==404
    db.commit.assert_not_awaited();db.get.assert_not_awaited()


def test_readonly_lot_actor_cannot_place_pin():
    ctx=context(role=UserRole.READONLY)
    db=SimpleNamespace(scalar=AsyncMock(return_value=ctx.org_id),get=AsyncMock(),commit=AsyncMock())
    assert client(ctx,db).patch(f"/api/v1/lots/{uuid4()}/location",json={"latitude":49.9,"longitude":-97.1}).status_code==403
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("ctx",[context(org=uuid4()),context(role=UserRole.STAFF,permission="viewer"),context(role=UserRole.READONLY)])
def test_rental_cross_org_or_non_editor_denied(ctx):
    db=SimpleNamespace(scalar=AsyncMock(),commit=AsyncMock())
    response=client(ctx,db).patch("/api/rentals/properties/5/location",json={"latitude":49.7,"longitude":-96.8})
    assert response.status_code==403
    db.scalar.assert_not_awaited();db.commit.assert_not_awaited()


def test_rental_save_adjust_clear_and_reset_preserve_original_geocode():
    r=row();ctx=context();db=SimpleNamespace(scalar=AsyncMock(return_value=r),commit=AsyncMock());c=client(ctx,db)
    for lat in [49.7,49.71]:
        response=c.patch("/api/rentals/properties/5/location",json={"latitude":lat,"longitude":-96.8})
        assert response.status_code==200 and response.json()["geocode_source"]=="manual"
    assert r.geocode_snapshot["latitude"]=="49.980809"
    assert c.patch("/api/rentals/properties/5/location",json={"action":"clear"}).status_code==200
    assert r.latitude is None and r.geocode_snapshot
    reset=c.patch("/api/rentals/properties/5/location",json={"action":"reset"})
    assert reset.status_code==200 and reset.json()["geocode_precision"]=="street"
    assert r.latitude==Decimal("49.980809")


def test_reset_without_snapshot_conflicts_and_leaves_row_unchanged():
    r=row()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:apply_location(r,LocationPatch(action="reset"),uuid4())
    assert exc.value.status_code==409 and r.geocode_precision=="street"
