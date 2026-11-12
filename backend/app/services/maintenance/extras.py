"""Maintenance P1/P2 helpers: checklists, purchase notes, unit history, spend report.

Checklist items and purchase notes are stored as append-only ``MaintEvent`` rows
(no new tables), and their current state is rebuilt by replaying those events.
That keeps the timeline the single audit log and needs no schema migration.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintStatus,
    MaintTicket,
    MaintVisibility,
    MaintWorkOrder,
    MaintWorkOrderStatus,
)
from app.models.rentals import RentalProperty, RentalUnit
from app.services.maintenance.state_machine import ActorContext

LOCAL_TZ = ZoneInfo("America/Winnipeg")
LOCKED_STATUSES = {MaintStatus.CLOSED, MaintStatus.CANCELLED, MaintStatus.DUPLICATE}

CHECKLIST_ADDED = "checklist_item_added"
CHECKLIST_UPDATED = "checklist_item_updated"
CHECKLIST_REMOVED = "checklist_item_removed"
CHECKLIST_EVENTS = (CHECKLIST_ADDED, CHECKLIST_UPDATED, CHECKLIST_REMOVED)
MAX_CHECKLIST_ITEMS = 50

PURCHASE_LOGGED = "purchase_logged"
PURCHASE_STATUS = "purchase_status_changed"
PURCHASE_EVENTS = (PURCHASE_LOGGED, PURCHASE_STATUS)
PurchaseStatus = Literal["needed", "ordered", "received", "cancelled"]
PURCHASE_STATUSES: tuple[str, ...] = ("needed", "ordered", "received", "cancelled")


def _status(value: object) -> MaintStatus:
    return MaintStatus(getattr(value, "value", value))


def _ensure_editable(ticket: MaintTicket) -> None:
    if _status(ticket.status) in LOCKED_STATUSES:
        raise ValueError("Reopen this ticket before changing it")


def _event(ticket: MaintTicket, actor: ActorContext, event_type: str, body: str, payload: dict[str, object],
           *, work_order_id: UUID | None = None, now: datetime | None = None) -> MaintEvent:
    return MaintEvent(
        ticket_id=ticket.id,
        work_order_id=work_order_id,
        event_type=event_type,
        channel=MaintEventChannel.WEB,
        visibility=MaintVisibility.INTERNAL,
        direction=MaintDirection.NONE,
        actor_party=actor.party if actor.party else MaintParty.STAFF,
        actor_user_id=actor.user_id,
        body=body,
        payload=payload,
        created_at=now or datetime.now(timezone.utc),
    )


async def _ticket_events(db: AsyncSession, ticket_ids: Sequence[UUID], types: Iterable[str]) -> list[MaintEvent]:
    if not ticket_ids:
        return []
    return list((await db.scalars(
        select(MaintEvent)
        .where(MaintEvent.ticket_id.in_(list(ticket_ids)), MaintEvent.event_type.in_(list(types)))
        .order_by(MaintEvent.created_at, MaintEvent.id)
    )).all())


# --- Checklist -------------------------------------------------------------

def replay_checklist(events: Iterable[MaintEvent]) -> list[dict[str, object]]:
    """Rebuild current checklist items from ordered checklist events."""
    items: dict[str, dict[str, object]] = {}
    for event in events:
        payload = event.payload or {}
        if event.event_type == CHECKLIST_ADDED and isinstance(payload.get("items"), list):
            for entry in payload["items"]:  # bulk add: one audit event for a pasted punch list
                if isinstance(entry, dict) and entry.get("item_id"):
                    items[str(entry["item_id"])] = {"id": str(entry["item_id"]), "text": str(entry.get("text") or ""),
                                                    "done": False, "position": len(items), "done_at": None}
            continue
        item_id = str(payload.get("item_id") or "")
        if not item_id:
            continue
        if event.event_type == CHECKLIST_ADDED:
            items[item_id] = {"id": item_id, "text": str(payload.get("text") or ""), "done": False,
                              "position": len(items), "done_at": None}
        elif item_id not in items:
            continue
        elif event.event_type == CHECKLIST_UPDATED:
            if "done" in payload:
                items[item_id]["done"] = bool(payload["done"])
                items[item_id]["done_at"] = event.created_at if payload["done"] else None
            if payload.get("text"):
                items[item_id]["text"] = str(payload["text"])
        elif event.event_type == CHECKLIST_REMOVED:
            items.pop(item_id)
    return sorted(items.values(), key=lambda item: int(item["position"]))  # type: ignore[arg-type]


def checklist_progress(items: Sequence[dict[str, object]]) -> dict[str, int]:
    return {"total": len(items), "done": sum(1 for item in items if item["done"])}


async def ticket_checklist(db: AsyncSession, ticket_id: UUID) -> list[dict[str, object]]:
    return replay_checklist(await _ticket_events(db, [ticket_id], CHECKLIST_EVENTS))


async def checklist_progress_by_ticket(db: AsyncSession, ticket_ids: Sequence[UUID]) -> dict[UUID, dict[str, int]]:
    grouped: dict[UUID, list[MaintEvent]] = {}
    for event in await _ticket_events(db, ticket_ids, CHECKLIST_EVENTS):
        grouped.setdefault(event.ticket_id, []).append(event)
    return {ticket_id: checklist_progress(replay_checklist(events)) for ticket_id, events in grouped.items()}


def parse_checklist_lines(text: str) -> list[str]:
    """Split pasted punch-list text into items, dropping bullets/numbering and blanks."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        for prefix in ("- [ ]", "- [x]", "* ", "- ", "• ", "[ ]"):
            if line.lower().startswith(prefix):
                line = line[len(prefix):].strip()
                break
        head, _, rest = line.partition(" ")
        if rest and head.rstrip(".)").isdigit() and head[-1:] in {".", ")"}:
            line = rest.strip()
        if line:
            lines.append(line[:300])
    return lines


