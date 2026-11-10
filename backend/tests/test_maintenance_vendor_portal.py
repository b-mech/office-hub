from __future__ import annotations
from datetime import datetime,timedelta,timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth import AuthenticationMiddleware
from app.models.maintenance import (MaintAttachment,MaintEvent,MaintEventChannel,MaintParty,MaintStatus,MaintTicket,MaintVendor,MaintWorkOrder,MaintWorkOrderStatus)
from app.models.rentals import RentalProperty,RentalUnit
from app.routers.maintenance import router
from app.schemas.maintenance import VendorPortalAction
from app.services.maintenance.rate_limit import RateLimitExceeded
from app.services.maintenance.tokens import hash_token,rotate_work_order_token
from app.services.maintenance.vendor_portal import (InvalidVendorLink,VendorActionConflict,apply_vendor_action,public_text,resolve_vendor_link)
NOW=datetime(2026,11,10,17,tzinfo=timezone.utc)
TOKEN="v"*43
PATH=f"/api/public/work-orders/{TOKEN}"

class FakeDb:
 def __init__(self):
  self.vendor=MaintVendor(id=uuid4(),name="Test Plumbing",phone_e164="+12045555678",is_active=True)
  self.ticket=MaintTicket(id=uuid4(),number="MT-TEST",property_id=1,unit_id=2,status=MaintStatus.ASSIGNED,is_emergency=False,reporter_phone_e164="+12045551234",entry_permission="denied",entry_notes="Cat inside. Tenant: 204-555-1234")
  self.order=MaintWorkOrder(id=uuid4(),ticket_id=self.ticket.id,number="MT-TEST-W1",assignee_type="vendor",vendor_id=self.vendor.id,status=MaintWorkOrderStatus.OFFERED,scope="Fix tap. Call (204) 555-1234",access_token_hash=hash_token(TOKEN),token_expires_at=datetime.now(timezone.utc)+timedelta(days=20),created_at=NOW)
  self.added=[];self.queries=[];self.photos=[];self.commits=0
 def add(self,o):self.added.append(o)
 async def flush(self):
  for o in self.added:
   if getattr(o,"id",None) is None:o.id=uuid4()
 async def commit(self):await self.flush();self.commits+=1
 async def rollback(self):pass
 async def scalar(self,q):
  self.queries.append(q);entity=q.column_descriptions[0].get("entity")
  if entity is MaintWorkOrder:
   params=q.compile().params
   return self.order if self.order.access_token_hash and hash_token(TOKEN) in params.values() else None
  if entity is MaintTicket:return self.ticket
  return len(self.photos) if entity is MaintAttachment else 0
 async def scalars(self,q):return SimpleNamespace(all=lambda:self.photos)
 async def get(self,model,key):
  if model is MaintVendor:return self.vendor
  if model is RentalProperty:return SimpleNamespace(street_address="1 Test Street")
  if model is RentalUnit:return SimpleNamespace(unit_label="A")
  if model is MaintAttachment:return next((p for p in self.photos if p.id==key),None)
  if model is MaintWorkOrder:return self.order
  if model is MaintTicket:return self.ticket

class Limiter:
 async def vendor_portal(self,*a,**kw):pass

@pytest.fixture
def portal(monkeypatch):
 monkeypatch.setattr(settings,"auth_enforced",True)
 db=FakeDb();api=FastAPI();api.include_router(router);api.add_middleware(AuthenticationMiddleware)
 async def dep():yield db
 api.dependency_overrides[get_db]=dep
 monkeypatch.setattr(settings,"public_base_url","https://maintenance.invalid")
 monkeypatch.setattr("app.routers.maintenance.get_rate_limiter",lambda:Limiter())
 return api,db

async def request(portal,method="GET",path=PATH,**kwargs):
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=portal[0]),base_url="http://testserver") as c:return await c.request(method,path,**kwargs)

@pytest.mark.asyncio
async def test_vendor_capability_is_public_and_never_serializes_tenant_contact(portal):
 r=await request(portal);assert r.status_code==200,r.text
 assert "1234" not in r.text and "reporter" not in r.text
 assert r.json()["scope"]=="Fix tap. Call [phone withheld]"
 assert r.headers["cache-control"]=="no-store, private"
 assert r.headers["referrer-policy"]=="no-referrer"
 assert (await request(portal,path="/api/maintenance/tickets")).status_code==401

