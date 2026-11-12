"""P1/P2 maintenance workflows: completion costs, checklists, purchases, history, spend, filters."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import settings
from app.core.database import get_db
from app.models.maintenance import MaintEvent, MaintParty, MaintStatus, MaintTicket, MaintWorkOrderStatus
from app.routers.maintenance import router
from app.services.maintenance import extras
from app.services.maintenance.extras import (
    SpendLine,
    add_checklist_items,
    aggregate_spend,
    checklist_progress,
    log_purchase,
    parse_checklist_lines,
    record_work_order_costs,
    related_tickets,
    replay_checklist,
    set_purchase_status,
    spend_csv,
    update_checklist_item,
)
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.tickets import mark_duplicate
from app.services.maintenance.work_orders import complete_work_order
from app.services.maintenance.workspace import list_ticket_views

ACTOR = ActorContext(MaintParty.STAFF, user_id=uuid4())
T0 = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)


class EventDb:
    """Stores added events; returns them for event queries in insertion order."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.orders: dict[object, object] = {}

    def add(self, obj: object) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = T0  # type: ignore[attr-defined]
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()  # type: ignore[attr-defined]
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return self.orders.get(key)

    async def scalars(self, query):
        events = [o for o in self.added if isinstance(o, MaintEvent)]
        return SimpleNamespace(all=lambda: events)


def open_ticket(status: MaintStatus = MaintStatus.IN_PROGRESS) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), status=status, property_id=1, unit_id=2, number="MT-00001")


def ev(kind: str, payload: dict[str, object], minute: int = 0) -> SimpleNamespace:
    return SimpleNamespace(event_type=kind, payload=payload, created_at=T0.replace(minute=minute))


def test_replay_checklist_tracks_add_done_reopen_remove_in_order() -> None:
    items = replay_checklist([
        ev(extras.CHECKLIST_ADDED, {"item_id": "a", "text": "Replace bathroom fan"}),
        ev(extras.CHECKLIST_ADDED, {"item_id": "b", "text": "Patch hallway drywall"}, 1),
        ev(extras.CHECKLIST_ADDED, {"item_id": "c", "text": "Rekey front door"}, 2),
        ev(extras.CHECKLIST_UPDATED, {"item_id": "b", "done": True}, 3),
        ev(extras.CHECKLIST_UPDATED, {"item_id": "a", "done": True}, 4),
        ev(extras.CHECKLIST_UPDATED, {"item_id": "a", "done": False}, 5),
        ev(extras.CHECKLIST_REMOVED, {"item_id": "c"}, 6),
        ev(extras.CHECKLIST_UPDATED, {"item_id": "missing", "done": True}, 7),
        ev("message", {"item_id": "x"}, 8),
    ])
    assert [(i["text"], i["done"]) for i in items] == [("Replace bathroom fan", False), ("Patch hallway drywall", True)]
    assert checklist_progress(items) == {"total": 2, "done": 1}


def test_parse_checklist_lines_strips_bullets_numbers_and_blanks() -> None:
    text = "1. Fix sink trap\n2) Replace smoke alarm\n\n- Caulk tub\n* Paint door\n• Clean gutters\n- [ ] Rehang blind\n10 bags of salt"
    assert parse_checklist_lines(text) == [
        "Fix sink trap", "Replace smoke alarm", "Caulk tub", "Paint door", "Clean gutters", "Rehang blind",
        "10 bags of salt",
    ]


@pytest.mark.asyncio
async def test_six_item_punch_list_shows_partial_completion_and_is_audited() -> None:
    db, ticket = EventDb(), open_ticket()
    lines = ["Furnace filter", "Bathroom fan", "Hall light", "Closet door", "Window screen", "Garage weatherstrip"]
    items = await add_checklist_items(db, ticket, ACTOR, lines)  # type: ignore[arg-type]
    assert len(items) == 6
    items = await update_checklist_item(db, ticket, ACTOR, str(items[1]["id"]), done=True)  # type: ignore[arg-type]
    items = await update_checklist_item(db, ticket, ACTOR, str(items[1]["id"]), done=True)  # type: ignore[arg-type]
    assert checklist_progress(items) == {"total": 6, "done": 1}
    events = [o for o in db.added if isinstance(o, MaintEvent)]
    assert len(events) == 7, "re-marking done must not add a duplicate event"
    assert all(e.visibility.value == "internal" and e.actor_user_id == ACTOR.user_id for e in events)
    with pytest.raises(ValueError, match="not found"):
        await update_checklist_item(db, ticket, ACTOR, "nope", done=True)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE])