async def add_checklist_items(db: AsyncSession, ticket: MaintTicket, actor: ActorContext, texts: Sequence[str],
                              *, now: datetime | None = None) -> list[dict[str, object]]:
    _ensure_editable(ticket)
    cleaned = [text.strip()[:300] for text in texts if text and text.strip()]
    if not cleaned:
        raise ValueError("Add at least one checklist item")
    current = await ticket_checklist(db, ticket.id)
    if len(current) + len(cleaned) > MAX_CHECKLIST_ITEMS:
        raise ValueError(f"A ticket can have at most {MAX_CHECKLIST_ITEMS} checklist items")
    if len(cleaned) == 1:
        db.add(_event(ticket, actor, CHECKLIST_ADDED, f"Checklist item added: {cleaned[0]}",
                      {"item_id": str(uuid4()), "text": cleaned[0]}, now=now))
    else:
        body = f"Checklist: {len(cleaned)} items added\n" + "\n".join(f"• {text}" for text in cleaned)
        db.add(_event(ticket, actor, CHECKLIST_ADDED, body,
                      {"items": [{"item_id": str(uuid4()), "text": text} for text in cleaned]}, now=now))
    await db.flush()
    return await ticket_checklist(db, ticket.id)


async def update_checklist_item(db: AsyncSession, ticket: MaintTicket, actor: ActorContext, item_id: str, *,
                                done: bool | None = None, remove: bool = False,
                                now: datetime | None = None) -> list[dict[str, object]]:
    _ensure_editable(ticket)
    current = {str(item["id"]): item for item in await ticket_checklist(db, ticket.id)}
    item = current.get(item_id)
    if item is None:
        raise ValueError("Checklist item not found")
    if remove:
        db.add(_event(ticket, actor, CHECKLIST_REMOVED, f"Checklist item removed: {item['text']}",
                      {"item_id": item_id}, now=now))
    elif done is not None and bool(item["done"]) != done:
        verb = "done" if done else "reopened"
        db.add(_event(ticket, actor, CHECKLIST_UPDATED, f"Checklist item {verb}: {item['text']}",
                      {"item_id": item_id, "done": done}, now=now))
    await db.flush()
    return await ticket_checklist(db, ticket.id)


