from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.maintenance import (
    MaintDirection,
    MaintParty,
    MaintPriority,
    MaintSmsMessage,
    MaintStatus,
    MaintWorkOrderStatus,
)
from app.services.maintenance.entry_notice import EntryNoticeError
from app.services.maintenance.errors import PermissionDeniedError
from app.services.maintenance.sms.outbound import cancel_held_sms
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.tickets import acknowledge_emergency, cancel_ticket, mark_duplicate
from app.services.maintenance.work_orders import assign_vendor_work_order, schedule_work_order


NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self, *, scalar: object | None = None, objects: dict[type[object], object] | None = None) -> None:
        self.scalar_value = scalar
        self.objects = objects or {}
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def scalar(self, statement: object) -> object | None:
        return self.scalar_value

    async def get(self, model: type[object], identity: object) -> object | None:
        value = self.objects.get(model)
        if isinstance(value, dict):
            return value.get(identity)
        return value


def ticket(status: MaintStatus = MaintStatus.TRIAGED, *, emergency: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        number="MT-00001",
        property_id=1,
        unit_id=2,
        status=status,
        is_emergency=emergency,
        entry_permission="denied",
        priority=MaintPriority.EMERGENCY if emergency else MaintPriority.ROUTINE,
        updated_at=NOW,
        triaged_at=NOW,
        triaged_by=None,
        sla_due_at=None,
        emergency_acked_by=None,
        emergency_acked_at=None,
        resolved_at=None,
        closed_at=None,
        close_reason=None,
        duplicate_of=None,
    )


@pytest.mark.asyncio
async def test_emergency_acknowledgement_is_idempotent() -> None:
    item = ticket(emergency=True)
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    db = FakeSession()
    assert await acknowledge_emergency(db, item, actor, now=NOW) is True  # type: ignore[arg-type]
    assert item.emergency_acked_by == actor.user_id
    assert item.emergency_acked_at == NOW
    assert db.added[-1].event_type == "emergency_acknowledged"  # type: ignore[attr-defined]
    assert await acknowledge_emergency(db, item, actor, now=NOW) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_duplicate_and_cancel_use_guarded_transitions() -> None:
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    duplicate = ticket(MaintStatus.NEW)
    canonical = ticket(MaintStatus.IN_PROGRESS)
    db = FakeSession()
    await mark_duplicate(db, duplicate, canonical, actor, now=NOW)  # type: ignore[arg-type]
    assert duplicate.status == MaintStatus.DUPLICATE
    assert duplicate.duplicate_of == canonical.id

    cancelled = ticket(MaintStatus.TRIAGED)
    await cancel_ticket(db, cancelled, actor, reason="Tenant withdrew request", now=NOW)  # type: ignore[arg-type]
    assert cancelled.status == MaintStatus.CANCELLED
    assert cancelled.close_reason is None


@pytest.mark.asyncio
async def test_held_sms_cancel_is_atomic_and_appends_event() -> None:
    message = SimpleNamespace(
        id=uuid4(),
        direction=MaintDirection.OUTBOUND,
        status="held",
        cancelled_at=None,
        provider_sid=None,
        ticket_id=uuid4(),
        work_order_id=None,
        updated_at=NOW,
    )
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    db = FakeSession(scalar=message)
    result = await cancel_held_sms(db, message.id, actor, now=NOW)  # type: ignore[arg-type]
    assert result.status == "cancelled"
    assert result.cancelled_at == NOW
    assert db.added[-1].event_type == "sms_cancelled"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="no longer cancellable"):
        await cancel_held_sms(db, message.id, actor, now=NOW)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schedule_enforces_entry_notice_in_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "entry_notice_min_hours", 24)
    monkeypatch.setattr(settings, "entry_window_start", time(8, 0))
    monkeypatch.setattr(settings, "entry_window_end", time(20, 0))
    item = ticket(MaintStatus.ASSIGNED)
    order = SimpleNamespace(
        id=uuid4(),
        status=MaintWorkOrderStatus.ACCEPTED,
        scheduled_start=None,
        scheduled_end=None,
    )
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    db = FakeSession()
    start = NOW + timedelta(hours=25)
    await schedule_work_order(
        db,
        item,
        order,
        actor,
        start,
        start + timedelta(hours=2),
        now=NOW,
    )  # type: ignore[arg-type]
    assert order.status == MaintWorkOrderStatus.SCHEDULED
    scheduled_event = next(
        value for value in db.added if getattr(value, "event_type", "") == "work_order_scheduled"
    )
    assert scheduled_event.payload["entry_notice"] == "notice_required"

    with pytest.raises(EntryNoticeError):
        await schedule_work_order(
            db,
            ticket(MaintStatus.ASSIGNED),
            order,
            actor,
            NOW + timedelta(hours=1),
            NOW + timedelta(hours=2),
            now=NOW,
        )  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schedule_override_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "entry_notice_min_hours", 24)
    item = ticket(MaintStatus.ASSIGNED)
    order = SimpleNamespace(id=uuid4())
    with pytest.raises(PermissionDeniedError):
        await schedule_work_order(
            FakeSession(),  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            order,  # type: ignore[arg-type]
            ActorContext(MaintParty.STAFF, user_id=uuid4()),
            NOW + timedelta(hours=1),
            NOW + timedelta(hours=2),
            admin_override_reason="Tenant requested this time",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_vendor_assignment_queues_offer_in_same_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models.maintenance import MaintVendor
    from app.models.rentals import RentalProperty, RentalUnit

    monkeypatch.setattr(settings, "public_base_url", "https://maintenance.invalid")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr(settings, "sms_signature", "")
    vendor_id = uuid4()
    vendor = SimpleNamespace(
        id=vendor_id,
        is_active=True,
        phone_e164="+12045550123",
    )
    prop = SimpleNamespace(id=1, street_address="10 Test Street")
    unit = SimpleNamespace(id=2, unit_label="Unit 3")
    db = FakeSession(objects={MaintVendor: vendor, RentalProperty: prop, RentalUnit: unit})
    work_order = SimpleNamespace(id=uuid4(), number="MT-00001-W1", scope="Repair the sink")
    queued: dict[str, object] = {}

    async def create(*args: object, **kwargs: object) -> tuple[object, str]:
        return work_order, "raw-one-time-token"

    async def queue(*args: object, **kwargs: object) -> object:
        queued.update(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.work_orders.create_work_order", create)
    monkeypatch.setattr("app.services.maintenance.work_orders.queue_sms", queue)
    item = ticket(MaintStatus.TRIAGED)
    result = await assign_vendor_work_order(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        vendor_id=vendor_id,
        scope="Repair the sink",
    )
    assert result is work_order
    assert queued["to"] == "+12045550123"
    assert queued["ticket_id"] == item.id
    assert queued["work_order_id"] == work_order.id
    assert "https://maintenance.invalid/w/raw-one-time-token" in str(queued["body"])


def test_slack_message_identity_is_unique_when_present() -> None:
    index = next(
        item
        for item in MaintSmsMessage.__table__.indexes
        if item.name == "uq_maint_sms_messages_slack_message"
    )
    assert index.unique is True
    assert {column.name for column in index.columns} == {"slack_channel_id", "slack_ts"}
