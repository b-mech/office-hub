from __future__ import annotations
import json
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.maintenance import MaintEvent, MaintEventChannel, MaintParty, MaintPriority, MaintStatus, MaintTicket
from app.models.rentals import RentalProperty, RentalUnit
from app.schemas.maintenance import StaffTicketCreate
from app.services.maintenance.notifier import NoopMaintenanceNotifier
from app.services.maintenance.sms.outbound import SmsOptedOutError
from app.services.maintenance.staff_tickets import confirmation_policy, create_staff_ticket
from app.services.maintenance.state_machine import ActorContext

class FakeDb:
    def __init__(self): self.added=[]; self.committed=False; self.rolled_back=False
    async def get(self,model,identity):
        if model is RentalProperty: return SimpleNamespace(id=1,street_address="1 Test Street") if identity==1 else None
        if model is RentalUnit: return SimpleNamespace(id=2,property_id=1,unit_label="A") if identity==2 else None
    def add(self,obj): self.added.append(obj)
    async def flush(self):
        for obj in self.added:
            if getattr(obj,"id",None) is None: obj.id=uuid4()
            if isinstance(obj,MaintTicket):
                if obj.status is None: obj.status=MaintStatus.NEW
                if obj.number is None: obj.number="MT-TEST"
    async def commit(self): self.committed=True
    async def rollback(self): self.rolled_back=True

def fields(**overrides):
    return dict(property_id=1,unit_id=2,title="Leaking kitchen tap",description="The kitchen tap drips all day.",category="plumbing",**overrides)

@pytest.fixture
def isolated(monkeypatch):
    db=FakeDb(); queued=[]
    async def dep():yield db
    async def queue(*args,**kwargs):queued.append(kwargs);return SimpleNamespace(id=uuid4())
    app.dependency_overrides[get_db]=dep
    monkeypatch.setattr(settings,"auth_enforced",False)
    monkeypatch.setattr(settings,"environment","staging")
    monkeypatch.setattr(settings,"staging_sms_allowlist","+12045551234")
    monkeypatch.setattr("app.services.maintenance.staff_tickets.get_maintenance_notifier",lambda:NoopMaintenanceNotifier())
    monkeypatch.setattr("app.services.maintenance.staff_tickets.queue_sms",queue)
    yield db,queued
    app.dependency_overrides.clear()

async def post(data,files=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://testserver") as c:
        return await c.post("/api/maintenance/tickets",data={"data":json.dumps(data)},files=files)

@pytest.mark.asyncio
async def test_staff_create_classifies_starts_sla_and_logs_web_event(isolated):
    db,queued=isolated;r=await post(fields())
    assert r.status_code==201,r.text
    assert r.json()["status"]=="triaged" and r.json()["sla_due_at"] and not r.json()["needs_reply"]
    item=next(o for o in db.added if isinstance(o,MaintTicket))
    event=next(o for o in db.added if isinstance(o,MaintEvent) and o.event_type=="created")
    assert item.source=="staff" and item.reporter_verified is False
    assert event.channel==MaintEventChannel.WEB and event.actor_party==MaintParty.STAFF
    assert event.payload=={"source":"staff","confirmation_sms_opt_in":False}
    assert db.committed and not queued

@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,expected",[({},"not_requested"),({"sms_opt_in":True},"no_phone"),({"reporter_phone":"2045551234"},"not_requested"),({"reporter_phone":"2045551234","sms_opt_in":True},"queued"),({"reporter_phone":"2045555678","sms_opt_in":True},"blocked_staging")])
async def test_confirmation_requires_phone_consent_and_allowlist(isolated,overrides,expected):
    db,queued=isolated;r=await post(fields(**overrides));assert r.status_code==201,r.text
    assert r.json()["confirmation"]==expected
    assert len(queued)==int(expected=="queued")

@pytest.mark.asyncio
async def test_existing_optout_is_not_overridden(isolated,monkeypatch):
    async def blocked(*a,**kw):raise SmsOptedOutError("Opted out")
    monkeypatch.setattr("app.services.maintenance.staff_tickets.queue_sms",blocked)
    r=await post(fields(reporter_phone="2045551234",sms_opt_in=True))
    assert r.status_code==201 and r.json()["confirmation"]=="blocked_opt_out"

@pytest.mark.asyncio
@pytest.mark.parametrize("override",[{"is_emergency":True},{"priority":"emergency"}])
async def test_emergency_is_not_implicitly_acknowledged(isolated,override):
    r=await post(fields(**override));assert r.status_code==201,r.text
    ticket=next(o for o in isolated[0].added if isinstance(o,MaintTicket))
    assert ticket.is_emergency and ticket.priority==MaintPriority.EMERGENCY and ticket.emergency_acked_at is None

@pytest.mark.asyncio
async def test_invalid_unit_and_untrusted_source_rejected(isolated):
    values=fields();values["unit_id"]=999
    assert (await post(values)).status_code==422
    assert (await post(fields(source="sms"))).status_code==422

@pytest.mark.asyncio
async def test_invalid_photo_fails_before_ticket_creation(isolated):
    r=await post(fields(),[("photos",("bad.jpg",b"not an image","image/jpeg"))])
    assert r.status_code==422 and not isolated[0].added

@pytest.mark.asyncio
async def test_create_requires_staff_permission_when_auth_enforced(isolated,monkeypatch):
    monkeypatch.setattr(settings,"auth_enforced",True)
    assert (await post(fields())).status_code==401  # Middleware rejects unauthenticated callers first.

@pytest.mark.asyncio
async def test_staff_actor_is_recorded(isolated):
    db,_=isolated;actor=ActorContext(MaintParty.STAFF,user_id=uuid4())
    ticket,_=await create_staff_ticket(db,StaffTicketCreate(**fields()),actor)
    assert ticket.created_by==actor.user_id
    assert next(o for o in db.added if isinstance(o,MaintEvent) and o.event_type=="created").actor_user_id==actor.user_id


@pytest.mark.asyncio
async def test_staff_photos_attach_to_created_ticket_with_web_audit(isolated,monkeypatch):
    from io import BytesIO
    from PIL import Image
    uploaded=[]
    async def store(db,**kwargs):uploaded.append(kwargs);return SimpleNamespace(id=uuid4())
    monkeypatch.setattr("app.services.maintenance.staff_tickets.store_attachment",store)
    image=BytesIO();Image.new("RGB",(2,2)).save(image,format="JPEG")
    r=await post(fields(),[("photos",("tap.jpg",image.getvalue(),"image/jpeg"))])
    assert r.status_code==201,r.text
    assert len(uploaded)==1 and str(uploaded[0]["ticket_id"])==r.json()["id"]
    assert uploaded[0]["uploaded_by_party"]==MaintParty.STAFF
    assert any(isinstance(e,MaintEvent) and e.event_type=="attachment_added" and e.channel==MaintEventChannel.WEB for e in isolated[0].added)


@pytest.mark.asyncio
async def test_invalid_later_photo_does_not_leave_partial_ticket(isolated):
    from io import BytesIO
    from PIL import Image
    image=BytesIO();Image.new("RGB",(2,2)).save(image,format="JPEG")
    r=await post(fields(),[("photos",("tap.jpg",image.getvalue(),"image/jpeg")),("photos",("bad.jpg",b"bad","image/jpeg"))])
    assert r.status_code==422 and not isolated[0].added