@pytest.mark.asyncio
@pytest.mark.parametrize("case",["expired","legacy_expired","revoked","inactive","cancelled","declined","wrong_assignee","closed_ticket"])
async def test_invalid_expired_or_revoked_is_clean_404(portal,case):
 db=portal[1]
 if case=="expired":db.order.token_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
 if case=="legacy_expired":db.order.token_expires_at=None;db.order.created_at=datetime.now(timezone.utc)-timedelta(days=31)
 if case=="revoked":db.order.access_token_hash=None
 if case=="inactive":db.vendor.is_active=False
 if case=="cancelled":db.order.status=MaintWorkOrderStatus.CANCELLED
 if case=="declined":db.order.status=MaintWorkOrderStatus.DECLINED
 if case=="wrong_assignee":db.order.assignee_type="staff"
 if case=="closed_ticket":db.ticket.status=MaintStatus.CLOSED
 r=await request(portal);assert r.status_code==404,r.text
 assert "expired or revoked" in r.json()["detail"] and "1234" not in r.text

@pytest.mark.asyncio
async def test_accept_records_vendor_web_inbound_and_locks_rows(portal):
 r=await request(portal,"POST",PATH+"/actions",json={"action":"accept"});assert r.status_code==200,r.text
 db=portal[1];assert db.order.status==MaintWorkOrderStatus.ACCEPTED
 e=db.added[-1];assert e.channel==MaintEventChannel.WEB and e.actor_party==MaintParty.VENDOR and e.actor_vendor_id==db.vendor.id
 assert e.event_type=="message" and e.direction.value=="inbound" and e.payload["vendor_action"]=="accept"
 assert sum(q._for_update_arg is not None for q in db.queries)==2
 assert (await request(portal,"POST",PATH+"/actions",json={"action":"accept"})).status_code==409

@pytest.mark.asyncio
async def test_decline_requires_reason_and_revokes_link(portal):
 assert (await request(portal,"POST",PATH+"/actions",json={"action":"decline"})).status_code==422
 r=await request(portal,"POST",PATH+"/actions",json={"action":"decline","notes":"Unavailable this week"})
 assert r.status_code==200 and r.json()["link_revoked"] is True
 assert (await request(portal)).status_code==404

@pytest.mark.asyncio
async def test_proposal_logs_but_does_not_schedule_or_send_notice(portal):
 db=portal[1];db.order.status=MaintWorkOrderStatus.ACCEPTED
 start=NOW+timedelta(days=2);end=start+timedelta(hours=1)
 await apply_vendor_action(db,db.order,db.ticket,db.vendor,VendorPortalAction(action="propose_schedule",start=start,end=end),now=NOW)
 assert db.order.status==MaintWorkOrderStatus.ACCEPTED and db.order.scheduled_start is None
 assert db.added[-1].payload["requires_staff_confirmation"]
 assert all(isinstance(e,MaintEvent) for e in db.added)

@pytest.mark.asyncio
async def test_proposal_respects_entry_notice_and_cannot_claim_exemptions(portal):
 db=portal[1];db.order.status=MaintWorkOrderStatus.ACCEPTED
 with pytest.raises(ValueError,match="24"):
  await apply_vendor_action(db,db.order,db.ticket,db.vendor,VendorPortalAction(action="propose_schedule",start=NOW+timedelta(hours=1),end=NOW+timedelta(hours=2)),now=NOW)
 r=await request(portal,"POST",PATH+"/actions",json={"action":"propose_schedule","start":(NOW+timedelta(days=2)).isoformat(),"end":(NOW+timedelta(days=2,hours=1)).isoformat(),"access_basis":"tenant_consent"})
 assert r.status_code==422

