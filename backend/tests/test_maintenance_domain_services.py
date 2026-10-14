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
    MaintWorkOrder,
    MaintWorkOrderStatus,
)
from app.services.maintenance.entry_notice import EntryNoticeError
from app.services.maintenance.sms.outbound import cancel_held_sms
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.tickets import acknowledge_emergency, cancel_ticket, mark_duplicate
from app.services.maintenance.work_orders import (
    assign_vendor_work_order,
    is_future_scheduled_visit,
    schedule_work_order,
)
from app.services.maintenance.workspace import (
    _future_scheduled_visits,
    post_message,
    preview_schedule_work,
    resolve_ticket,
    schedule_work,
    set_scheduled_visit_status,
)


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


class FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class WorkOrderSession(FakeSession):
    def __init__(self, orders: list[object], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.orders = orders

    async def scalars(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult(self.orders)


def ticket(status: MaintStatus = MaintStatus.TRIAGED, *, emergency: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        number="MT-00001",
        property_id=1,
        unit_id=2,
        status=status,
        is_emergency=emergency,
        entry_permission="denied",
        entry_notes=None,
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
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
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
        reason="inspect the boiler",
        now=NOW,
    )  # type: ignore[arg-type]
    assert order.status == MaintWorkOrderStatus.SCHEDULED
    assert order.scheduled_visit_status == "scheduled"
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
            reason="inspect the boiler",
            now=NOW,
        )  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_invalid_visit_never_queues_entry_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    item = ticket(MaintStatus.ASSIGNED)
    order = SimpleNamespace(id=uuid4(), ticket_id=item.id)
    db = FakeSession(objects={MaintWorkOrder: order})
    queued = False

    async def queue(*args: object, **kwargs: object) -> None:
        nonlocal queued
        queued = True

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    start = NOW + timedelta(days=2)
    with pytest.raises(EntryNoticeError, match="same local calendar day"):
        await schedule_work(
            db,  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            ActorContext(MaintParty.STAFF, user_id=uuid4()),
            work_order_id=order.id,
            start=start,
            end=start + timedelta(days=30),
            reason="repair the kitchen faucet",
            now=NOW,
        )

    assert queued is False
    assert not hasattr(order, "scheduled_start")
    assert db.added == []


def schedulable_order(ticket_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        ticket_id=ticket_id,
        number="MT-00001-W1",
        status=MaintWorkOrderStatus.ACCEPTED,
        assignee_type="staff",
        vendor_id=None,
        scheduled_start=None,
        scheduled_end=None,
    )


async def stub_address(*args: object, **kwargs: object) -> tuple[str, str]:
    return "10 Test Street", "Unit A"


@pytest.mark.asyncio
async def test_routine_schedule_validates_then_sends_exact_entry_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr(settings, "sms_signature", "— Connect Properties")
    monkeypatch.setattr("app.services.maintenance.workspace._ticket_address_and_unit", stub_address)
    item = ticket(MaintStatus.ASSIGNED)
    item.reporter_phone_e164 = "+12045550100"
    item.entry_notes = "Fuidi"
    order = schedulable_order(item.id)
    db = FakeSession(objects={MaintWorkOrder: order})
    queued: list[dict[str, object]] = []

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        queued.append(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    start = NOW + timedelta(hours=25)
    await schedule_work(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        work_order_id=order.id,
        start=start,
        end=start + timedelta(hours=2),
        access_basis="routine",
        reason="repair the kitchen faucet",
        now=NOW,
    )

    assert queued[0]["body"] == (
        "Connect Properties: Notice of entry to 10 Test Street, Unit A on Sat Oct 3 between "
        "11:00 AM and 1:00 PM to repair the kitchen faucet. Reply with any questions."
    )
    assert "Fuidi" not in str(queued[0]["body"])
    assert any(value.event_type == "entry_notice_sent" for value in db.added)
    assert not any(value.event_type == "entry_policy_exemption" for value in db.added)


@pytest.mark.asyncio
async def test_schedule_preview_requires_staff_reason_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr("app.services.maintenance.workspace._ticket_address_and_unit", stub_address)
    item = ticket(MaintStatus.ASSIGNED)
    order = schedulable_order(item.id)
    db = FakeSession(objects={MaintWorkOrder: order})
    start = NOW + timedelta(hours=25)

    with pytest.raises(EntryNoticeError, match="Reason for entry is required"):
        await preview_schedule_work(
            db,  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            work_order_id=order.id,
            start=start,
            end=start + timedelta(hours=2),
            reason="   ",
            now=NOW,
        )

    message = await preview_schedule_work(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        work_order_id=order.id,
        start=start,
        end=start + timedelta(hours=2),
        reason="repair the kitchen faucet",
        now=NOW,
    )
    assert message == (
        "Connect Properties: Notice of entry to 10 Test Street, Unit A on Sat Oct 3 between "
        "11:00 AM and 1:00 PM to repair the kitchen faucet. Reply with any questions."
    )
    assert db.added == []


@pytest.mark.asyncio
async def test_tenant_consent_requires_evidence_and_records_actor_and_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr(settings, "sms_signature", "— Connect Properties")
    monkeypatch.setattr("app.services.maintenance.workspace._ticket_address_and_unit", stub_address)
    item = ticket(MaintStatus.ASSIGNED)
    item.reporter_phone_e164 = "+12045550100"
    order = schedulable_order(item.id)
    db = FakeSession(objects={MaintWorkOrder: order})
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    queued: list[dict[str, object]] = []

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        queued.append(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    start = NOW + timedelta(hours=2)
    with pytest.raises(EntryNoticeError, match="requires the tenant's message"):
        await schedule_work(
            db,  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            actor,
            work_order_id=order.id,
            start=start,
            end=start + timedelta(hours=1),
            access_basis="tenant_consent",
            reason="repair the kitchen faucet",
            now=NOW,
        )

    evidence = "Tenant texted: noon works for me."
    await schedule_work(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        actor,
        work_order_id=order.id,
        start=start,
        end=start + timedelta(hours=1),
        access_basis="tenant_consent",
        consent_evidence=evidence,
        reason="repair the kitchen faucet",
        now=NOW,
    )

    assert queued[0]["body"] == (
        "Connect Properties: Confirming the visit you agreed to at 10 Test Street, Unit A on "
        "Fri Oct 2, 12:00 PM–1:00 PM, to repair the kitchen faucet. Reply if this no longer works."
    )
    exemption = next(value for value in db.added if value.event_type == "entry_policy_exemption")
    assert exemption.actor_user_id == actor.user_id
    assert exemption.payload["evidence"] == evidence
    assert evidence in exemption.body
    assert any(value.event_type == "tenant_consent_confirmation_sent" for value in db.added)


@pytest.mark.asyncio
async def test_emergency_schedule_skips_window_and_sends_on_the_way_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr(settings, "sms_signature", "— Connect Properties")
    monkeypatch.setattr(settings, "privi_emergency_phone", "+12042598093")
    monkeypatch.setattr("app.services.maintenance.workspace._ticket_address_and_unit", stub_address)
    item = ticket(MaintStatus.ASSIGNED, emergency=True)
    item.reporter_phone_e164 = "+12045550100"
    order = schedulable_order(item.id)
    db = FakeSession(objects={MaintWorkOrder: order})
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    queued: list[dict[str, object]] = []

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        queued.append(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    start = datetime(2026, 10, 3, 7, 0, tzinfo=timezone.utc)
    await schedule_work(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        actor,
        work_order_id=order.id,
        start=start,
        end=start + timedelta(hours=1),
        access_basis="emergency",
        now=NOW,
    )

    assert queued[0]["body"] == (
        "Connect Properties: A technician is on the way to 10 Test Street, Unit A for your "
        "emergency request. Reply or call (204) 259-8093 if anything changes."
    )
    assert queued[0]["emergency"] is True
    exemption = next(value for value in db.added if value.event_type == "entry_policy_exemption")
    assert exemption.actor_user_id == actor.user_id
    assert exemption.payload["access_basis"] == "emergency"
    assert any(value.event_type == "emergency_on_way_sent" for value in db.added)


@pytest.mark.asyncio
async def test_staff_composer_uses_prefix_without_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr(settings, "sms_signature", "— Connect Properties")
    item = ticket(MaintStatus.ASSIGNED)
    item.reporter_phone_e164 = "+12045550100"
    db = FakeSession()
    queued: dict[str, object] = {}

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        queued.update(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    await post_message(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        target="tenant",
        body="We can come Tuesday.",
        work_order_id=None,
        files=[],
    )
    assert queued["body"] == "Connect Properties: We can come Tuesday."
    assert queued["append_signature"] is False


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
    item.entry_notes = "Dog in the house; call before coming"
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
    assert "Entry notes: Dog in the house; call before coming." in str(queued["body"])
    assert "https://maintenance.invalid/w/raw-one-time-token" in str(queued["body"])


def test_sms_messages_have_no_inbound_slack_relay_identity() -> None:
    assert "slack_channel_id" not in MaintSmsMessage.__table__.columns
    assert "slack_ts" not in MaintSmsMessage.__table__.columns


def test_future_scheduled_visit_is_independent_of_completed_work_order() -> None:
    order = SimpleNamespace(
        status=MaintWorkOrderStatus.COMPLETED,
        scheduled_start=NOW + timedelta(days=1),
        scheduled_visit_status="scheduled",
    )
    assert is_future_scheduled_visit(order, now=NOW) is True  # type: ignore[arg-type]
    assert _future_scheduled_visits([order], now=NOW) == [order]  # type: ignore[list-item]
    order.scheduled_visit_status = "cancelled"
    assert is_future_scheduled_visit(order, now=NOW) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cancelling_noticed_visit_queues_exact_tenant_text_and_thread_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr(settings, "sms_signature", "— Connect Properties")
    monkeypatch.setattr("app.services.maintenance.workspace._ticket_address_and_unit", stub_address)
    ticket_id = uuid4()
    order_id = uuid4()
    item = ticket(MaintStatus.SCHEDULED)
    item.id = ticket_id
    item.reporter_phone_e164 = "+12045550100"
    order = SimpleNamespace(
        id=order_id,
        ticket_id=ticket_id,
        number="MT-00001-W1",
        scheduled_start=datetime(2026, 10, 11, 14, 27, tzinfo=timezone.utc),
        scheduled_end=datetime(2026, 10, 11, 16, 27, tzinfo=timezone.utc),
        scheduled_visit_status="scheduled",
    )
    db = FakeSession(scalar=uuid4())
    queued: dict[str, object] = {}

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        queued.update(kwargs)
        message = SimpleNamespace(id=uuid4())
        db.added.append(
            SimpleNamespace(
                event_type="message",
                body=kwargs["body"],
                sms_message_id=message.id,
            )
        )
        return message

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    await set_scheduled_visit_status(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        order,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        status="cancelled",
        now=NOW,
    )

    assert order.scheduled_visit_status == "cancelled"
    assert queued["body"] == (
        "Connect Properties: The visit to 10 Test Street, Unit A scheduled for Sun Oct 11 at "
        "9:27 AM is no longer needed."
    )
    assert queued["ticket_id"] == ticket_id
    assert queued["work_order_id"] == order_id
    assert any(value.event_type == "scheduled_visit_cancelled" for value in db.added)
    assert any(
        value.event_type == "message" and value.body == queued["body"]
        for value in db.added
    )


@pytest.mark.asyncio
async def test_reschedule_cancels_old_notice_then_sends_new_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    monkeypatch.setattr("app.services.maintenance.workspace._ticket_address_and_unit", stub_address)
    item = ticket(MaintStatus.SCHEDULED)
    item.reporter_phone_e164 = "+12045550100"
    old_start = NOW + timedelta(days=2)
    old_end = old_start + timedelta(hours=1)
    order = schedulable_order(item.id)
    order.status = MaintWorkOrderStatus.SCHEDULED
    order.scheduled_start = old_start
    order.scheduled_end = old_end
    order.scheduled_visit_status = "scheduled"
    # Rescheduling always cancels the old time, even when its notice event is unavailable.
    db = FakeSession(scalar=None, objects={MaintWorkOrder: order})
    queued: list[dict[str, object]] = []

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        queued.append(kwargs)
        message = SimpleNamespace(id=uuid4())
        db.added.append(SimpleNamespace(event_type="message", body=kwargs["body"], sms_message_id=message.id))
        return message

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    new_start = NOW + timedelta(days=3)
    await schedule_work(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        work_order_id=order.id,
        start=new_start,
        end=new_start + timedelta(hours=1),
        reason="repair the kitchen faucet",
        now=NOW,
    )

    assert len(queued) == 2
    assert "scheduled for Sun Oct 4 at 10:00 AM is no longer needed" in str(queued[0]["body"])
    assert "Notice of entry" in str(queued[1]["body"])
    assert order.scheduled_start == new_start
    assert any(value.event_type == "scheduled_visit_rescheduled" for value in db.added)
    assert sum(value.event_type == "message" for value in db.added) == 2


@pytest.mark.asyncio
async def test_invalid_reschedule_keeps_old_visit_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    item = ticket(MaintStatus.SCHEDULED)
    item.reporter_phone_e164 = "+12045550100"
    old_start = NOW + timedelta(days=2)
    order = schedulable_order(item.id)
    order.status = MaintWorkOrderStatus.SCHEDULED
    order.scheduled_start = old_start
    order.scheduled_end = old_start + timedelta(hours=1)
    order.scheduled_visit_status = "scheduled"
    db = FakeSession(scalar=uuid4(), objects={MaintWorkOrder: order})
    queued = False

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal queued
        queued = True
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    with pytest.raises(EntryNoticeError, match="same local calendar day"):
        await schedule_work(
            db,  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            ActorContext(MaintParty.STAFF, user_id=uuid4()),
            work_order_id=order.id,
            start=NOW + timedelta(days=3),
            end=NOW + timedelta(days=4),
            reason="repair the kitchen faucet",
            now=NOW,
        )
    assert queued is False
    assert order.scheduled_start == old_start


@pytest.mark.asyncio
async def test_resolve_lists_future_visit_until_it_is_cancelled_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    item = ticket(MaintStatus.SCHEDULED)
    item.reporter_phone_e164 = None
    order = SimpleNamespace(
        id=uuid4(),
        ticket_id=item.id,
        number="MT-00001-W1",
        created_at=NOW,
        scheduled_start=NOW + timedelta(days=365),
        scheduled_end=NOW + timedelta(days=365, hours=2),
        scheduled_visit_status="scheduled",
    )
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    blocked_db = WorkOrderSession([order])
    with pytest.raises(ValueError, match=r"Resolve blocked by scheduled visits: MT-00001-W1"):
        await resolve_ticket(
            blocked_db,  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            actor,
            note="Fixed",
        )

    resolved_db = WorkOrderSession([order], scalar=uuid4())
    await resolve_ticket(
        resolved_db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        actor,
        note="Fixed",
        cancel_scheduled_visit_ids=[order.id],
    )
    assert order.scheduled_visit_status == "cancelled"
    assert item.status == MaintStatus.RESOLVED


@pytest.mark.asyncio
async def test_resolve_new_ticket_without_work_order() -> None:
    item = ticket(MaintStatus.NEW)
    item.reporter_phone_e164 = None
    db = WorkOrderSession([])

    await resolve_ticket(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        note="Handled during the initial call",
    )

    assert item.status == MaintStatus.RESOLVED
    assert item.resolved_at is not None
    event = next(value for value in db.added if value.event_type == "status_changed")
    assert event.payload == {"from": "new", "to": "resolved", "reason": "Handled during the initial call"}


@pytest.mark.asyncio
async def test_resolving_resolved_ticket_is_idempotent_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = ticket(MaintStatus.RESOLVED)
    item.reporter_phone_e164 = "+12045550100"
    db = WorkOrderSession([])
    queued = False

    async def queue(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal queued
        queued = True
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.services.maintenance.workspace.queue_sms", queue)
    await resolve_ticket(
        db,  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        ActorContext(MaintParty.STAFF, user_id=uuid4()),
        note="Repeated request",
    )

    assert item.status == MaintStatus.RESOLVED
    assert queued is False
    assert db.added == []
