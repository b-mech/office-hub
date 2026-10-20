"""Lawyer funds intake, review, and possession confirmation."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.core import Lot, LotStatus, User, UserRole
from app.models.financing import ConstructionStageSync, LenderFacility, LenderStatement, Property
from app.models.funds import FundsAttachment, FundsBoxWatch, FundsEntry, FundsNotice, FundsTask
from app.models.sales import SalesAgreement
from app.schemas.funds import EntryUpdate, FundsIntake, PossessionConfirm
from app.services import funds_intake, funds_posting
from app.services.extraction.funds import FUNDS_TYPES
from app.services.minio_financing import get_financing_document

router = APIRouter(prefix="/api/financing/funds-notices", tags=["lawyer-funds"])


def extension_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(401, "Invalid Office Hub extension API key")


def reviewer(request: Request) -> User | None:
    if not settings.auth_enforced:
        return None
    user = current_user(request)
    if user.role == UserRole.ADMIN or (user.permissions or {}).get("financing") == "editor":
        return user
    raise HTTPException(403, "Financing review permission required")


@router.get("/extension/properties", dependencies=[Depends(extension_key)])
async def extension_properties(search: str = "", db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = list((await db.scalars(select(Property).order_by(Property.address))).all())
    return [{"id": str(row.id), "address": row.address} for row in rows
            if search.casefold() in row.address.casefold()][:100]


@router.get("/options", dependencies=[Depends(reviewer)])
async def review_options(db: AsyncSession = Depends(get_db)) -> dict:
    properties = list((await db.scalars(select(Property).order_by(Property.address))).all())
    lots = list((await db.scalars(select(Lot))).all())
    facilities = list((await db.scalars(select(LenderFacility))).all())
    agreements = list((await db.scalars(select(SalesAgreement).order_by(SalesAgreement.created_at.desc()))).all())
    agreement_by_lot = {row.lot_id: row for row in reversed(agreements)}
    stages = list((await db.scalars(select(ConstructionStageSync))).all())
    stage_by_property = {row.property_id: row for row in stages if row.property_id}
    return {
        "properties": [{"id": str(p.id), "address": p.address} for p in properties],
        "lots": [{"id": str(l.id), "property_id": str(l.property_id) if l.property_id else None,
                  "address": l.civic_address or l.legal_description_raw or str(l.id),
                  "is_sale": l.id in agreement_by_lot,
                  "estimated_possession_date": (
                    stage_by_property[l.property_id].possession_date.isoformat()
                    if l.property_id in stage_by_property and stage_by_property[l.property_id].possession_date
                    else agreement_by_lot[l.id].possession_date.isoformat()
                    if l.id in agreement_by_lot and agreement_by_lot[l.id].possession_date else None),
                  "tracker_date_locked": bool(stage_by_property[l.property_id].possession_date_locked)
                    if l.property_id in stage_by_property else False,
                  "possession_confirmed_date": l.possession_confirmed_date.isoformat() if l.possession_confirmed_date else None}
                 for l in lots],
        "facilities": [{"id": str(f.id), "lot_id": str(f.lot_id) if f.lot_id else None,
                        "property_id": str(f.property_id) if f.property_id else None,
                        "label": f.property_name or f.facility_key or str(f.id),
                        "lender_type": f.lender_type} for f in facilities],
    }


@router.get("/tasks", dependencies=[Depends(reviewer)])
async def list_tasks(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = list((await db.scalars(select(FundsTask).where(FundsTask.status == "open")
                                  .order_by(FundsTask.created_at.desc()).limit(500))).all())
    return [{"id": str(row.id), "task_type": row.task_type, "title": row.title,
             "lot_id": str(row.lot_id) if row.lot_id else None,
             "notice_id": str(row.notice_id) if row.notice_id else None,
             "payload": row.payload, "due_at": row.due_at.isoformat() if row.due_at else None}
            for row in rows]


@router.post("/intake", status_code=202, dependencies=[Depends(extension_key)])
async def intake(data: FundsIntake, background_tasks: BackgroundTasks,
                 db: AsyncSession = Depends(get_db)) -> dict:
    try:
        notice_id = await funds_intake.intake(db, data)
    except ValueError as exc:
        raise HTTPException(409 if "Duplicate" in str(exc) else 400, str(exc)) from exc
    background_tasks.add_task(funds_intake.extract_notice, notice_id)
    return {"funds_notice_id": str(notice_id)}


@router.get("", dependencies=[Depends(reviewer)])
async def list_notices(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = list((await db.scalars(select(FundsNotice).order_by(FundsNotice.created_at.desc()).limit(200))).all())
    return [{"id": str(row.id), "subject": row.email_subject, "status": row.status,
             "funds_type": row.funds_type, "law_firm": row.law_firm,
             "trust_statement_total": str(row.trust_statement_total) if row.trust_statement_total is not None else None,
             "received_at": row.email_received_at.isoformat() if row.email_received_at else None,
             "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/{notice_id}", dependencies=[Depends(reviewer)])
async def notice_detail(notice_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(FundsNotice, notice_id)
    if row is None:
        raise HTTPException(404, "Notice not found")
    attachments = list((await db.scalars(select(FundsAttachment).where(FundsAttachment.notice_id == notice_id))).all())
    entries = list((await db.scalars(select(FundsEntry).where(FundsEntry.notice_id == notice_id)
                                           .order_by(FundsEntry.created_at))).all())
    return {"id": str(row.id), "subject": row.email_subject, "email_from": row.email_from,
            "received_at": row.email_received_at.isoformat() if row.email_received_at else None,
            "status": row.status, "funds_type": row.funds_type,
            "classification_reason": row.classification_reason,
            "law_firm": row.law_firm,
            "trust_statement_total": str(row.trust_statement_total) if row.trust_statement_total is not None else None,
            "review_flags": row.review_flags,
            "attachments": [{"id": str(a.id), "filename": a.original_filename,
                             "box_file_url": a.box_file_url, "box_filing_status": a.box_filing_status,
                             "extraction_status": a.extraction_status, "extraction_error": a.extraction_error}
                            for a in attachments],
            "entries": [await funds_posting.preview_entry(db, e) for e in entries],
            "entry_total": str(sum((e.amount or 0 for e in entries), 0))}


@router.get("/{notice_id}/attachments/{attachment_id}/pdf", dependencies=[Depends(reviewer)])
async def attachment_pdf(notice_id: UUID, attachment_id: UUID,
                         db: AsyncSession = Depends(get_db)) -> Response:
    row = await db.get(FundsAttachment, attachment_id)
    if row is None or row.notice_id != notice_id:
        raise HTTPException(404, "PDF not found")
    content = await asyncio.to_thread(get_financing_document, key=row.file_key)
    return Response(content=content, media_type="application/pdf")


@router.patch("/{notice_id}/entries/{entry_id}", dependencies=[Depends(reviewer)])
async def update_entry(notice_id: UUID, entry_id: UUID, update: EntryUpdate,
                       db: AsyncSession = Depends(get_db)) -> dict:
    entry = await db.get(FundsEntry, entry_id)
    if entry is None or entry.notice_id != notice_id:
        raise HTTPException(404, "Entry not found")
    if entry.status == "posted":
        raise HTTPException(409, "Posted entries cannot be edited")
    for key, value in update.model_dump(exclude_unset=True).items():
        if key == "funds_type" and value not in FUNDS_TYPES:
            raise HTTPException(400, "Invalid funds type")
        setattr(entry, key, value)
    if entry.property_id and "lot_id" not in update.model_fields_set:
        lots = list((await db.scalars(select(Lot).where(Lot.property_id == entry.property_id))).all())
        entry.lot_id = lots[0].id if len(lots) == 1 else None
    if entry.lot_id and entry.funds_type == "pro_draw" and "facility_id" not in update.model_fields_set:
        facilities = list((await db.scalars(select(LenderFacility).where(
            LenderFacility.lot_id == entry.lot_id, LenderFacility.lender_type == "PRO"))).all())
        entry.facility_id = facilities[0].id if len(facilities) == 1 else None
    if entry.property_id and not await db.get(Property, entry.property_id):
        raise HTTPException(400, "Property not found")
    if entry.lot_id:
        lot = await db.get(Lot, entry.lot_id)
        if not lot:
            raise HTTPException(400, "Lot not found")
        if entry.property_id and lot.property_id != entry.property_id:
            raise HTTPException(400, "Lot is not linked to the selected property")
    if entry.facility_id:
        facility = await db.get(LenderFacility, entry.facility_id)
        if not facility:
            raise HTTPException(400, "Facility not found")
        if entry.lot_id and facility.lot_id != entry.lot_id:
            raise HTTPException(400, "Facility is not linked to the selected lot")
    if entry.property_id and entry.lot_id:
        entry.review_flags = [flag for flag in (entry.review_flags or []) if flag != "property_unmatched"]
    entry.status = "pending_review"
    await db.commit()
    return await funds_posting.preview_entry(db, entry)


@router.post("/{notice_id}/file-to-box", dependencies=[Depends(reviewer)])
async def file_to_box(notice_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    attachments = list((await db.scalars(select(FundsAttachment).where(FundsAttachment.notice_id == notice_id))).all())
    if not attachments:
        raise HTTPException(404, "Notice not found")
    filed = 0
    for attachment in attachments:
        if attachment.box_filing_status == "filed" or await funds_intake.file_attachment_to_box(db, attachment):
            filed += 1
    await db.commit()
    return {"filed": filed, "total": len(attachments)}


@router.post("/{notice_id}/entries/{entry_id}/confirm", dependencies=[Depends(reviewer)])
async def confirm_entry(notice_id: UUID, entry_id: UUID, request: Request,
                        db: AsyncSession = Depends(get_db)) -> dict:
    entry = await db.get(FundsEntry, entry_id, with_for_update=True)
    if entry is None or entry.notice_id != notice_id:
        raise HTTPException(404, "Entry not found")
    if entry.status == "posted":
        return {"status": "posted", "entry_id": str(entry.id)}
    if entry.status not in {"pending_review", "confirmed"}:
        raise HTTPException(409, "Entry cannot be confirmed")
    preview = await funds_posting.preview_entry(db, entry)
    blocking = [f for f in preview["flags"] if f in {"property_unmatched", "obligation_already_paid",
                "closing_incomplete", "adjustment_incomplete", "discharge_incomplete", "new_lender_not_on_file"}
                or f.startswith("undischarged_facility:") or f.startswith("net_proceeds_variance:")]
    if blocking:
        raise HTTPException(409, {"message": "Resolve entry before confirmation", "flags": blocking})
    entry.status = "confirmed"
    entry.confirmed_at = datetime.now(timezone.utc)
    entry.confirmed_by = current_user(request).id if settings.auth_enforced else None
    await db.commit()
    other = list((await db.scalars(select(FundsEntry).where(FundsEntry.notice_id == notice_id))).all())
    if any(e.status not in {"confirmed", "posted"} for e in other):
        return {"status": "confirmed_waiting_for_other_entries", "entry_id": str(entry.id)}
    try:
        attachments = list((await db.scalars(select(FundsAttachment).where(FundsAttachment.notice_id == notice_id))).all())
        for attachment in attachments:
            if attachment.box_filing_status != "filed":
                await funds_intake.file_attachment_to_box(db, attachment)
        await db.commit()
        return await funds_posting.post_confirmed_notice(db, notice_id)
    except (ValueError, RuntimeError) as exc:
        await db.rollback()
        return {"status": "confirmed_not_posted", "reason": str(exc), "entry_id": str(entry.id)}


@router.post("/{notice_id}/post", dependencies=[Depends(reviewer)])
async def retry_post(notice_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await funds_posting.post_confirmed_notice(db, notice_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/lots/{lot_id}/possession", dependencies=[Depends(reviewer)])
async def possession_taken(lot_id: UUID, data: PossessionConfirm,
                           db: AsyncSession = Depends(get_db)) -> dict:
    lot = await db.get(Lot, lot_id, with_for_update=True)
    if lot is None:
        raise HTTPException(404, "Lot not found")
    agreement = await db.scalar(select(SalesAgreement).where(SalesAgreement.lot_id == lot_id)
                                .order_by(SalesAgreement.created_at.desc()))
    if agreement is None:
        raise HTTPException(409, "Possession taken is available only for sales")
    if data.possession_date > date.today():
        raise HTTPException(400, "Actual possession date cannot be in the future")
    if lot.possession_confirmed_date:
        raise HTTPException(409, "Possession was already confirmed")
    lot.possession_confirmed_date = data.possession_date
    lot.possession_confirmed_at = datetime.now(timezone.utc)
    lot.status = LotStatus.POSSESSION
    stage = await db.scalar(select(ConstructionStageSync).where(
        ConstructionStageSync.property_id == lot.property_id).with_for_update()) if lot.property_id else None
    if stage:
        stage.possession_date = data.possession_date
        stage.possession_confirmed_date = data.possession_date
    facilities = list((await db.scalars(select(LenderFacility).where(
        LenderFacility.lot_id == lot_id,
        LenderFacility.status.notin_(["closed", "discharged", "statement_only"])))).all())
    for facility in facilities:
        facility.status = "closing_pending"
        facility.closing_pending_at = data.possession_date
    address = lot.civic_address or lot.legal_description_raw or str(lot.id)
    db.add(FundsTask(task_key=f"closing:{lot_id}", lot_id=lot_id,
                     task_type="awaiting_closing_docs",
                     title=f"Awaiting signed closing docs — {address}",
                     assignee_id=await funds_intake.nicholas_user_id(db),
                     payload={"assignee_name": "Nicholas"}))
    db.add(FundsBoxWatch(lot_id=lot_id, possession_date=data.possession_date))
    if facilities:
        from app.services.financing import _refresh_statement_status, _sync_statement_discrepancies
        await db.flush()
        statements = list((await db.scalars(select(LenderStatement.id).where(LenderStatement.lender == "PRO"))).all())
        for statement_id in statements:
            await _sync_statement_discrepancies(db, statement_id)
            await _refresh_statement_status(db, statement_id)
    await db.commit()
    return {"lot_id": str(lot_id), "possession_date": data.possession_date.isoformat(),
            "closing_pending_facilities": [str(f.id) for f in facilities]}