@pytest.mark.asyncio
async def test_start_requires_staff_schedule_time_and_emergency_ack(portal):
 db=portal[1]
 with pytest.raises(VendorActionConflict):await apply_vendor_action(db,db.order,db.ticket,db.vendor,VendorPortalAction(action="start"),now=NOW)
 db.order.status=MaintWorkOrderStatus.SCHEDULED;db.order.scheduled_visit_status="scheduled";db.order.scheduled_start=NOW;db.order.scheduled_end=NOW+timedelta(hours=1);db.ticket.status=MaintStatus.SCHEDULED
 with pytest.raises(VendorActionConflict,match="window"):await apply_vendor_action(db,db.order,db.ticket,db.vendor,VendorPortalAction(action="start"),now=NOW-timedelta(minutes=1))
 db.ticket.is_emergency=True
 with pytest.raises(VendorActionConflict,match="acknowledge"):await apply_vendor_action(db,db.order,db.ticket,db.vendor,VendorPortalAction(action="start"),now=NOW)
 db.ticket.emergency_acked_at=NOW
 await apply_vendor_action(db,db.order,db.ticket,db.vendor,VendorPortalAction(action="start"),now=NOW)
 assert db.order.status==MaintWorkOrderStatus.IN_PROGRESS and db.ticket.status==MaintStatus.IN_PROGRESS

@pytest.mark.asyncio
async def test_complete_does_not_resolve_ticket(portal):
 db=portal[1];db.order.status=MaintWorkOrderStatus.IN_PROGRESS;db.ticket.status=MaintStatus.IN_PROGRESS
 r=await request(portal,"POST",PATH+"/actions",json={"action":"complete","notes":"Tap washer replaced; tested dry."})
 assert r.status_code==200,r.text
 assert db.order.status==MaintWorkOrderStatus.COMPLETED and db.ticket.status==MaintStatus.IN_PROGRESS
 assert any(e.event_type=="work_order_completed" and e.channel==MaintEventChannel.WEB for e in db.added)

@pytest.mark.asyncio
async def test_only_own_vendor_photos_are_downloadable_and_revoke_is_enforced(portal,monkeypatch):
 db=portal[1];photo=SimpleNamespace(id=uuid4(),work_order_id=db.order.id,uploaded_by_party=MaintParty.VENDOR,kind="photo",content_type="image/jpeg",minio_key="test/photo.jpg")
 db.photos=[photo];seen=[]
 def download(key):seen.append(key);return b"photo"
 monkeypatch.setattr("app.routers.maintenance.download_attachment",download)
 r=await request(portal,path=PATH+f"/photos/{photo.id}");assert r.status_code==200 and seen==[photo.minio_key]
 photo.uploaded_by_party=MaintParty.TENANT
 assert (await request(portal,path=PATH+f"/photos/{photo.id}")).status_code==404
 photo.uploaded_by_party=MaintParty.VENDOR;db.order.access_token_hash=None
 assert (await request(portal,path=PATH+f"/photos/{photo.id}")).status_code==404

@pytest.mark.asyncio
async def test_photos_are_bounded_validated_and_scoped_to_order(portal,monkeypatch):
 seen=[]
 async def store(db,**kw):seen.append(kw);return SimpleNamespace(id=uuid4())
 monkeypatch.setattr("app.services.maintenance.vendor_portal.store_attachment",store)
 bad=await request(portal,"POST",PATH+"/photos",files=[("photos",("bad.jpg",b"bad","image/jpeg"))]);assert bad.status_code==422 and not seen
 image=BytesIO();Image.new("RGB",(2,2)).save(image,format="JPEG")
 r=await request(portal,"POST",PATH+"/photos",files=[("photos",("photo.jpg",image.getvalue(),"image/jpeg"))]);assert r.status_code==201,r.text
 assert seen[0]["work_order_id"]==portal[1].order.id and seen[0]["uploaded_by_party"]==MaintParty.VENDOR

@pytest.mark.asyncio
async def test_rate_limit_fails_before_actions(portal,monkeypatch):
 class Blocked:
  async def vendor_portal(self,*a,**k):raise RateLimitExceeded("Too many updates")
 monkeypatch.setattr("app.routers.maintenance.get_rate_limiter",lambda:Blocked())
 assert (await request(portal,"POST",PATH+"/actions",json={"action":"accept"})).status_code==429
 assert not portal[1].added


def test_rotated_tokens_expire_and_free_text_contact_is_redacted():
 order=MaintWorkOrder();rotate_work_order_token(order)
 assert order.token_expires_at>datetime.now(timezone.utc)+timedelta(days=29)
 assert public_text("Tenant +1 (204) 555-1234, mobile 204.555.1234")=="Tenant [phone withheld], mobile [phone withheld]"
