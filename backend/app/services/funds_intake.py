"""Capture and stage lawyer funds documents; no money is posted here."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.addresses import normalize_address
from app.core.database import AsyncSessionLocal
from app.models.core import Lot, User
from app.models.financing import Property
from app.models.funds import FundsAttachment, FundsEntry, FundsNotice, FundsTask
from app.schemas.funds import FundsIntake
from app.services.box import get_box_client, upload_file
from app.services.extraction.funds import FUNDS_TYPES, extract_funds_pdf
from app.services.minio_financing import get_financing_document, upload_financing_document


def _money(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).replace(",", "").replace("$", "")).quantize(Decimal("0.01"))
        return result if result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


async def nicholas_user_id(db: AsyncSession) -> UUID | None:
    return await db.scalar(select(User.id).where(User.is_active.is_(True),
        or_(func.lower(User.full_name).like("nicholas%"), func.lower(User.email).like("nicholas%"))).limit(1))


async def match_property(db: AsyncSession, address: str | None) -> tuple[UUID | None, UUID | None]:
    if not address:
        return None, None
    key = normalize_address(address).canonical_key
    properties = list((await db.scalars(select(Property).where(Property.canonical_address_key == key))).all())
    if not properties:
        properties = [p for p in (await db.scalars(select(Property))).all()
                      if normalize_address(p.address).canonical_key == key]
    if not properties:
        text_value = re.sub(r"[^A-Z0-9]+", " ", address.upper()).strip()
        properties = [p for p in (await db.scalars(select(Property))).all()
                      if re.sub(r"[^A-Z0-9]+", " ", p.address.upper()).strip() in text_value]
    if len(properties) != 1:
        return None, None
    lots = list((await db.scalars(select(Lot).where(Lot.property_id == properties[0].id))).all())
    return properties[0].id, lots[0].id if len(lots) == 1 else None


async def intake(db: AsyncSession, data: FundsIntake) -> UUID:
    if data.property_id and await db.get(Property, data.property_id) is None:
        raise ValueError("Property not found")
    decoded = []
    seen_digests: set[str] = set()
    for attachment in data.attachments:
        if attachment.mime not in ("application/pdf", "application/octet-stream"):
            raise ValueError(f"{attachment.filename} is not a PDF")
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except Exception as exc:
            raise ValueError(f"{attachment.filename} has invalid base64") from exc
        if not content.startswith(b"%PDF") or len(content) > 25_000_000:
            raise ValueError(f"{attachment.filename} must be a PDF under 25 MB")
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen_digests:
            raise ValueError(f"Duplicate attachment in this message: {attachment.filename}")
        seen_digests.add(digest)
        existing = await db.scalar(select(FundsAttachment).where(FundsAttachment.file_sha256 == digest))
        if existing:
            raise ValueError(f"Duplicate attachment: notice {existing.notice_id}")
        decoded.append((attachment, content, digest))
    property_id = data.property_id
    matched_property, matched_lot = await match_property(db, data.email.subject)
    if property_id is None:
        property_id = matched_property
    lot_id = matched_lot if property_id == matched_property else None
    notice = FundsNotice(
        property_id=property_id, lot_id=lot_id,
        email_message_id=data.email.message_id, email_from=data.email.from_,
        email_subject=data.email.subject, email_received_at=data.email.received_at,
        email_body_text=data.email.body_text[:4000],
    )
    db.add(notice)
    await db.flush()
    for attachment, content, digest in decoded:
        key = f"lawyer-funds/{notice.id}/{digest}.pdf"
        upload_financing_document(key=key, content=content, content_type="application/pdf")
        db.add(FundsAttachment(notice_id=notice.id, file_sha256=digest,
                               file_key=key, original_filename=attachment.filename, mime="application/pdf"))
    db.add(FundsTask(task_key=f"notice:{notice.id}", notice_id=notice.id,
                     lot_id=lot_id, task_type="review_notice",
                     title=f"Funds notice — {data.email.subject or 'Multiple'} — pending extraction",
                     assignee_id=await nicholas_user_id(db),
                     payload={"assignee_name": "Nicholas"}))
    await db.commit()
    return notice.id


async def extract_notice(notice_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        notice = await db.get(FundsNotice, notice_id)
        if notice is None:
            return
        attachments = list((await db.scalars(select(FundsAttachment).where(FundsAttachment.notice_id == notice_id))).all())
        for attachment in attachments:
            if attachment.extraction_status == "complete":
                continue
            try:
                content = await asyncio.to_thread(get_financing_document, key=attachment.file_key)
                extracted = await extract_funds_pdf(content)
                attachment.extracted = extracted
                attachment.extraction_status = "complete"
                await _apply_extraction(db, notice, attachment, extracted)
            except Exception as exc:
                attachment.extraction_status = "error"
                attachment.extraction_error = str(exc)[:1000]
                notice.status = "needs_attention"
                notice.review_flags = list(set((notice.review_flags or []) + ["extraction_failed"]))
        await db.flush()
        for attachment in attachments:
            if attachment.extraction_status != "complete" or attachment.box_filing_status == "filed":
                continue
            try:
                await file_attachment_to_box(db, attachment)
            except Exception:
                # Extraction remains available for review when Box is temporarily unavailable.
                attachment.box_filing_status = "pending"
                notice.review_flags = list(set((notice.review_flags or []) + ["box_filing_pending"]))
        if notice.status != "needs_attention":
            notice.status = "pending_review"
        await db.commit()


async def _apply_extraction(db: AsyncSession, notice: FundsNotice,
                            attachment: FundsAttachment, extracted: dict) -> None:
    funds_type = extracted.get("funds_type") if extracted.get("funds_type") in FUNDS_TYPES else "other"
    notice.law_firm = notice.law_firm or extracted.get("law_firm") or None
    attachment_total = _money(extracted.get("trust_statement_total"))
    if attachment_total is not None:
        notice.trust_statement_total = (notice.trust_statement_total or Decimal("0.00")) + attachment_total
    notice.funds_release_date = notice.funds_release_date or _date(extracted.get("funds_release_date"))
    notice.classification_reason = notice.classification_reason or extracted.get("classification_reason") or None
    ordinal = {"1st": 1, "2nd": 2, "3rd": 3}.get(extracted.get("deposit_ordinal"))
    entries = extracted.get("entries") or []
    if not entries:
        entries = [{"property_address": notice.email_subject, "amount": None,
                    "memo": "No transaction entry could be extracted; review the PDF."}]
        funds_type = "other"
        notice.review_flags = list(set((notice.review_flags or []) + ["details_not_extracted"]))
    notice.funds_type = funds_type if not notice.funds_type or notice.funds_type == funds_type else "multiple"
    total = Decimal("0.00")
    for item in entries:
        if not isinstance(item, dict):
            continue
        amount = _money(item.get("amount"))
        total += amount or Decimal("0.00")
        address = item.get("property_address") or None
        property_id, lot_id = await match_property(db, address)
        if not property_id and len(entries) == 1:
            property_id, lot_id = notice.property_id, notice.lot_id
        flags = [] if property_id and lot_id else ["property_unmatched"]
        db.add(FundsEntry(
            notice_id=notice.id, attachment_id=attachment.id,
            property_id=property_id, lot_id=lot_id,
            funds_type=funds_type, deposit_ordinal=ordinal,
            property_address=address, amount=amount,
            cheque_number=str(item["cheque_number"]) if item.get("cheque_number") else None,
            txn_date=_date(item.get("date")) or notice.funds_release_date,
            payee=item.get("payee") or None, memo=item.get("memo") or None,
            closing=item.get("closing") if isinstance(item.get("closing"), dict) else None,
            review_flags=flags,
        ))
    if attachment_total is not None and total != attachment_total:
        notice.review_flags = list(set((notice.review_flags or []) + ["trust_total_mismatch"]))
    task = await db.scalar(select(FundsTask).where(FundsTask.task_key == f"notice:{notice.id}"))
    if task:
        task.title = f"Funds notice — {notice.email_subject or 'Multiple'} — {funds_type} — ${total:,.2f}"
        task.payload = {"assignee_name": "Nicholas", "law_firm": notice.law_firm,
                        "entries": len(entries), "received_at": notice.email_received_at.isoformat() if notice.email_received_at else None}


async def file_attachment_to_box(db: AsyncSession, attachment: FundsAttachment) -> bool:
    """File only to an existing, unambiguous legal folder. Never create guessed folders."""
    entries = list((await db.scalars(select(FundsEntry).where(FundsEntry.attachment_id == attachment.id))).all())
    if not entries or any(not entry.property_id for entry in entries):
        return False
    client = await asyncio.to_thread(get_box_client)
    if client is None:
        attachment.box_filing_status = "pending"
        return False
    content = await asyncio.to_thread(get_financing_document, key=attachment.file_key)
    urls: dict[str, str] = {}
    for entry in entries:
        property_row = await db.get(Property, entry.property_id)
        if property_row is None:
            continue
        folder_id = await asyncio.to_thread(resolve_legal_folder, client, property_row.address)
        if not folder_id:
            attachment.box_filing_status = "pending"
            return False
        filed_name = f"{attachment.file_sha256[:12]}-{attachment.original_filename}"
        file_id, url = await asyncio.to_thread(upload_file, folder_id, filed_name, content,
                                                raise_errors=True)
        if not file_id or not url:
            return False
        urls[str(entry.id)] = url
    if len(urls) != len(entries):
        return False
    attachment.box_file_url = next(iter(urls.values()))
    attachment.box_file_id = attachment.box_file_url.rsplit("/", 1)[-1]
    attachment.extracted = {**(attachment.extracted or {}), "box_file_urls_by_entry": urls}
    attachment.box_filing_status = "filed"
    return True


LEGAL_ROOT_ID = "210783521222"  # Verified from Box's 154 Ramona Gallos Way path.


def resolve_legal_folder(client: object, raw_address: str) -> str | None:
    address = normalize_address(raw_address)
    if not address.street_number or not address.street_name:
        return None
    suffix = {"ST": "Street", "DR": "Drive", "AVE": "Avenue", "CRES": "Crescent",
              "RD": "Road", "BLVD": "Boulevard"}.get(address.street_suffix, address.street_suffix or "")
    folder_name = f"{address.street_name.title()} {suffix}, {address.street_number}".strip()
    candidates = list(client.search().query(
        query=folder_name, type="folder", ancestor_folders=[client.folder(LEGAL_ROOT_ID)],
        fields=["id", "name", "path_collection"], limit=100))
    exact = [row for row in candidates if row.name.casefold() == folder_name.casefold()
             and any(item["id"] == LEGAL_ROOT_ID for item in row.path_collection["entries"])]
    return str(exact[0].id) if len(exact) == 1 else None