async def test_locked_tickets_reject_checklist_and_purchase_changes(status) -> None:
    db, ticket = EventDb(), open_ticket(status)
    with pytest.raises(ValueError, match="Reopen"):
        await add_checklist_items(db, ticket, ACTOR, ["x"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Reopen"):
        await log_purchase(db, ticket, ACTOR, vendor="WM Dyck", item="Fan", amount=None, status="ordered",  # type: ignore[arg-type]
                           reference=None, work_order_id=None)


@pytest.mark.asyncio
async def test_checklist_requires_items_and_caps_size() -> None:
    db, ticket = EventDb(), open_ticket()
    with pytest.raises(ValueError, match="at least one"):
        await add_checklist_items(db, ticket, ACTOR, ["  "])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at most"):
        await add_checklist_items(db, ticket, ACTOR, [f"item {i}" for i in range(51)])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_purchase_notes_log_and_move_from_ordered_to_received() -> None:
    db, ticket = EventDb(), open_ticket()
    order = SimpleNamespace(id=uuid4(), ticket_id=ticket.id)
    db.orders[order.id] = order
    purchases = await log_purchase(db, ticket, ACTOR, vendor="Amazon", item="Range hood filter",  # type: ignore[arg-type]
                                   amount=Decimal("42.5"), status="ordered", reference="113-555",
                                   work_order_id=order.id)
    assert purchases[0]["amount"] == "42.50" and purchases[0]["work_order_id"] == str(order.id)
    purchases = await set_purchase_status(db, ticket, ACTOR, str(purchases[0]["id"]), "received")  # type: ignore[arg-type]
    assert purchases[0]["status"] == "received"
    with pytest.raises(ValueError, match="Work order not found"):
        await log_purchase(db, ticket, ACTOR, vendor="A", item="B", amount=None, status="ordered",  # type: ignore[arg-type]
                           reference=None, work_order_id=uuid4())
    with pytest.raises(ValueError, match="Unsupported"):
        await set_purchase_status(db, ticket, ACTOR, str(purchases[0]["id"]), "lost")  # type: ignore[arg-type]


def line(when: datetime, actual: str | None, *, unit_id: int | None = 2, cls: str | None = "repair",
         estimate: str | None = None, prop: int = 1) -> SpendLine:
    return SpendLine(prop, f"{prop} Test St", unit_id, "A" if unit_id else "Main building",
                     Decimal(estimate) if estimate else None, Decimal(actual) if actual else None, cls, when)


def test_spend_groups_by_winnipeg_month_and_cost_class() -> None:
    lines = [
        line(datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), "100.00"),  # Oct 31 local
        line(datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc), "250.10", cls="capital", estimate="300"),
        line(datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc), "10", unit_id=3, cls=None),
        line(datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc), None, estimate="75", prop=9),
    ]
    rows = aggregate_spend(lines)
    assert [(r["month"], r["property"], r["cost_actual"]) for r in rows] == [
        ("2026-10", "1 Test St", "100.00"), ("2026-11", "1 Test St", "260.10"), ("2026-11", "9 Test St", "0.00")]
    nov = rows[1]
    assert (nov["repair_actual"], nov["capital_actual"], nov["unclassified_actual"], nov["cost_estimate"]) == (
        "0.00", "250.10", "10.00", "300.00")
    by_unit = aggregate_spend(lines, group_by="unit", start=date(2026, 11, 1), end=date(2026, 11, 3))
    assert [(r["unit_id"], r["cost_actual"]) for r in by_unit] == [(2, "250.10"), (3, "10.00")]