# --- Purchases -------------------------------------------------------------

def replay_purchases(events: Iterable[MaintEvent]) -> list[dict[str, object]]:
    purchases: dict[str, dict[str, object]] = {}
    for event in events:
        payload = event.payload or {}
        purchase_id = str(payload.get("purchase_id") or "")
        if not purchase_id:
            continue
        if event.event_type == PURCHASE_LOGGED:
            purchases[purchase_id] = {
                "id": purchase_id,
                "vendor": payload.get("vendor"),
                "item": payload.get("item"),
                "amount": payload.get("amount"),
                "status": payload.get("status") or "ordered",
                "reference": payload.get("reference"),
                "work_order_id": payload.get("work_order_id"),
                "logged_at": event.created_at,
                "updated_at": event.created_at,
            }
        elif event.event_type == PURCHASE_STATUS and purchase_id in purchases:
            purchases[purchase_id]["status"] = payload.get("status")
            purchases[purchase_id]["updated_at"] = event.created_at
    return list(purchases.values())


async def ticket_purchases(db: AsyncSession, ticket_id: UUID) -> list[dict[str, object]]:
    return replay_purchases(await _ticket_events(db, [ticket_id], PURCHASE_EVENTS))


def _money(amount: Decimal | None) -> str | None:
    return None if amount is None else str(amount.quantize(Decimal("0.01")))


async def log_purchase(db: AsyncSession, ticket: MaintTicket, actor: ActorContext, *, vendor: str, item: str,
                       amount: Decimal | None, status: str, reference: str | None,
                       work_order_id: UUID | None, now: datetime | None = None) -> list[dict[str, object]]:
    _ensure_editable(ticket)
    if status not in PURCHASE_STATUSES:
        raise ValueError("Unsupported purchase status")
    if work_order_id is not None:
        order = await db.get(MaintWorkOrder, work_order_id)
        if order is None or order.ticket_id != ticket.id:
            raise ValueError("Work order not found on this ticket")
    vendor, item = vendor.strip(), item.strip()
    if not vendor or not item:
        raise ValueError("Vendor and item are required")
    amount_text = _money(amount)
    body = f"Purchase {status}: {item} from {vendor}" + (f" (${amount_text})" if amount_text else "")
    db.add(_event(ticket, actor, PURCHASE_LOGGED, body, {
        "purchase_id": str(uuid4()), "vendor": vendor, "item": item, "amount": amount_text, "status": status,
        "reference": (reference or "").strip() or None,
        "work_order_id": str(work_order_id) if work_order_id else None,
    }, work_order_id=work_order_id, now=now))
    await db.flush()
    return await ticket_purchases(db, ticket.id)


async def set_purchase_status(db: AsyncSession, ticket: MaintTicket, actor: ActorContext, purchase_id: str,
                              status: str, *, now: datetime | None = None) -> list[dict[str, object]]:
    _ensure_editable(ticket)
    if status not in PURCHASE_STATUSES:
        raise ValueError("Unsupported purchase status")
    current = {str(item["id"]): item for item in await ticket_purchases(db, ticket.id)}
    purchase = current.get(purchase_id)
    if purchase is None:
        raise ValueError("Purchase not found")
    if purchase["status"] != status:
        db.add(_event(ticket, actor, PURCHASE_STATUS, f"Purchase {status}: {purchase['item']}",
                      {"purchase_id": purchase_id, "status": status}, now=now))
        await db.flush()
    return await ticket_purchases(db, ticket.id)


# --- Unit / property history ----------------------------------------------

