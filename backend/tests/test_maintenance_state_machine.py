from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.maintenance import MaintParty, MaintPriority, MaintStatus, MaintWorkOrderStatus
from app.services.maintenance.errors import InvalidTransitionError
from app.services.maintenance.state_machine import ALLOWED_TRANSITIONS, ActorContext, transition, validate_transition
from app.services.maintenance.work_orders import (
    all_active_work_orders_complete,
    status_after_first_work_order,
    status_after_schedule,
    status_after_work_started,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.parametrize(
    ("current", "target"),
    [(current, target) for current, targets in ALLOWED_TRANSITIONS.items() for target in targets],
)
def test_every_allowed_transition(current: MaintStatus, target: MaintStatus) -> None:
    validate_transition(
        current,
        target,
        is_admin=current in {MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE},
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (MaintStatus.NEW, MaintStatus.RESOLVED),
        (MaintStatus.TRIAGED, MaintStatus.CLOSED),
        (MaintStatus.IN_PROGRESS, MaintStatus.ASSIGNED),
        (MaintStatus.CANCELLED, MaintStatus.IN_PROGRESS),
        (MaintStatus.DUPLICATE, MaintStatus.TRIAGED),
    ],
)
def test_disallowed_transition(current: MaintStatus, target: MaintStatus) -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(current, target)


def test_closed_reopen_requires_admin() -> None:
    with pytest.raises(InvalidTransitionError, match="admin"):
        validate_transition(MaintStatus.CLOSED, MaintStatus.IN_PROGRESS)
    validate_transition(MaintStatus.CLOSED, MaintStatus.IN_PROGRESS, is_admin=True)


@pytest.mark.asyncio
async def test_transition_writes_event_and_sets_triage_sla(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    ticket = SimpleNamespace(
        id=uuid4(),
        property_id=1,
        source="staff",
        reporter_party=MaintParty.STAFF,
        title="No heat",
        description="The furnace is not starting.",
        priority=MaintPriority.URGENT,
        status=MaintStatus.NEW,
        updated_at=None,
        triaged_at=None,
        triaged_by=None,
        sla_due_at=None,
        resolved_at=None,
        closed_at=None,
        close_reason=None,
    )
    actor = ActorContext(MaintParty.STAFF, user_id=uuid4())
    db = FakeSession()

    monkeypatch.setattr(
        "app.services.maintenance.state_machine.MaintEvent",
        lambda **values: SimpleNamespace(**values),
    )
    await transition(db, ticket, MaintStatus.TRIAGED, actor, now=now)  # type: ignore[arg-type]

    assert ticket.status == MaintStatus.TRIAGED
    assert ticket.triaged_at == now
    assert ticket.sla_due_at == datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    event = db.added[-1]
    assert event.event_type == "status_changed"
    assert event.payload == {"from": "new", "to": "triaged"}


def test_derived_work_order_transitions() -> None:
    assert status_after_first_work_order(MaintStatus.TRIAGED, 0) == MaintStatus.ASSIGNED
    assert status_after_first_work_order(MaintStatus.ASSIGNED, 0) is None
    assert status_after_first_work_order(MaintStatus.TRIAGED, 1) is None
    assert status_after_schedule(MaintStatus.ASSIGNED) == MaintStatus.SCHEDULED
    assert status_after_schedule(MaintStatus.AWAITING_PARTS) == MaintStatus.SCHEDULED
    assert status_after_work_started(MaintStatus.SCHEDULED) == MaintStatus.IN_PROGRESS
    assert all_active_work_orders_complete([MaintWorkOrderStatus.COMPLETED]) is True
    assert all_active_work_orders_complete([MaintWorkOrderStatus.COMPLETED, MaintWorkOrderStatus.CANCELLED]) is True
    assert all_active_work_orders_complete([MaintWorkOrderStatus.COMPLETED, MaintWorkOrderStatus.IN_PROGRESS]) is False