def test_spend_csv_neutralises_formula_cells() -> None:
    rows = aggregate_spend([SpendLine(1, "=HYPERLINK(\"x\")", None, "Main building", None, Decimal("5"), None, T0)])
    text = spend_csv(rows)
    assert text.splitlines()[0].startswith("month,property,unit")
    assert "'=HYPERLINK" in text


@pytest.mark.asyncio
async def test_staff_completion_records_cost_class_and_cannot_complete_twice() -> None:
    db = EventDb()
    async def scalar(_q):
        return 0
    db.scalar = scalar  # type: ignore[attr-defined]
    ticket = open_ticket()
    order = SimpleNamespace(id=uuid4(), ticket_id=ticket.id, number="MT-00001-W1", status=MaintWorkOrderStatus.IN_PROGRESS,
                            cost_actual=None, cost_class=None, completion_notes=None, completed_at=None)
    done = await complete_work_order(db, ticket, order, ACTOR, completion_notes=" Replaced trap ",  # type: ignore[arg-type]
                                     cost_actual=Decimal("180.00"), cost_class="repair")
    assert done and order.cost_class == "repair" and order.completion_notes == "Replaced trap"
    event = next(o for o in db.added if isinstance(o, MaintEvent))
    assert event.payload == {"work_order": "MT-00001-W1", "cost_actual": "180.00", "cost_class": "repair"}
    with pytest.raises(ValueError, match="already closed"):
        await complete_work_order(db, ticket, order, ACTOR, completion_notes="again")  # type: ignore[arg-type]
    other = SimpleNamespace(**{**order.__dict__, "status": MaintWorkOrderStatus.IN_PROGRESS})
    with pytest.raises(ValueError, match="repair or capital"):
        await complete_work_order(db, ticket, other, ACTOR, completion_notes="x", cost_class="opex")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_final_cost_can_be_recorded_after_vendor_completion_only() -> None:
    db, ticket = EventDb(), open_ticket()
    order = SimpleNamespace(id=uuid4(), ticket_id=ticket.id, number="W1", status=MaintWorkOrderStatus.IN_PROGRESS,
                            cost_actual=None, cost_class=None)
    with pytest.raises(ValueError, match="Complete the work order"):
        await record_work_order_costs(db, ticket, order, ACTOR, cost_actual=Decimal("1"), cost_class=None)  # type: ignore[arg-type]
    order.status = MaintWorkOrderStatus.COMPLETED
    await record_work_order_costs(db, ticket, order, ACTOR, cost_actual=Decimal("612.4"), cost_class="capital")  # type: ignore[arg-type]
    assert order.cost_actual == Decimal("612.4") and order.cost_class == "capital"
    event = next(o for o in db.added if isinstance(o, MaintEvent))
    assert event.event_type == "work_order_costs_updated" and event.payload["cost_actual"] == "612.40"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [MaintStatus.CANCELLED, MaintStatus.DUPLICATE])
async def test_duplicate_target_cannot_be_cancelled_or_duplicate(status) -> None:
    ticket = SimpleNamespace(id=uuid4(), status=MaintStatus.NEW, duplicate_of=None)
    canonical = SimpleNamespace(id=uuid4(), status=status, number="MT-2")
    with pytest.raises(ValueError, match="cannot be cancelled or duplicate"):
        await mark_duplicate(EventDb(), ticket, canonical, ACTOR)  # type: ignore[arg-type]
    assert ticket.duplicate_of is None