async def related_tickets(db: AsyncSession, ticket: MaintTicket, *, limit: int = 10) -> list[dict[str, object]]:
    """Recent other tickets at the same property, same-unit ones flagged (pest/leak recurrence)."""
    rows = list((await db.scalars(
        select(MaintTicket)
        .where(MaintTicket.property_id == ticket.property_id, MaintTicket.id != ticket.id)
        .order_by(MaintTicket.created_at.desc())
        .limit(limit)
    )).all())
    units = {unit.id: unit for unit in (await db.scalars(
        select(RentalUnit).where(RentalUnit.id.in_([row.unit_id for row in rows if row.unit_id]))
    )).all()} if any(row.unit_id for row in rows) else {}
    result = []
    for row in rows:
        unit = units.get(row.unit_id) if row.unit_id else None
        result.append({
            "id": row.id,
            "number": row.number,
            "title": row.title,
            "status": getattr(row.status, "value", row.status),
            "category": getattr(row.category, "value", row.category),
            "created_at": row.created_at,
            "unit": unit.unit_label if unit and unit.unit_label else "Main building",
            "same_unit": bool(ticket.unit_id) and row.unit_id == ticket.unit_id,
        })
    result.sort(key=lambda item: (not item["same_unit"],))
    return result


# --- Spend report -----------------------------------------------------------

@dataclass(frozen=True)
class SpendLine:
    property_id: int
    property: str
    unit_id: int | None
    unit: str
    cost_estimate: Decimal | None
    cost_actual: Decimal | None
    cost_class: str | None
    when: datetime


def _local_day(value: datetime) -> date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(LOCAL_TZ).date()


def aggregate_spend(lines: Iterable[SpendLine], *, group_by: Literal["property", "unit"] = "property",
                    start: date | None = None, end: date | None = None) -> list[dict[str, object]]:
    """Sum estimates and actuals by month and property (or unit). Dates are Winnipeg local; end inclusive."""
    buckets: dict[tuple[str, int, int | None], dict[str, object]] = {}
    zero = Decimal("0.00")
    for line in lines:
        day = _local_day(line.when)
        if (start and day < start) or (end and day > end):
            continue
        month = f"{day.year:04d}-{day.month:02d}"
        unit_key = line.unit_id if group_by == "unit" else None
        key = (month, line.property_id, unit_key)
        bucket = buckets.setdefault(key, {
            "month": month, "property_id": line.property_id, "property": line.property,
            "unit_id": unit_key, "unit": line.unit if group_by == "unit" else None,
            "work_orders": 0, "cost_estimate": zero, "cost_actual": zero,
            "repair_actual": zero, "capital_actual": zero, "unclassified_actual": zero,
        })
        bucket["work_orders"] = int(bucket["work_orders"]) + 1  # type: ignore[arg-type]
        if line.cost_estimate is not None:
            bucket["cost_estimate"] = bucket["cost_estimate"] + line.cost_estimate  # type: ignore[operator]
        if line.cost_actual is not None:
            bucket["cost_actual"] = bucket["cost_actual"] + line.cost_actual  # type: ignore[operator]
            field = {"repair": "repair_actual", "capital": "capital_actual"}.get(line.cost_class or "", "unclassified_actual")
            bucket[field] = bucket[field] + line.cost_actual  # type: ignore[operator]
    rows = sorted(buckets.values(), key=lambda row: (row["month"], str(row["property"]), str(row["unit"] or "")))
    for row in rows:
        for field in ("cost_estimate", "cost_actual", "repair_actual", "capital_actual", "unclassified_actual"):
            row[field] = str(Decimal(row[field]).quantize(Decimal("0.01")))  # type: ignore[arg-type]
    return rows


