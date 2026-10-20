"""Daily gap checks and signed-closing-document watch."""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Lot
from app.models.financing import ConstructionStageSync, FacilityStatementSnapshot, LenderFacility, LenderStatement, Property
from app.models.funds import FundsAttachment, FundsBoxWatch, FundsEntry, FundsNotice, FundsTask
from app.models.land import DepositSchedule
from app.models.sales import SalesAgreement
from app.services.box import get_box_client
from app.services.funds_intake import _date, _money, extract_notice, nicholas_user_id, resolve_legal_folder
from app.services.minio_financing import upload_financing_document


async def _task(db: AsyncSession, key: str, title: str, kind: str,
                *, lot_id=None, notice_id=None, payload=None, due_at=None) -> None:
    db.info.setdefault("funds_active_task_keys", set()).add(key)
    existing = await db.scalar(select(FundsTask).where(FundsTask.task_key == key))
    if existing:
        if existing.status != "open":
            existing.status = "open"
            existing.completed_at = None
        existing.title = title
        existing.payload = {"assignee_name": "Nicholas", **(payload or {})}
        return
    db.add(FundsTask(task_key=key, title=title, task_type=kind, lot_id=lot_id,
                     assignee_id=await nicholas_user_id(db),
                     notice_id=notice_id, payload={"assignee_name": "Nicholas", **(payload or {})},
                     due_at=due_at))


