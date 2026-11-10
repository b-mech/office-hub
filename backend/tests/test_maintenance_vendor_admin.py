from __future__ import annotations
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.database import get_db
from app.models.maintenance import MaintEvent,MaintParty,MaintVendor,MaintWorkOrder
from app.routers.maintenance import router
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.work_orders import assign_vendor_work_order

class FakeDb:
 def __init__(self):self.vendors=[];self.orders=[];self.added=[];self.queries=[];self.fail_unique=False
 def add(self,o):
  self.added.append(o)
  if isinstance(o,MaintVendor):self.vendors.append(o)
 async def flush(self):
  if self.fail_unique:raise IntegrityError("insert",{},Exception("uq_maint_vendors_active_phone"))
  for o in self.added:
   if getattr(o,"id",None) is None:o.id=uuid4()
 async def commit(self):pass
 async def rollback(self):pass
 async def scalar(self,q):
  self.queries.append(q);params=q.compile().params
  if q.column_descriptions[0]["expr"] is MaintVendor:return next((v for v in self.vendors if v.id in params.values()),None)
  phone=next((p for p in params.values() if isinstance(p,str) and p.startswith("+")),None)
  if "sms_opted_out IS true" in str(q):return next((v.id for v in self.vendors if v.phone_e164==phone and v.sms_opted_out),None)
  return next((v.id for v in self.vendors if v.is_active and v.phone_e164==phone and v.id not in params.values()),None)
 async def scalars(self,q):
  self.queries.append(q)
  if q.column_descriptions[0]["entity"] is MaintWorkOrder:return SimpleNamespace(all=lambda:self.orders)
  active_only="is_active IS true" in str(q)
  return SimpleNamespace(all=lambda:[v for v in self.vendors if v.is_active or not active_only])
 async def get(self,model,key):return next((v for v in self.vendors if v.id==key),None)

@pytest.fixture
def admin(monkeypatch):
 db=FakeDb();api=FastAPI();api.include_router(router)
 async def dep():yield db
 api.dependency_overrides[get_db]=dep
 monkeypatch.setattr(settings,"auth_enforced",False)
 monkeypatch.setattr(settings,"public_base_url","https://maintenance.invalid")
 return api,db

async def request(admin,method="GET",suffix="",**kw):
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin[0]),base_url="http://testserver") as c:return await c.request(method,"/api/maintenance/vendors"+suffix,**kw)

def data(**overrides):return {"name":"Test Plumbing","phone_e164":"204 555 1234","trades":["plumbing"],"insurance_expiry":"2027-02-01","wcb_expiry":"2027-03-01","notes":"Test only",**overrides}

@pytest.mark.asyncio
async def test_create_normalizes_phone_and_lists_active_vendor(admin):
 r=await request(admin,"POST",json=data());assert r.status_code==201,r.text
 assert r.json()["phone_e164"]=="+12045551234" and r.json()["is_active"] is True
 assert r.json()["insurance_expiry"]=="2027-02-01"
 listing=await request(admin);assert len(listing.json())==1
 assert "is_active IS true" in str(admin[1].queries[-1])

@pytest.mark.asyncio
async def test_duplicate_active_phone_rejected_even_if_format_differs(admin):
 assert (await request(admin,"POST",json=data())).status_code==201
 r=await request(admin,"POST",json=data(name="Other vendor",phone_e164="+12045551234"));assert r.status_code==409
 assert len(admin[1].vendors)==1

