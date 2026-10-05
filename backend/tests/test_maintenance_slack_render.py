from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.maintenance.slack.render import (
    render_emergency_alert,
    render_ticket_card,
    render_work_order_card,
)
from app.services.maintenance.slack.types import TicketCardView, WorkOrderCardView


NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)


def view(**overrides: object) -> TicketCardView:
    values: dict[str, object] = {
        "id": uuid4(),
        "number": "MT-00001",
        "title": "Leaking sink",
        "description": "Water is leaking under the kitchen sink.",
        "status": "new",
        "category": "water_leak",
        "priority": "emergency",
        "is_emergency": True,
        "emergency_acknowledged": False,
        "property_label": "Test Property",
        "unit_label": "Unit 2",
        "reporter_name": "Alex Tenant",
        "reporter_verified": False,
        "entry_permission": "denied",
        "sla_due_at": NOW - timedelta(minutes=1),
    }
    values.update(overrides)
    return TicketCardView(**values)  # type: ignore[arg-type]


def test_ticket_card_contains_warnings_and_state_actions() -> None:
    blocks = render_ticket_card(view(), now=NOW)
    rendered = repr(blocks)
    assert "MT-00001" in rendered
    assert "SLA overdue" in rendered
    assert "not verified" in rendered
    assert "maint_ack_emergency" in rendered
    assert "maint_open_triage" in rendered
    assert "maint_open_message" in rendered
    assert len(blocks) <= 50


def test_closed_ticket_shows_reopen_instead_of_message() -> None:
    blocks = render_ticket_card(
        view(status="closed", is_emergency=False, emergency_acknowledged=True, sla_due_at=None),
        now=NOW,
    )
    rendered = repr(blocks)
    assert "maint_reopen" in rendered
    assert "maint_open_message" not in rendered


def test_emergency_alert_is_separate_from_ticket_card() -> None:
    alert = render_emergency_alert(view())
    assert "maint_ack_emergency" in repr(alert)
    assert "maint_open_triage" not in repr(alert)


def test_staff_work_order_card_is_explicitly_internal() -> None:
    order = WorkOrderCardView(
        id=uuid4(),
        number="MT-00001-W1",
        assignee_type="staff",
        assignee_name="Pat Staff",
        status="offered",
        scope="Inspect the shutoff valve",
    )
    blocks = render_work_order_card(order, uuid4())
    assert "Internal staff" in repr(blocks)
    assert "maint_open_complete_work_order" in repr(blocks)