async def run_gap_checks(db: AsyncSession, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    db.info["funds_active_task_keys"] = set()
    counts = {"statement_without_notice": 0, "overdue_deposit": 0,
              "sold_open_facility": 0, "no_statement_activity": 0,
              "past_estimated_possession": 0, "closing_docs_overdue": 0}
    snapshots = list((await db.scalars(select(FacilityStatementSnapshot))).all())
    entries = list((await db.scalars(select(FundsEntry).where(FundsEntry.funds_type == "pro_draw"))).all())
    seen_draw_keys = set()
    for snapshot in snapshots:
        if not snapshot.facility_id:
            continue
        for draw in (snapshot.parse_payload or {}).get("draws", []):
            txn_date = _date(draw.get("txn_date") or draw.get("date"))
            amount = _money(draw.get("amount"))
            if not txn_date or amount is None:
                continue
            cheque = _cheque(draw.get("reference"))
            key = (snapshot.facility_id, txn_date, amount, cheque)
            if key in seen_draw_keys:
                continue
            seen_draw_keys.add(key)
            matched = any(e.facility_id == snapshot.facility_id and e.amount == amount and
                          ((_cheque(e.cheque_number) == cheque) if cheque else e.txn_date == txn_date)
                          for e in entries)
            if not matched:
                counts["statement_without_notice"] += 1
                await _task(db, f"pro-no-notice:{snapshot.facility_id}:{txn_date}:{amount}:{cheque or ''}",
                            f"PRO draw without lawyer notice — {snapshot.matched_property_name} — ${amount:,.2f}",
                            "statement_without_notice", payload={"statement_id": str(snapshot.statement_id),
                                "facility_id": str(snapshot.facility_id), "date": txn_date.isoformat(), "cheque": cheque})

    deposits = list((await db.scalars(select(DepositSchedule).where(
        DepositSchedule.due_date < today, DepositSchedule.paid_at.is_(None)))).all())
    for schedule in deposits:
        counts["overdue_deposit"] += 1
        lot = await db.get(Lot, schedule.lot_id)
        address = lot.civic_address if lot else str(schedule.lot_id)
        await _task(db, f"overdue-deposit:{schedule.id}",
                    f"Overdue land deposit #{schedule.deposit_number} — {address}", "overdue_deposit",
                    lot_id=schedule.lot_id, payload={"amount": str(schedule.amount),
                        "due_date": schedule.due_date.isoformat() if schedule.due_date else None})

    facilities = list((await db.scalars(select(LenderFacility).where(
        LenderFacility.lot_id.is_not(None),
        LenderFacility.status.notin_(["closed", "discharged", "statement_only", "closing_pending"])))).all())
    for facility in facilities:
        lot = await db.get(Lot, facility.lot_id)
        if lot and lot.closing_date:
            counts["sold_open_facility"] += 1
            await _task(db, f"sold-open-facility:{facility.id}",
                        f"Sold lot has open facility — {lot.civic_address or facility.property_name}",
                        "sold_open_facility", lot_id=lot.id,
                        payload={"facility_id": str(facility.id)})

    statements = list((await db.scalars(select(LenderStatement).where(
        LenderStatement.lender == "PRO").order_by(LenderStatement.period.desc()).limit(2))).all())
    if len(statements) == 2:
        last_period = max((s.reported_period_end_date for s in snapshots if s.statement_id == statements[0].id), default=None)
        seen = {s.facility_id for s in snapshots if s.statement_id in {statements[0].id, statements[1].id}}
        if last_period:
            for facility in facilities:
                if facility.lender_type != "PRO" or facility.id in seen:
                    continue
                if facility.original_advance_date and facility.original_advance_date <= last_period:
                    counts["no_statement_activity"] += 1
                    await _task(db, f"no-statement-activity:{facility.id}",
                                f"PRO facility absent from two statements — {facility.property_name or facility.facility_key}",
                                "no_statement_activity", lot_id=facility.lot_id,
                                payload={"facility_id": str(facility.id), "last_period": statements[0].period})

    agreements = list((await db.scalars(select(SalesAgreement))).all())
    seen_lots = set()
    for agreement in agreements:
        if agreement.lot_id in seen_lots:
            continue
        seen_lots.add(agreement.lot_id)
        lot = await db.get(Lot, agreement.lot_id)
        stage = await db.scalar(select(ConstructionStageSync).where(
            ConstructionStageSync.property_id == lot.property_id)) if lot and lot.property_id else None
        expected = stage.possession_date if stage and stage.possession_date else agreement.possession_date
        if lot and expected and expected < today and not lot.possession_confirmed_date and not lot.closing_date:
            counts["past_estimated_possession"] += 1
            await _task(db, f"possession-overdue:{lot.id}",
                        f"Confirm possession — {lot.civic_address or lot.legal_description_raw}",
                        "past_estimated_possession", lot_id=lot.id,
                        payload={"estimated_date": expected.isoformat(),
                                 "tracker_date_locked": bool(stage.possession_date_locked) if stage else False})

    watches = list((await db.scalars(select(FundsBoxWatch).where(FundsBoxWatch.status == "watching"))).all())
    for watch in watches:
        if watch.possession_date + timedelta(days=watch.escalate_after_days) < today:
            found = await db.scalar(select(FundsNotice.id).where(
                FundsNotice.lot_id == watch.lot_id,
                FundsNotice.capture_source == "box_watch").limit(1))
            if found:
                continue
            counts["closing_docs_overdue"] += 1
            lot = await db.get(Lot, watch.lot_id)
            await _task(db, f"closing-docs-overdue:{watch.lot_id}",
                        f"Signed closing docs overdue — {lot.civic_address if lot else watch.lot_id}",
                        "closing_docs_overdue", lot_id=watch.lot_id)
    active_keys = db.info["funds_active_task_keys"]
    automated_types = list(counts)
    old_tasks = list((await db.scalars(select(FundsTask).where(
        FundsTask.task_type.in_(automated_types), FundsTask.status == "open"))).all())
    for task in old_tasks:
        if task.task_key not in active_keys:
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return counts


def _cheque(value: object) -> str | None:
    match = re.search(r"\b\d{4,8}\b", str(value or ""))
    return match.group(0) if match else None


async def scan_closing_folders(db: AsyncSession) -> dict[str, int]:
    watches = list((await db.scalars(select(FundsBoxWatch).where(FundsBoxWatch.status == "watching"))).all())
    client = await asyncio.to_thread(get_box_client)
    if client is None:
        for watch in watches:
            watch.last_error = "Box unavailable"
        await db.commit()
        return {"watched": len(watches), "ingested": 0}
    ingested = 0
    notice_ids = []
    for watch in watches:
        try:
            open_facilities = list((await db.scalars(select(LenderFacility.id).where(
                LenderFacility.lot_id == watch.lot_id,
                LenderFacility.status.notin_(["closed", "discharged", "statement_only"])))).all())
            if not open_facilities:
                watch.status = "completed"
                continue
            lot = await db.get(Lot, watch.lot_id)
            property_row = await db.get(Property, lot.property_id) if lot and lot.property_id else None
            if property_row is None:
                watch.last_error = "No property address linked to lot"
                continue
            folder_id = watch.folder_id or await asyncio.to_thread(resolve_legal_folder, client, property_row.address)
            if not folder_id:
                watch.last_error = "Legal folder not found unambiguously"
                continue
            watch.folder_id = folder_id
            items = await asyncio.to_thread(lambda: list(client.folder(folder_id).get_items(
                limit=1000, fields=["id", "name", "type", "created_at"])))
            for item in items:
                if item.type != "file" or not item.name.lower().endswith(".pdf"):
                    continue
                if not re.search(r"adjustment|discharge|payout|transfer|closing", item.name, re.I):
                    continue
                content = await asyncio.to_thread(lambda: client.file(str(item.id)).content())
                digest = hashlib.sha256(content).hexdigest()
                if await db.scalar(select(FundsAttachment.id).where(FundsAttachment.file_sha256 == digest)):
                    continue
                notice = FundsNotice(property_id=property_row.id, lot_id=lot.id,
                                     capture_source="box_watch", status="pending_extraction",
                                     email_subject=f"Closing documents — {property_row.address}")
                db.add(notice)
                await db.flush()
                key = f"lawyer-funds/{notice.id}/{digest}.pdf"
                await asyncio.to_thread(upload_financing_document, key=key, content=content, content_type="application/pdf")
                db.add(FundsAttachment(notice_id=notice.id, file_sha256=digest, file_key=key,
                                       original_filename=item.name, mime="application/pdf",
                                       box_file_id=str(item.id), box_file_url=f"https://app.box.com/file/{item.id}",
                                       box_filing_status="filed"))
                db.add(FundsTask(task_key=f"notice:{notice.id}", notice_id=notice.id, lot_id=lot.id,
                                 task_type="review_notice", title=f"Funds notice — {property_row.address} — closing document",
                                 assignee_id=await nicholas_user_id(db),
                                 payload={"assignee_name": "Nicholas", "source": "box_watch"}))
                notice_ids.append(notice.id)
                ingested += 1
            watch.last_checked_at = datetime.now(timezone.utc)
            watch.last_error = None
        except Exception as exc:
            watch.last_error = str(exc)[:500]
    await db.commit()
    for notice_id in notice_ids:
        await extract_notice(notice_id)
    return {"watched": len(watches), "ingested": ingested}