@pytest.mark.asyncio
async def test_edit_clear_expiries_and_deactivate_hide_and_revoke_links(admin):
 r=await request(admin,"POST",json=data());identity=r.json()["id"];vendor=admin[1].vendors[0]
 order=MaintWorkOrder(id=uuid4(),ticket_id=uuid4(),vendor_id=vendor.id,access_token_hash="test-digest")
 admin[1].orders=[order]
 r=await request(admin,"PATCH","/"+identity,json={"name":"Updated Plumbing","insurance_expiry":None,"is_active":False})
 assert r.status_code==200 and r.json()["name"]=="Updated Plumbing" and r.json()["insurance_expiry"] is None
 assert (await request(admin)).json()==[]
 assert len((await request(admin,suffix="?include_inactive=true")).json())==1
 assert order.access_token_hash is None and order.token_expires_at<=datetime.now(timezone.utc)
 assert any(isinstance(e,MaintEvent) and e.payload=={"reason":"vendor_deactivated"} for e in admin[1].added)
 assert (await request(admin,"POST",json=data(name="Replacement"))).status_code==201
 assert (await request(admin,"PATCH","/"+identity,json={"is_active":True})).status_code==409
 assert vendor.is_active is False

@pytest.mark.asyncio
async def test_inactive_duplicate_phone_allowed(admin):
 assert (await request(admin,"POST",json=data())).status_code==201
 assert (await request(admin,"POST",json=data(is_active=False))).status_code==201

@pytest.mark.asyncio
@pytest.mark.parametrize("overrides",[{"phone_e164":"not a number"},{"name":"  "},{"trades":["not_a_trade"]},{"insurance_expiry":"yesterday"}])
async def test_invalid_vendor_input_rejected(admin,overrides):
 assert (await request(admin,"POST",json=data(**overrides))).status_code==422

@pytest.mark.asyncio
async def test_required_fields_cannot_be_cleared_and_missing_id_404(admin):
 r=await request(admin,"POST",json=data());identity=r.json()["id"]
 assert (await request(admin,"PATCH","/"+identity,json={"phone_e164":None})).status_code==422
 assert (await request(admin,"PATCH","/"+str(uuid4()),json={"notes":"test"})).status_code==404

@pytest.mark.asyncio
async def test_concurrent_unique_constraint_maps_to_clean_409(admin):
 admin[1].fail_unique=True;r=await request(admin,"POST",json=data())
 assert r.status_code==409 and r.json()["detail"]=="An active vendor already uses this phone"
 assert "insert" not in r.text

@pytest.mark.asyncio
async def test_manage_vendors_permission_is_required(admin,monkeypatch):
 monkeypatch.setattr(settings,"auth_enforced",True)
 assert (await request(admin)).status_code==403
 assert (await request(admin,"POST",json=data())).status_code==403
 assert (await request(admin,"PATCH","/"+str(uuid4()),json={"is_active":False})).status_code==403

@pytest.mark.asyncio
async def test_inactive_vendor_cannot_be_assigned(admin):
 vendor=MaintVendor(id=uuid4(),name="Inactive",phone_e164="+12045551234",is_active=False)
 admin[1].vendors=[vendor]
 with pytest.raises(ValueError,match="Active vendor not found"):
  await assign_vendor_work_order(admin[1],SimpleNamespace(id=uuid4()),ActorContext(MaintParty.STAFF),vendor_id=vendor.id,scope="Test scope")


@pytest.mark.asyncio
async def test_replacement_vendor_inherits_inactive_contacts_stop(admin):
    prior=MaintVendor(id=uuid4(),name="Previous contact",phone_e164="+12045551234",is_active=False,sms_opted_out=True)
    admin[1].vendors=[prior]
    response=await request(admin,"POST",json=data())
    assert response.status_code==201 and response.json()["sms_opted_out"] is True
    assert (await request(admin,"PATCH","/"+response.json()["id"],json={"sms_opted_out":False})).status_code==422


@pytest.mark.asyncio
async def test_phone_edit_cannot_discard_optout_history(admin):
    response=await request(admin,"POST",json=data());vendor=admin[1].vendors[0];vendor.sms_opted_out=True
    changed=await request(admin,"PATCH","/"+response.json()["id"],json={"phone_e164":"+12045555678"})
    assert changed.status_code==422 and vendor.phone_e164=="+12045551234" and vendor.sms_opted_out is True
