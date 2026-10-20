"""Review and atomically promote lawyer funds entries to operational records."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Lot, LotStatus
from app.models.financing import FacilityStatementSnapshot, FacilityTransaction, LenderFacility
from app.models.funds import FundsAttachment, FundsBoxWatch, FundsEntry, FundsNotice, FundsTask
from app.models.land import DepositSchedule
from app.models.lenders import Lender
from app.models.sales import SalesAgreement
from app.services.funds_intake import _date, _money
from app.services.promotion import PromotionService


def _cheque(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?:#|CHEQUE\s*#?\s*)?(\d{4,8})", value, re.I)
    return match.group(1) if match else None


async def statement_match(db: AsyncSession, entry: FundsEntry) -> tuple[FacilityStatementSnapshot, object] | None:
    if not entry.facility_id:
        return None
    snapshots = list((await db.scalars(select(FacilityStatementSnapshot).where(
        FacilityStatementSnapshot.facility_id == entry.facility_id))).all())
    candidates = []
    for snapshot in snapshots:
        for draw in (snapshot.parse_payload or {}).get("draws", []):
            if _money(draw.get("amount")) != entry.amount:
                continue
            if entry.cheque_number:
                matches = _cheque(draw.get("reference")) == _cheque(entry.cheque_number)
            else:
                matches = _date(draw.get("txn_date") or draw.get("date")) == entry.txn_date
            if matches:
                candidates.append((snapshot, draw))
    # A draw can appear again on later monthly statements; use its first report.
    candidates.sort(key=lambda pair: pair[0].reported_period_end_date)
    return candidates[0] if candidates else None


async def preview_entry(db: AsyncSession, entry: FundsEntry) -> dict:
    flags = list(entry.review_flags or [])
    match: dict | None = None
    if entry.funds_type == "lot_deposit" and entry.lot_id and entry.deposit_ordinal:
        schedule = await db.scalar(select(DepositSchedule).where(
            DepositSchedule.lot_id == entry.lot_id,
            DepositSchedule.deposit_number == entry.deposit_ordinal).order_by(DepositSchedule.created_at.desc()))
        if schedule:
            match = {"kind": "deposit_obligation", "id": str(schedule.id),
                     "scheduled_amount": str(schedule.amount), "paid_amount": str(schedule.paid_amount) if schedule.paid_amount is not None else None}
            if entry.amount != schedule.amount:
                flags.append("deposit_amount_variance")
            if schedule.paid_at:
                flags.append("obligation_already_paid")
        else:
            flags.append("deposit_obligation_missing")
    elif entry.funds_type == "pro_draw" and entry.facility_id:
        found = await statement_match(db, entry)
        if found:
            match = {"kind": "pro_statement", "statement_id": str(found[0].statement_id),
                     "snapshot_id": str(found[0].id), "line": found[1]}
        else:
            flags.append("awaiting_pro_statement")
    elif entry.funds_type == "statement_of_adjustments":
        flags.extend(await _closing_flags(db, entry))
    return {"id": str(entry.id), "notice_id": str(entry.notice_id),
            "attachment_id": str(entry.attachment_id), "property_id": str(entry.property_id) if entry.property_id else None,
            "lot_id": str(entry.lot_id) if entry.lot_id else None,
            "facility_id": str(entry.facility_id) if entry.facility_id else None,
            "funds_type": entry.funds_type, "deposit_ordinal": entry.deposit_ordinal,
            "property_address": entry.property_address, "amount": str(entry.amount) if entry.amount is not None else None,
            "cheque_number": entry.cheque_number, "txn_date": entry.txn_date.isoformat() if entry.txn_date else None,
            "payee": entry.payee, "memo": entry.memo, "closing": entry.closing,
            "status": entry.status, "match": match, "flags": list(dict.fromkeys(flags)),
            "posting_result": entry.posting_result}


async def _closing_flags(db: AsyncSession, entry: FundsEntry) -> list[str]:
    closing = entry.closing or {}
    flags = []
    if not entry.lot_id or not closing.get("closing_date") or closing.get("closing_type") not in {"sale", "refinance"}:
        return ["closing_incomplete"]
    price = _money(closing.get("sale_price")) or Decimal("0")
    adjustments = closing.get("adjustments") or []
    discharges = closing.get("discharges") or []
    net = _money(closing.get("net_proceeds"))
    expected = price
    for item in adjustments:
        amount = _money(item.get("amount"))
        if amount is None or item.get("direction") not in {"credit_vendor", "credit_purchaser"}:
            flags.append("adjustment_incomplete")
            continue
        expected += amount if item["direction"] == "credit_vendor" else -amount
    for item in discharges:
        amount = _money(item.get("payout_amount"))
        if amount is None or _date(item.get("payout_date")) is None:
            flags.append("discharge_incomplete")
        else:
            expected -= amount
    if net is None or expected != net:
        flags.append(f"net_proceeds_variance:{(expected - (net or Decimal('0'))):.2f}")
    facilities = list((await db.scalars(select(LenderFacility).where(
        LenderFacility.lot_id == entry.lot_id,
        LenderFacility.status.notin_(["closed", "discharged", "statement_only"])))).all())
    resolved_ids = set()
    for item in discharges:
        facility = _resolve_discharge_facility(facilities, item)
        if facility is None:
            flags.append("discharge_facility_unmatched_or_ambiguous")
        else:
            if facility.id in resolved_ids:
                flags.append("duplicate_facility_discharge")
            resolved_ids.add(facility.id)
    for facility in facilities:
        if facility.id not in resolved_ids:
            flags.append(f"undischarged_facility:{facility.id}")
    if closing.get("closing_type") == "refinance":
        lender_name = str(closing.get("new_lender") or "").strip()
        if not lender_name or not await db.scalar(select(Lender.id).where(func.lower(Lender.name) == lender_name.casefold())):
            flags.append("new_lender_not_on_file")
    if closing.get("closing_type") == "sale":
        agreement = await db.scalar(select(SalesAgreement).where(SalesAgreement.lot_id == entry.lot_id)
                                    .order_by(SalesAgreement.created_at.desc()))
        if agreement and _money(closing.get("sale_price")) != agreement.sale_price:
            flags.append("sale_price_differs_from_otp")
    return flags


async def post_confirmed_notice(db: AsyncSession, notice_id: UUID) -> dict:
    notice = await db.get(FundsNotice, notice_id, with_for_update=True)
    if notice is None:
        raise ValueError("Notice not found")
    entries = list((await db.scalars(select(FundsEntry).where(FundsEntry.notice_id == notice_id)
                         .order_by(FundsEntry.created_at).with_for_update())).all())
    if not entries or any(e.status not in {"confirmed", "posted"} for e in entries):
        raise ValueError("Every entry must be explicitly confirmed before any posting")
    attachments = {a.id: a for a in (await db.scalars(select(FundsAttachment).where(
        FundsAttachment.notice_id == notice_id))).all()}
    if not attachments or any(a.extraction_status != "complete" for a in attachments.values()):
        raise ValueError("Every attached PDF must finish extraction before posting")
    if any(not any(e.attachment_id == attachment_id for e in entries) for attachment_id in attachments):
        raise ValueError("Every attached PDF needs a reviewed entry before posting")
    if any(attachments[e.attachment_id].box_filing_status != "filed" for e in entries):
        raise ValueError("Every source PDF must be filed to its legal Box folder before posting")
    for entry in entries:
        if entry.status == "posted":
            continue
        if entry.funds_type != "other" and not entry.lot_id:
            raise ValueError(f"Entry {entry.id} needs a matched lot")
        attachment = attachments[entry.attachment_id]
        box_url = (attachment.extracted or {}).get("box_file_urls_by_entry", {}).get(str(entry.id)) or attachment.box_file_url
        if entry.funds_type == "pro_draw":
            result = await _post_pro(db, entry, box_url)
        elif entry.funds_type == "lot_deposit":
            result = await PromotionService(db).record_lawyer_deposit_payment(
                entry, box_url)
        elif entry.funds_type == "client_funded_draw":
            result = await _post_client(db, entry, box_url)
        elif entry.funds_type == "statement_of_adjustments":
            result = await _post_closing(db, entry, box_url)
        else:
            result = {"status": "filed_for_review", "money_posted": False}
        entry.status = "posted"
        entry.posted_at = datetime.now(timezone.utc)
        entry.posting_result = result
    affected_facility_ids = {e.facility_id for e in entries if e.funds_type == "pro_draw" and e.facility_id}
    if affected_facility_ids:
        from app.services.financing import _reconcile_snapshot, _refresh_statement_status
        await db.flush()
        snapshots = list((await db.scalars(select(FacilityStatementSnapshot).where(
            FacilityStatementSnapshot.facility_id.in_(affected_facility_ids)))).all())
        for snapshot in snapshots:
            await _reconcile_snapshot(db, snapshot.id)
        for statement_id in {snapshot.statement_id for snapshot in snapshots}:
            await _refresh_statement_status(db, statement_id)
    notice.status = "posted"
    task = await db.scalar(select(FundsTask).where(FundsTask.task_key == f"notice:{notice_id}"))
    if task:
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"notice_id": str(notice_id), "posted": len(entries)}


async def _post_pro(db: AsyncSession, entry: FundsEntry, box_url: str | None) -> dict:
    if not entry.facility_id or not entry.amount or not entry.txn_date:
        raise ValueError("PRO draw needs a facility, amount and date")
    facility = await db.get(LenderFacility, entry.facility_id)
    if not facility or facility.lender_type != "PRO":
        raise ValueError("Selected facility is not PRO-financed")
    found = await statement_match(db, entry)
    existing = list((await db.scalars(select(FacilityTransaction).where(
        FacilityTransaction.facility_id == entry.facility_id,
        FacilityTransaction.txn_type == "draw"))).all())
    cheque = _cheque(entry.cheque_number)
    matched = next((tx for tx in existing if cheque and _cheque(tx.reference) == cheque), None)
    if matched and matched.amount != entry.amount:
        raise ValueError("Existing cheque has a different amount")
    if not matched:
        same_date_amount = [tx for tx in existing if tx.txn_date == entry.txn_date and tx.amount == entry.amount]
        if cheque and any(_cheque(tx.reference) and _cheque(tx.reference) != cheque for tx in same_date_amount):
            raise ValueError("Date and amount match an existing draw with a different cheque")
        if len(same_date_amount) > 1:
            raise ValueError("Multiple core draws share this date and amount; select a unique match")
        matched = same_date_amount[0] if same_date_amount else None
    if matched:
        if matched.funds_entry_id and matched.funds_entry_id != entry.id:
            raise ValueError("Core draw is already linked to another funds notice")
        matched.funds_entry_id = entry.id
        matched.funds_notice_id = entry.notice_id
        matched.intake_origin = "lawyer_notice"
        matched.box_file_url = box_url
        if found and not matched.statement_id:
            matched.statement_id = found[0].statement_id
        result = {"status": "matched_existing_core", "transaction_id": str(matched.id)}
    else:
        tx = FacilityTransaction(facility_id=entry.facility_id, txn_date=entry.txn_date,
                                 txn_type="draw", amount=entry.amount,
                                 reference=entry.cheque_number or entry.memo,
                                 source="lawyer_notice", funds_entry_id=entry.id,
                                 funds_notice_id=entry.notice_id, intake_origin="lawyer_notice",
                                 statement_id=found[0].statement_id if found else None,
                                 box_file_url=box_url)
        db.add(tx)
        await db.flush()
        result = {"status": "matched_statement" if found else "pending_statement",
                  "transaction_id": str(tx.id)}
        matched = tx
    entry.posted_transaction_id = matched.id
    if found:
        entry.matched_statement_id = found[0].statement_id
        entry.matched_snapshot_id = found[0].id
    return result


async def _post_client(db: AsyncSession, entry: FundsEntry, box_url: str | None) -> dict:
    if not entry.amount or not entry.txn_date:
        raise ValueError("Client-funded draw needs amount and date")
    row = (await db.execute(text("""INSERT INTO core.client_funded_draws
        (lot_id, funds_entry_id, funds_notice_id, amount, txn_date, cheque_number, box_file_url)
        VALUES (:lot, :entry, :notice, :amount, :date, :cheque, :url) RETURNING id"""),
        {"lot": entry.lot_id, "entry": entry.id, "notice": entry.notice_id, "amount": entry.amount,
         "date": entry.txn_date, "cheque": entry.cheque_number, "url": box_url})).scalar_one()
    return {"status": "posted_client_funded", "draw_id": str(row)}


async def _post_closing(db: AsyncSession, entry: FundsEntry, box_url: str | None) -> dict:
    closing = entry.closing or {}
    flags = await _closing_flags(db, entry)
    blocking = [flag for flag in flags if flag != "sale_price_differs_from_otp"]
    if blocking:
        raise ValueError(f"Closing requires correction: {', '.join(blocking)}")
    closing_date = _date(closing.get("closing_date"))
    assert closing_date is not None
    discharges = closing.get("discharges") or []
    facilities = list((await db.scalars(select(LenderFacility).where(
        LenderFacility.lot_id == entry.lot_id,
        LenderFacility.status.notin_(["closed", "discharged", "statement_only"])))).all())
    facility_ids = []
    for item in discharges:
        reference = str(item.get("facility_reference") or "").strip()
        facility = _resolve_discharge_facility(facilities, item)
        if not facility:
            raise ValueError(f"Discharge facility not found: {reference}")
        amount = _money(item.get("payout_amount"))
        payout_date = _date(item.get("payout_date"))
        assert amount is not None and payout_date is not None
        tx = FacilityTransaction(facility_id=facility.id, txn_date=payout_date,
                                 txn_type="repayment", amount=amount,
                                 reference=f"Discharge {entry.id}", source="lawyer_notice",
                                 funds_entry_id=entry.id, funds_notice_id=entry.notice_id,
                                 intake_origin="lawyer_notice", box_file_url=box_url)
        db.add(tx)
        facility.status = "closed"
        facility.payout_date = payout_date
        facility.payout_amount = amount
        facility.payout_notice_id = entry.notice_id
        facility_ids.append(str(facility.id))
    lot = await db.get(Lot, entry.lot_id)
    assert lot is not None
    if closing.get("closing_type") == "sale":
        lot.closing_date = closing_date
        lot.final_sale_price = _money(closing.get("sale_price"))
        lot.net_proceeds = _money(closing.get("net_proceeds"))
        lot.status = LotStatus.POSSESSION
    else:
        lender = await db.scalar(select(Lender).where(func.lower(Lender.name) ==
                                                str(closing.get("new_lender")).strip().casefold()))
        assert lender is not None
        db.add(LenderFacility(lot_id=entry.lot_id, property_id=lot.property_id,
                              lender_id=lender.id, lender_type="OTHER", lender_name=lender.name,
                              facility_key=f"REFI-{entry.lot_id}-{lender.id}", status="pending"))
    row_id = (await db.execute(text("""INSERT INTO core.lot_closings
        (lot_id, funds_entry_id, funds_notice_id, closing_type, closing_date, sale_price, net_proceeds,
         adjustments, new_lender, box_file_url)
        VALUES (:lot, :entry, :notice, :type, :date, :price, :net, CAST(:adjustments AS jsonb), :lender, :url)
        RETURNING id"""), {"lot": entry.lot_id, "entry": entry.id,
        "notice": entry.notice_id,
        "type": closing["closing_type"], "date": closing_date,
        "price": _money(closing.get("sale_price")), "net": _money(closing.get("net_proceeds")),
        "adjustments": __import__("json").dumps(closing.get("adjustments") or []),
        "lender": closing.get("new_lender"), "url": box_url})).scalar_one()
    watch = await db.scalar(select(FundsBoxWatch).where(FundsBoxWatch.lot_id == entry.lot_id))
    if watch:
        watch.status = "completed"
    task = await db.scalar(select(FundsTask).where(FundsTask.task_key == f"closing:{entry.lot_id}"))
    if task:
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
    return {"status": "closing_posted", "closing_id": str(row_id),
            "discharged_facility_ids": facility_ids, "flags": flags}


def _resolve_discharge_facility(facilities: list[LenderFacility], discharge: dict) -> LenderFacility | None:
    reference = str(discharge.get("facility_reference") or "").strip().casefold()
    lender = str(discharge.get("lender") or "").strip().casefold()
    if reference:
        matches = [f for f in facilities if reference in {
            str(f.id).casefold(), str(f.facility_key or "").casefold(),
            str(f.account_number or "").casefold()}]
    else:
        matches = [f for f in facilities if lender and lender in {
            str(f.lender_name or "").casefold(), str(f.lender or "").casefold(),
            str(f.lender_type or "").casefold()}]
    return matches[0] if len(matches) == 1 else None