async def spend_lines(db: AsyncSession, *, property_id: int | None = None) -> list[SpendLine]:
    statement = (
        select(MaintWorkOrder, MaintTicket, RentalProperty, RentalUnit)
        .join(MaintTicket, MaintTicket.id == MaintWorkOrder.ticket_id)
        .join(RentalProperty, RentalProperty.id == MaintTicket.property_id)
        .outerjoin(RentalUnit, RentalUnit.id == MaintTicket.unit_id)
        .where(MaintWorkOrder.status != MaintWorkOrderStatus.CANCELLED)
        .where(or_(MaintWorkOrder.cost_actual.is_not(None), MaintWorkOrder.cost_estimate.is_not(None)))
    )
    if property_id is not None:
        statement = statement.where(MaintTicket.property_id == property_id)
    lines = []
    for order, ticket, prop, unit in (await db.execute(statement)).all():
        lines.append(SpendLine(
            property_id=prop.id,
            property=prop.street_address,
            unit_id=unit.id if unit else None,
            unit=(unit.unit_label if unit and unit.unit_label else "Main building"),
            cost_estimate=order.cost_estimate,
            cost_actual=order.cost_actual,
            cost_class=order.cost_class,
            when=order.completed_at or order.created_at or ticket.created_at,
        ))
    return lines


SPEND_CSV_FIELDS = ("month", "property", "unit", "work_orders", "cost_estimate", "cost_actual",
                    "repair_actual", "capital_actual", "unclassified_actual")


def spend_csv(rows: Sequence[dict[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SPEND_CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        safe = dict(row)
        for field in ("property", "unit"):
            text = str(safe.get(field) or "")
            safe[field] = f"'{text}" if text[:1] in {"=", "+", "-", "@"} else text
        writer.writerow(safe)
    return buffer.getvalue()


# --- Work order costs and invoices -----------------------------------------

async def record_work_order_costs(db: AsyncSession, ticket: MaintTicket, order: MaintWorkOrder, actor: ActorContext,
                                  *, cost_actual: Decimal | None, cost_class: str | None,
                                  now: datetime | None = None) -> None:
    """Record the final cost on a completed work order (e.g. a vendor invoice arriving later)."""
    if order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    if MaintWorkOrderStatus(getattr(order.status, "value", order.status)) != MaintWorkOrderStatus.COMPLETED:
        raise ValueError("Complete the work order before recording its final cost")
    if cost_class is not None and cost_class not in {"repair", "capital"}:
        raise ValueError("Cost class must be repair or capital")
    previous = {"cost_actual": _money(order.cost_actual), "cost_class": order.cost_class}
    order.cost_actual = cost_actual
    order.cost_class = cost_class
    amount = _money(cost_actual)
    body = f"Final cost for {order.number}: " + (f"${amount}" if amount else "cleared") + (f" ({cost_class})" if cost_class else "")
    db.add(_event(ticket, actor, "work_order_costs_updated", body,
                  {"work_order": order.number, "cost_actual": amount, "cost_class": cost_class, "previous": previous},
                  work_order_id=order.id, now=now))
    await db.flush()


async def attach_invoice(db: AsyncSession, ticket: MaintTicket, order: MaintWorkOrder, actor: ActorContext,
                         *, content: bytes, filename: str | None, now: datetime | None = None) -> UUID:
    from app.services.maintenance.media import store_attachment

    if order.ticket_id != ticket.id:
        raise ValueError("Work order not found")
    _ensure_editable(ticket)
    event = _event(ticket, actor, "invoice_attached", f"Invoice attached to {order.number}",
                   {"work_order": order.number, "filename": filename}, work_order_id=order.id, now=now)
    db.add(event)
    await db.flush()
    attachment = await store_attachment(
        db,
        ticket_id=ticket.id,
        content=content,
        original_filename=filename,
        uploaded_by_party=MaintParty.STAFF,
        kind="invoice",
        work_order_id=order.id,
        event_id=event.id,
    )
    order.invoice_attachment_id = attachment.id
    await db.flush()
    return attachment.id