@pytest.mark.asyncio
async def test_related_tickets_flag_same_unit_first() -> None:
    current = SimpleNamespace(id=uuid4(), property_id=1, unit_id=2)
    rows = [SimpleNamespace(id=uuid4(), number=f"MT-{n}", title=f"T{n}", status=MaintStatus.CLOSED, category="pests",
                            created_at=T0, unit_id=u) for n, u in ((1, 3), (2, 2), (3, None))]
    units = [SimpleNamespace(id=2, unit_label="Up"), SimpleNamespace(id=3, unit_label="Down")]
    queries = []

    class Db:
        async def scalars(self, query):
            queries.append(str(query))
            return SimpleNamespace(all=lambda: rows if len(queries) == 1 else units)

    result = await related_tickets(Db(), current)  # type: ignore[arg-type]
    assert [(r["number"], r["same_unit"], r["unit"]) for r in result] == [
        ("MT-2", True, "Up"), ("MT-1", False, "Down"), ("MT-3", False, "Main building")]
    assert "maint_tickets.id !=" in queries[0] and "LIMIT" in queries[0]


@pytest.mark.asyncio
async def test_list_assignee_filter_uses_non_cancelled_work_orders() -> None:
    seen = []

    class Db:
        async def scalars(self, query):
            seen.append(query)
            return SimpleNamespace(all=lambda: [])

    assert await list_ticket_views(Db(), assignee_id=uuid4()) == []  # type: ignore[arg-type]
    sql = str(seen[0])
    assert "maint_work_orders.assignee_user_id" in sql and "maint_work_orders.vendor_id" in sql
    assert "maint_work_orders.status !=" in sql


@pytest.fixture
def api(monkeypatch):
    app = FastAPI(); app.include_router(router)

    class Db:
        async def get(self, model, key):
            return None

        async def rollback(self):
            return None

    async def dep():
        yield Db()

    app.dependency_overrides[get_db] = dep
    monkeypatch.setattr(settings, "auth_enforced", False)
    return app


async def call(app, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.request(method, path, **kw)


@pytest.mark.asyncio
async def test_complete_endpoint_requires_notes_and_valid_cost_class(api) -> None:
    path = f"/api/maintenance/tickets/{uuid4()}/work-orders/{uuid4()}/complete"
    assert (await call(api, "POST", path, json={"completion_notes": "  "})).status_code == 422
    assert (await call(api, "POST", path, json={"completion_notes": "ok", "cost_class": "opex"})).status_code == 422
    assert (await call(api, "POST", path, json={"completion_notes": "ok", "cost_actual": "-1"})).status_code == 422
    assert (await call(api, "POST", path, json={"completion_notes": "ok", "cost_class": "repair"})).status_code == 404


@pytest.mark.asyncio
async def test_spend_report_json_and_csv(api, monkeypatch) -> None:
    async def lines(db, property_id=None):
        return [line(datetime(2026, 10, 10, 18, tzinfo=timezone.utc), "99.99")]

    monkeypatch.setattr("app.routers.maintenance.spend_lines", lines)
    r = await call(api, "GET", "/api/maintenance/reports/spend?start=2026-10-01&end=2026-10-31")
    assert r.status_code == 200 and r.json()["totals"]["cost_actual"] == "99.99"
    csv_r = await call(api, "GET", "/api/maintenance/reports/spend?format=csv&group_by=unit")
    assert csv_r.headers["content-type"].startswith("text/csv") and "2026-10,1 Test St,A,1" in csv_r.text
    bad = await call(api, "GET", "/api/maintenance/reports/spend?start=2026-10-31&end=2026-10-01")
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_new_staff_endpoints_require_permission_when_auth_enforced(api, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", True)
    tid = uuid4()
    for method, path, body in [
        ("GET", "/api/maintenance/reports/spend", None),
        ("GET", "/api/maintenance/filter-options", None),
        ("POST", f"/api/maintenance/tickets/{tid}/checklist", {"items": ["a"]}),
        ("POST", f"/api/maintenance/tickets/{tid}/checklist/{uuid4()}", {"done": True}),
        ("POST", f"/api/maintenance/tickets/{tid}/purchases", {"vendor": "a", "item": "b"}),
        ("POST", f"/api/maintenance/tickets/{tid}/purchases/{uuid4()}", {"status": "received"}),
        ("POST", f"/api/maintenance/tickets/{tid}/work-orders/{uuid4()}/costs", {"cost_actual": "1"}),
    ]:
        r = await call(api, method, path, json=body)
        assert r.status_code == 403, (path, r.status_code)
