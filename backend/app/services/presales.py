from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from email.message import EmailMessage
from typing import Any, Iterable
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.addresses import normalize_address
from app.core.config import settings
from app.models.core import BuildingType, Contact, Lot, Reminder, SaleType, User, UserRole
from app.models.documents import DocType, Document, DocumentStatus
from app.models.land import Agreement as LandAgreement
from app.models.land import LotTerms
from app.models.lenders import Lender
from app.models.presales import (
    ApprovalLetterStatus,
    FundingPartnerRule,
    PresaleApprovalLetter,
    PresaleNotification,
    PresalePackageItem,
    PresaleTask,
)
from app.models.program_allocations import LenderProgram
from app.models.sales import Party, PartyRole, SalesAgreement
from app.modules.costbook.models import Budget, BudgetLine
from app.services.extraction.approval_letters import CONDITION_CATEGORIES
from app.services.minio_financing import get_financing_document, upload_financing_document
from app.services.program_allocations import get_program_capacity


DOCUMENT_BUCKET = "documents"
MONEY_FIELDS = ("approved_amount", "purchase_price", "down_payment")
REQUIRED_EXTRACTION_FIELDS = ("approved_amount", "expiry_date", "document_type", "conditions")
PACKAGE_ITEM_TYPES = ("appraisal", "stamped_plans", "otp_land", "otp_sale", "prelim_budget")


class DuplicateApprovalLetterError(ValueError):
    def __init__(self, existing_id: UUID) -> None:
        self.existing_id = existing_id
        super().__init__(f"Approval letter already exists: {existing_id}")


@dataclass(slots=True)
class PartnerRuleData:
    partner_code: str
    display_name: str
    priority: int
    required_docs: list[str]
    required_fields: list[str]
    disqualifying_conditions: list[str]
    min_quality_score: int | None
    formula: dict[str, Any] | None
    package_recipient: str | None
    package_docs: list[str]


@dataclass(slots=True)
class ReadinessInputs:
    available_docs: set[str]
    fields: dict[str, Any]
    conditions: list[dict[str, Any]]
    quality_score: int | None
    lender_contacted_at: datetime | None
    scu_capacity_ok: bool | None


@dataclass(slots=True)
class LotPackageContext:
    lot: Lot
    letter: PresaleApprovalLetter | None
    sale_agreement: SalesAgreement | None
    land_terms: LotTerms | None
    prelim_budget: Budget | None
    prelim_total: Decimal | None
    buyer_names: list[str]
    package_items: dict[str, PresalePackageItem]
    source_documents: dict[str, Document]
    available_docs: set[str]
    fields: dict[str, Any]
    scu_capacity_ok: bool | None


def evaluate_partner_rules(
    rules: Iterable[PartnerRuleData],
    inputs: ReadinessInputs,
    *,
    computed_at: datetime | None = None,
) -> dict[str, Any]:
    now = computed_at or datetime.now(timezone.utc)
    partners: dict[str, dict[str, Any]] = {}
    suggested: str | None = None

    for rule in sorted(rules, key=lambda item: (item.priority, item.partner_code)):
        missing = [name for name in rule.required_docs if name not in inputs.available_docs]
        missing.extend(
            path for path in rule.required_fields
            if _required_value_missing(inputs.fields.get(path))
        )
        disqualified_by = [
            {"category": condition.get("category"), "text": condition.get("text", "")}
            for condition in inputs.conditions
            if condition.get("category") in set(rule.disqualifying_conditions)
        ]
        quality_blocked = (
            rule.min_quality_score is not None
            and (inputs.quality_score is None or inputs.quality_score < rule.min_quality_score)
            and inputs.lender_contacted_at is None
        )
        capacity_ok = inputs.scu_capacity_ok if rule.partner_code == "SCU" else None

        if disqualified_by:
            state = "disqualified"
        elif quality_blocked:
            state = "blocked_by_quality"
        elif missing or capacity_ok is False:
            state = "not_ready"
        else:
            state = "ready"

        partner: dict[str, Any] = {
            "display_name": rule.display_name,
            "state": state,
            "ready": state == "ready",
            "disqualified_by": disqualified_by,
            "missing": list(dict.fromkeys(missing)),
            "min_quality_score": rule.min_quality_score,
            "package_recipient": rule.package_recipient,
            "package_docs": rule.package_docs,
        }
        if capacity_ok is not None:
            partner["capacity_ok"] = capacity_ok

        if rule.formula and rule.formula.get("type") == "pct_of_sum":
            percentage = _decimal(rule.formula.get("pct")) or Decimal("0")
            formula_inputs = [_decimal(inputs.fields.get(path)) for path in rule.formula.get("inputs", [])]
            if formula_inputs and all(value is not None for value in formula_inputs):
                advance = _round_dollars(percentage * sum((value for value in formula_inputs if value is not None), Decimal("0")))
                sale_price = _round_dollars(_decimal(inputs.fields.get("otp_sale.sale_price")) or Decimal("0"))
                approved = _round_dollars(_decimal(inputs.fields.get("approval_letter.approved_amount")) or Decimal("0"))
                partner.update(
                    {
                        "advance": advance,
                        "sale_price": sale_price,
                        "approved_mortgage": approved,
                        "equity_gap": sale_price - advance,
                    }
                )

        partners[rule.partner_code] = partner
        if suggested is None and state == "ready":
            suggested = rule.partner_code

    return {
        "computed_at": now.isoformat(),
        "status": "ready" if suggested else "not_fundable_yet",
        "suggested": suggested,
        "partners": partners,
    }


async def create_intake_records(
    db: AsyncSession,
    *,
    lot_id: UUID | None,
    mark_as_presale: bool = False,
    email: Any,
    attachments: list[Any],
) -> list[PresaleApprovalLetter]:
    if lot_id is not None:
        lot = await db.get(Lot, lot_id)
        if lot is None:
            raise ValueError("Lot not found")
        if lot.sale_type != SaleType.PRESALE and not mark_as_presale:
            raise ValueError("Approval letters can only be linked to presale lots")
        if lot.sale_type != SaleType.PRESALE:
            await _mark_lot_as_presale(db, lot)

    decoded: list[tuple[Any, bytes, str]] = []
    for attachment in attachments:
        if attachment.mime not in {"application/pdf", "application/octet-stream"}:
            raise ValueError(f"{attachment.filename} is not a PDF")
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except Exception as exc:
            raise ValueError(f"{attachment.filename} contains invalid base64 data") from exc
        if not content or not content.startswith(b"%PDF"):
            raise ValueError(f"{attachment.filename} is not a readable PDF")
        digest = hashlib.sha256(content).hexdigest()
        existing = await db.scalar(
            select(PresaleApprovalLetter.id).where(
                PresaleApprovalLetter.lot_id.is_(None) if lot_id is None else PresaleApprovalLetter.lot_id == lot_id,
                PresaleApprovalLetter.file_sha256 == digest,
            )
        )
        if existing is not None:
            raise DuplicateApprovalLetterError(existing)
        decoded.append((attachment, content, digest))

    requested_record = None
    if lot_id is not None:
        requested_record = await db.scalar(
            select(PresaleApprovalLetter)
            .where(
                PresaleApprovalLetter.lot_id == lot_id,
                PresaleApprovalLetter.status == ApprovalLetterStatus.REQUESTED.value,
                PresaleApprovalLetter.file_key.is_(None),
            )
            .order_by(PresaleApprovalLetter.created_at.desc())
            .limit(1)
        )
    next_version = 1
    if lot_id is not None:
        next_version = int(
            await db.scalar(
                select(func.coalesce(func.max(PresaleApprovalLetter.version), 0)).where(
                    PresaleApprovalLetter.lot_id == lot_id
                )
            )
            or 0
        ) + 1

    records: list[PresaleApprovalLetter] = []
    for index, (attachment, content, digest) in enumerate(decoded):
        key_scope = str(lot_id) if lot_id else "unmatched"
        file_key = f"presales/{key_scope}/approval-letters/{digest}.pdf"
        upload_financing_document(key=file_key, content=content, content_type="application/pdf")
        record = requested_record if index == 0 and requested_record is not None else PresaleApprovalLetter(
            lot_id=lot_id,
            version=next_version + index - (1 if requested_record is not None else 0),
        )
        if record is not requested_record:
            db.add(record)
        record.status = ApprovalLetterStatus.PENDING_EXTRACTION.value
        record.file_key = file_key
        record.file_sha256 = digest
        record.original_filename = _safe_filename(attachment.filename)
        record.email_message_id = email.message_id or None
        record.email_from = email.from_ or None
        record.email_subject = email.subject or None
        record.email_received_at = email.received_at
        record.email_body_text = (email.body_text or "")[:4000] or None
        records.append(record)

    await db.commit()
    for record in records:
        await db.refresh(record)
    return records


async def apply_extraction_result(
    db: AsyncSession,
    letter_id: UUID,
    *,
    payload: dict[str, Any],
    confidences: dict[str, float],
) -> PresaleApprovalLetter:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        raise ValueError("Approval letter not found")
    missing_required = any(_extraction_value_missing(name, payload) for name in REQUIRED_EXTRACTION_FIELDS)
    normalized = normalize_extracted_payload(payload)
    letter.extracted = normalized
    letter.extraction_confidence = confidences
    letter.low_confidence_fields = sorted(key for key, value in confidences.items() if value < 0.75)
    letter.needs_manual_entry = missing_required
    if letter.lot_id is None:
        letter.lot_id = await match_presale_lot(db, str(normalized.get("property_address") or ""))
    letter.status = ApprovalLetterStatus.PENDING_REVIEW.value
    await _upsert_review_task(db, letter)
    await db.commit()
    await db.refresh(letter)
    return letter


async def mark_extraction_failed(db: AsyncSession, letter_id: UUID, message: str) -> None:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        return
    letter.status = ApprovalLetterStatus.PENDING_REVIEW.value
    letter.needs_manual_entry = True
    letter.extracted = {**(letter.extracted or {}), "extraction_error": message[:1000]}
    await _upsert_review_task(db, letter)
    await db.commit()


async def match_presale_lot(db: AsyncSession, address: str) -> UUID | None:
    if not address.strip():
        return None
    target = normalize_address(address).canonical_key
    if not target:
        return None
    lots = list(
        (await db.scalars(select(Lot).where(Lot.sale_type == SaleType.PRESALE))).all()
    )
    scores: list[tuple[float, UUID]] = []
    for lot in lots:
        candidate = normalize_address(lot.civic_address or "").canonical_key
        if not candidate:
            continue
        scores.append((SequenceMatcher(None, target, candidate).ratio(), lot.id))
    scores.sort(reverse=True, key=lambda item: item[0])
    if not scores or scores[0][0] < 0.92:
        return None
    if len(scores) > 1 and scores[1][0] >= 0.92:
        return None
    return scores[0][1]


async def set_lot_presale(
    db: AsyncSession,
    lot_id: UUID,
    *,
    sale_type: str,
    building_type: str | None,
    realtor_name: str | None,
    realtor_email: str | None,
    realtor_brokerage: str | None,
) -> dict[str, Any]:
    lot = await db.get(Lot, lot_id)
    if lot is None:
        raise ValueError("Lot not found")
    requested_sale_type = SaleType(sale_type)
    if requested_sale_type == SaleType.PRESALE:
        await _mark_lot_as_presale(db, lot)
    else:
        lot.sale_type = requested_sale_type
    if building_type is not None:
        lot.building_type = BuildingType(building_type)
    if realtor_name is not None:
        lot.realtor_name = realtor_name.strip() or None
    if realtor_email is not None:
        lot.realtor_email = realtor_email.strip().casefold() or None
    if realtor_brokerage is not None:
        lot.realtor_brokerage = realtor_brokerage.strip() or None
    if lot.sale_type == SaleType.PRESALE:
        active_letter = await db.scalar(
            select(PresaleApprovalLetter.id).where(
                PresaleApprovalLetter.lot_id == lot.id,
                PresaleApprovalLetter.status.in_([
                    ApprovalLetterStatus.REQUESTED.value,
                    ApprovalLetterStatus.PENDING_EXTRACTION.value,
                    ApprovalLetterStatus.PENDING_REVIEW.value,
                    ApprovalLetterStatus.APPROVED.value,
                ]),
            ).limit(1)
        )
        if active_letter is None:
            await create_letter_request_task(db, lot)
    await db.commit()
    return await get_lot_detail(db, lot_id)


async def _mark_lot_as_presale(db: AsyncSession, lot: Lot) -> None:
    lot.sale_type = SaleType.PRESALE
    await populate_lot_realtor(db, lot)


async def populate_lot_realtor(db: AsyncSession, lot: Lot) -> None:
    if lot.realtor_name and lot.realtor_email:
        return
    row = (
        await db.execute(
            select(Contact, Party.party_role)
            .join(Party, Party.contact_id == Contact.id)
            .join(SalesAgreement, SalesAgreement.id == Party.agreement_id)
            .where(
                SalesAgreement.lot_id == lot.id,
                Party.party_role.in_([PartyRole.BUYERS_REALTOR, PartyRole.SELLERS_REALTOR]),
            )
            .order_by(
                (Party.party_role == PartyRole.BUYERS_REALTOR).desc(),
                SalesAgreement.created_at.desc(),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return
    contact, _role = row
    lot.realtor_name = lot.realtor_name or contact.full_name
    lot.realtor_email = lot.realtor_email or contact.email
    lot.realtor_brokerage = lot.realtor_brokerage or contact.company_name


async def create_letter_request_task(db: AsyncSession, lot: Lot) -> PresaleTask:
    address = _lot_address(lot)
    realtor = lot.realtor_name or "realtor"
    buyers = await _buyer_names(db, lot.id)
    buyer_suffix = f" ({', '.join(buyers)})" if buyers else ""
    body = (
        f"Hi {realtor},\n\nPlease send the purchaser's lender approval letter for "
        f"{address}{buyer_suffix}.\n\nThank you."
    )
    return await _upsert_task(
        db,
        task_key=f"presale:{lot.id}:request-approval-letter",
        task_type="request_approval_letter",
        title=f"Request approval letter from {realtor} — {address}",
        lot_id=lot.id,
        payload={
            "to": lot.realtor_email,
            "subject": f"Approval letter request — {address}",
            "body": body,
            "missing_realtor": not bool(lot.realtor_name and lot.realtor_email),
        },
    )


async def mark_letter_requested(
    db: AsyncSession, lot_id: UUID, *, requested_from: str | None = None
) -> PresaleApprovalLetter:
    lot = await db.get(Lot, lot_id)
    if lot is None or lot.sale_type != SaleType.PRESALE:
        raise ValueError("Presale lot not found")
    now = datetime.now(timezone.utc)
    letter = await db.scalar(
        select(PresaleApprovalLetter)
        .where(
            PresaleApprovalLetter.lot_id == lot_id,
            PresaleApprovalLetter.status == ApprovalLetterStatus.REQUESTED.value,
            PresaleApprovalLetter.file_key.is_(None),
        )
        .order_by(PresaleApprovalLetter.created_at.desc())
        .limit(1)
    )
    if letter is None:
        version = int(
            await db.scalar(select(func.coalesce(func.max(PresaleApprovalLetter.version), 0)).where(PresaleApprovalLetter.lot_id == lot_id))
            or 0
        ) + 1
        letter = PresaleApprovalLetter(lot_id=lot_id, status=ApprovalLetterStatus.REQUESTED.value, version=version)
        db.add(letter)
    letter.requested_at = now
    letter.requested_from = requested_from or " · ".join(filter(None, [lot.realtor_name, lot.realtor_email])) or None
    task = await db.scalar(select(PresaleTask).where(PresaleTask.task_key == f"presale:{lot_id}:request-approval-letter"))
    if task is not None:
        task.status = "completed"
        task.completed_at = now
    await db.commit()
    await db.refresh(letter)
    return letter


async def update_letter(
    db: AsyncSession,
    letter_id: UUID,
    *,
    lot_id: UUID | None | object = ...,
    mark_as_presale: bool = False,
    extracted: dict[str, Any] | None = None,
    quality_score: int | None | object = ...,
) -> PresaleApprovalLetter:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        raise ValueError("Approval letter not found")
    previous_lot_id = letter.lot_id
    if lot_id is not ...:
        if lot_id is not None:
            lot = await db.get(Lot, lot_id)
            if lot is None:
                raise ValueError("Lot not found")
            if lot.sale_type != SaleType.PRESALE and not mark_as_presale:
                raise ValueError("Selected lot is not a presale")
            if lot.sale_type != SaleType.PRESALE:
                await _mark_lot_as_presale(db, lot)
            if letter.file_sha256:
                duplicate = await db.scalar(
                    select(PresaleApprovalLetter.id).where(
                        PresaleApprovalLetter.lot_id == lot_id,
                        PresaleApprovalLetter.file_sha256 == letter.file_sha256,
                        PresaleApprovalLetter.id != letter.id,
                    )
                )
                if duplicate is not None:
                    raise ValueError(f"This PDF is already linked to the selected lot ({duplicate})")
        letter.lot_id = lot_id  # type: ignore[assignment]
    if extracted is not None:
        letter.extracted = normalize_extracted_payload(extracted)
        letter.needs_manual_entry = any(
            _extraction_value_missing(name, letter.extracted) for name in REQUIRED_EXTRACTION_FIELDS
        )
    if quality_score is not ...:
        letter.quality_score = quality_score  # type: ignore[assignment]
    if letter.status == ApprovalLetterStatus.PENDING_REVIEW.value:
        await _upsert_review_task(db, letter)
    if previous_lot_id is not None and previous_lot_id != letter.lot_id:
        await recompute_readiness(db, previous_lot_id, notify=False)
    if letter.lot_id is not None:
        await recompute_readiness(db, letter.lot_id, letter_override=letter, notify=False)
    await db.commit()
    await db.refresh(letter)
    return letter


async def contact_lender(db: AsyncSession, letter_id: UUID, notes: str) -> PresaleApprovalLetter:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        raise ValueError("Approval letter not found")
    letter.lender_contacted_at = datetime.now(timezone.utc)
    letter.lender_contact_notes = notes.strip() or None
    if letter.lot_id is not None:
        await recompute_readiness(db, letter.lot_id, letter_override=letter)
        await _complete_task_by_key(db, f"presale:{letter.lot_id}:contact-lender")
    await db.commit()
    await db.refresh(letter)
    return letter


async def approve_letter(db: AsyncSession, letter_id: UUID, reviewer_id: UUID | None) -> dict[str, Any]:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        raise ValueError("Approval letter not found")
    if letter.status != ApprovalLetterStatus.PENDING_REVIEW.value:
        raise ValueError("Only approval letters pending review can be approved")
    if letter.lot_id is None:
        raise ValueError("Choose a presale lot before approving")
    if letter.quality_score is None:
        raise ValueError("Quality score is required before approval")
    lot = await db.get(Lot, letter.lot_id)
    if lot is None or lot.sale_type != SaleType.PRESALE:
        raise ValueError("Approval letter must be linked to a presale lot")

    now = datetime.now(timezone.utc)
    prior = list(
        (await db.scalars(select(PresaleApprovalLetter).where(
            PresaleApprovalLetter.lot_id == letter.lot_id,
            PresaleApprovalLetter.status == ApprovalLetterStatus.APPROVED.value,
            PresaleApprovalLetter.id != letter.id,
        ))).all()
    )
    for item in prior:
        item.status = ApprovalLetterStatus.SUPERSEDED.value
    letter.status = ApprovalLetterStatus.APPROVED.value
    letter.reviewed_by = reviewer_id
    letter.reviewed_at = now
    lot.active_approval_letter_id = letter.id
    await _complete_task_by_key(db, f"presale:letter:{letter.id}:review")
    await _complete_task_by_key(db, f"presale:{lot.id}:request-approval-letter")

    readiness = await recompute_readiness(db, lot.id, letter_override=letter, notify=False)
    await create_followup_tasks(db, lot, readiness, letter)
    await _notify(
        db,
        lot,
        "approval_letter_approved",
        _approval_notification_message(lot, readiness),
        {"approval_letter_id": str(letter.id), "readiness": readiness},
    )
    await _schedule_expiry_reminder(db, letter)
    await db.commit()
    return await get_lot_detail(db, lot.id)


async def reject_letter(
    db: AsyncSession, letter_id: UUID, *, reason: str, reviewer_id: UUID | None
) -> PresaleApprovalLetter:
    letter = await db.get(PresaleApprovalLetter, letter_id)
    if letter is None:
        raise ValueError("Approval letter not found")
    if letter.status != ApprovalLetterStatus.PENDING_REVIEW.value:
        raise ValueError("Only approval letters pending review can be rejected")
    letter.status = ApprovalLetterStatus.REJECTED.value
    letter.rejection_reason = reason.strip()
    letter.reviewed_by = reviewer_id
    letter.reviewed_at = datetime.now(timezone.utc)
    await _complete_task_by_key(db, f"presale:letter:{letter.id}:review")
    await db.commit()
    await db.refresh(letter)
    return letter


async def recompute_readiness(
    db: AsyncSession,
    lot_id: UUID,
    *,
    letter_override: PresaleApprovalLetter | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    context = await load_lot_package_context(db, lot_id, letter_override=letter_override)
    rules = await active_rules(db)
    old = context.lot.funding_readiness or {}
    result = evaluate_partner_rules(
        rules,
        ReadinessInputs(
            available_docs=context.available_docs,
            fields=context.fields,
            conditions=_conditions(context.letter),
            quality_score=context.letter.quality_score if context.letter else None,
            lender_contacted_at=context.letter.lender_contacted_at if context.letter else None,
            scu_capacity_ok=context.scu_capacity_ok,
        ),
    )
    context.lot.funding_partner_suggested = result["suggested"]
    context.lot.funding_readiness = result
    await _sync_package_lifecycle(db, context)
    if notify and _is_readiness_upgrade(old, result):
        partner = result.get("suggested")
        if partner:
            await _notify(
                db,
                context.lot,
                "readiness_upgrade",
                f"Presale {_lot_address(context.lot)} now {partner}-ready.",
                {"readiness": result},
            )
    return result


async def load_lot_package_context(
    db: AsyncSession,
    lot_id: UUID,
    *,
    letter_override: PresaleApprovalLetter | None = None,
) -> LotPackageContext:
    lot = await db.get(Lot, lot_id)
    if lot is None:
        raise ValueError("Lot not found")
    letter = letter_override
    if letter is None and lot.active_approval_letter_id:
        letter = await db.get(PresaleApprovalLetter, lot.active_approval_letter_id)
    if letter is None:
        letter = await db.scalar(
            select(PresaleApprovalLetter)
            .where(
                PresaleApprovalLetter.lot_id == lot_id,
                PresaleApprovalLetter.status.in_(
                    [
                        ApprovalLetterStatus.REQUESTED.value,
                        ApprovalLetterStatus.PENDING_EXTRACTION.value,
                        ApprovalLetterStatus.PENDING_REVIEW.value,
                    ]
                ),
            )
            .order_by(PresaleApprovalLetter.version.desc(), PresaleApprovalLetter.created_at.desc())
            .limit(1)
        )

    sale = await db.scalar(
        select(SalesAgreement).where(SalesAgreement.lot_id == lot_id).order_by(SalesAgreement.created_at.desc()).limit(1)
    )
    land_terms = await db.scalar(
        select(LotTerms).where(LotTerms.lot_id == lot_id).order_by(LotTerms.created_at.desc()).limit(1)
    )
    budget = await db.scalar(
        select(Budget).where(Budget.lot_agreement_id == lot_id, Budget.is_prelim.is_(True)).order_by(Budget.updated_at.desc()).limit(1)
    )
    prelim_total = None
    if budget is not None:
        prelim_total = await db.scalar(select(func.coalesce(func.sum(BudgetLine.estimate), 0)).where(BudgetLine.budget_id == budget.id))
        prelim_total = _decimal(prelim_total)

    items = list((await db.scalars(select(PresalePackageItem).where(PresalePackageItem.lot_id == lot_id))).all())
    item_map = {item.item_type: item for item in items}
    source_documents: dict[str, Document] = {}
    available: set[str] = set()
    if letter and letter.file_key and letter.status in {ApprovalLetterStatus.APPROVED.value, ApprovalLetterStatus.PENDING_REVIEW.value}:
        available.add("approval_letter")
    if sale is not None:
        available.add("otp_sale")
        document = await db.get(Document, sale.document_id)
        if document:
            source_documents["otp_sale"] = document
    if land_terms is not None:
        available.add("otp_land")
        land_agreement = await db.get(LandAgreement, land_terms.agreement_id)
        if land_agreement:
            document = await db.get(Document, land_agreement.document_id)
            if document:
                source_documents["otp_land"] = document
    if prelim_total is not None and prelim_total > 0:
        available.add("prelim_budget")
    appraisal = item_map.get("appraisal")
    if (
        appraisal
        and appraisal.received_at
        and "red river" in str((appraisal.metadata_ or {}).get("appraiser", "")).casefold()
    ):
        available.add("appraisal")
    plans = item_map.get("stamped_plans")
    if plans and plans.received_at:
        available.add("stamped_plans")

    buyers = await _buyer_names(db, lot_id)
    expected_draw = prelim_total
    fields = {
        "lot.building_type": lot.building_type.value if isinstance(lot.building_type, BuildingType) else lot.building_type,
        "otp_sale.sale_price": sale.sale_price if sale else None,
        "otp_land.lot_cost": land_terms.purchase_price if land_terms else None,
        "prelim_budget.total": prelim_total,
        "approval_letter.approved_amount": (letter.extracted or {}).get("approved_amount") if letter else None,
    }
    capacity_ok = await _scu_capacity_ok(db, expected_draw)
    return LotPackageContext(
        lot=lot,
        letter=letter,
        sale_agreement=sale,
        land_terms=land_terms,
        prelim_budget=budget,
        prelim_total=prelim_total,
        buyer_names=buyers,
        package_items=item_map,
        source_documents=source_documents,
        available_docs=available,
        fields=fields,
        scu_capacity_ok=capacity_ok,
    )


async def active_rules(db: AsyncSession) -> list[PartnerRuleData]:
    records = list(
        (await db.scalars(select(FundingPartnerRule).where(FundingPartnerRule.active.is_(True)).order_by(FundingPartnerRule.priority))).all()
    )
    return [_rule_data(record) for record in records]


async def list_partner_rules(db: AsyncSession) -> list[dict[str, Any]]:
    records = list((await db.scalars(select(FundingPartnerRule).order_by(FundingPartnerRule.priority, FundingPartnerRule.partner_code))).all())
    return [_rule_payload(record) for record in records]


async def create_partner_rule(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    partner_code = str(data["partner_code"]).strip().upper()
    if await db.get(FundingPartnerRule, partner_code) is not None:
        raise ValueError("Partner code already exists")
    record = FundingPartnerRule(**{**data, "partner_code": partner_code, "package_recipient": str(data["package_recipient"]) if data.get("package_recipient") else None})
    db.add(record)
    await recompute_all_readiness(db)
    await db.commit()
    await db.refresh(record)
    return _rule_payload(record)


async def update_partner_rule(db: AsyncSession, partner_code: str, updates: dict[str, Any]) -> dict[str, Any]:
    record = await db.get(FundingPartnerRule, partner_code.upper())
    if record is None:
        raise ValueError("Funding partner rule not found")
    for key, value in updates.items():
        if key == "package_recipient" and value is not None:
            value = str(value)
        setattr(record, key, value)
    await recompute_all_readiness(db)
    await db.commit()
    await db.refresh(record)
    return _rule_payload(record)


async def delete_partner_rule(db: AsyncSession, partner_code: str) -> None:
    record = await db.get(FundingPartnerRule, partner_code.upper())
    if record is None:
        raise ValueError("Funding partner rule not found")
    await db.delete(record)
    await recompute_all_readiness(db)
    await db.commit()


async def recompute_all_readiness(db: AsyncSession) -> int:
    lot_ids = list((await db.scalars(select(Lot.id).where(Lot.sale_type == SaleType.PRESALE))).all())
    for lot_id in lot_ids:
        await recompute_readiness(db, lot_id, notify=False)
    return len(lot_ids)


async def list_notifications(db: AsyncSession, *, unread_only: bool = False) -> list[dict[str, Any]]:
    query = select(PresaleNotification)
    if unread_only:
        query = query.where(PresaleNotification.read_at.is_(None))
    records = list((await db.scalars(query.order_by(PresaleNotification.created_at.desc()).limit(100))).all())
    return [
        {
            "id": str(record.id),
            "lot_id": str(record.lot_id) if record.lot_id else None,
            "type": record.notification_type,
            "message": record.message,
            "payload": record.payload or {},
            "read_at": record.read_at.isoformat() if record.read_at else None,
            "created_at": record.created_at.isoformat(),
        }
        for record in records
    ]


async def mark_notification_read(db: AsyncSession, notification_id: UUID) -> None:
    record = await db.get(PresaleNotification, notification_id)
    if record is None:
        raise ValueError("Notification not found")
    record.read_at = datetime.now(timezone.utc)
    await db.commit()


async def create_followup_tasks(
    db: AsyncSession,
    lot: Lot,
    readiness: dict[str, Any],
    letter: PresaleApprovalLetter,
) -> None:
    partners = readiness.get("partners", {})
    candidate: dict[str, Any] | None = None
    for _code, value in partners.items():
        if value.get("state") != "disqualified":
            candidate = value
            break
    missing = set(candidate.get("missing", [])) if candidate else set()
    for item in missing:
        await _create_missing_item_task(db, lot, item)

    scu = partners.get("SCU", {})
    if scu.get("state") == "blocked_by_quality":
        await _upsert_task(
            db,
            task_key=f"presale:{lot.id}:contact-lender",
            task_type="contact_lender",
            title=f"Contact lender re: {_lot_address(lot)}",
            lot_id=lot.id,
            approval_letter_id=letter.id,
            payload={
                "broker_name": (letter.extracted or {}).get("broker_name"),
                "broker_email": (letter.extracted or {}).get("broker_email"),
                "quality_score": letter.quality_score,
                "required_score": scu.get("min_quality_score"),
            },
        )
    if scu.get("state") == "disqualified":
        await _upsert_task(
            db,
            task_key=f"presale:{lot.id}:scu-disqualified:{letter.id}",
            task_type="route_alternate_lender",
            title=f"SCU disqualified — route {_lot_address(lot)} to alternate lender",
            lot_id=lot.id,
            approval_letter_id=letter.id,
            payload={"conditions": scu.get("disqualified_by", []), "href": f"/presales/lots/{lot.id}"},
        )


async def mark_package_item_action(
    db: AsyncSession, lot_id: UUID, item_type: str, action: str
) -> dict[str, Any]:
    if item_type not in PACKAGE_ITEM_TYPES:
        raise ValueError("Unknown presale package item")
    lot = await db.get(Lot, lot_id)
    if lot is None:
        raise ValueError("Lot not found")
    item = await _get_or_create_item(db, lot_id, item_type)
    now = datetime.now(timezone.utc)
    if action == "requested":
        item.requested_at = now
    elif action == "ordered":
        item.ordered_at = now
        item.requested_at = item.requested_at or now
        if item_type == "appraisal":
            item.metadata_ = {**(item.metadata_ or {}), "appraiser": "Red River Group"}
    else:
        raise ValueError("Unsupported package item action")
    await db.commit()
    return await get_lot_detail(db, lot_id)


async def store_package_document(
    db: AsyncSession,
    *,
    lot_id: UUID,
    item_type: str,
    filename: str,
    content: bytes,
    content_type: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if item_type not in {"appraisal", "stamped_plans"}:
        raise ValueError("Only appraisal and stamped plans can be uploaded here")
    lot = await db.get(Lot, lot_id)
    if lot is None:
        raise ValueError("Lot not found")
    if not content or not content.startswith(b"%PDF"):
        raise ValueError("Package document must be a PDF")
    digest = hashlib.sha256(content).hexdigest()
    key = f"presales/{lot_id}/package/{item_type}/{digest}.pdf"
    upload_financing_document(key=key, content=content, content_type=content_type or "application/pdf")
    item = await _get_or_create_item(db, lot_id, item_type)
    now = datetime.now(timezone.utc)
    document = await db.scalar(select(Document).where(Document.checksum_sha256 == digest))
    if document is None:
        document = Document(
            org_id=settings.default_org_id,
            doc_type=DocType.APPRAISAL if item_type == "appraisal" else DocType.STAMPED_PLANS,
            status=DocumentStatus.APPROVED,
            original_filename=_safe_filename(filename),
            minio_bucket=DOCUMENT_BUCKET,
            minio_key=key,
            file_size_bytes=len(content),
            checksum_sha256=digest,
            received_at=now,
        )
        db.add(document)
        await db.flush()
    item.file_key = key
    item.document_id = document.id
    item.original_filename = _safe_filename(filename)
    item.received_at = now
    item.metadata_ = {
        **(item.metadata_ or {}),
        **metadata,
        **({"appraiser": metadata.get("appraiser") or "Red River Group"} if item_type == "appraisal" else {}),
        **(
            {
                "stamp_detected": metadata.get("stamp_detected", True),
                "building_type": metadata.get("building_type") or _enum_value(lot.building_type),
            }
            if item_type == "stamped_plans"
            else {}
        ),
        "sha256": digest,
        "mime": content_type or "application/pdf",
    }
    readiness = await recompute_readiness(db, lot_id)
    await _complete_task_by_key(db, f"presale:{lot_id}:missing:{item_type}")
    await db.commit()
    return await get_lot_detail(db, lot_id)


async def complete_task(db: AsyncSession, task_id: UUID, notes: str | None = None) -> PresaleTask:
    task = await db.get(PresaleTask, task_id)
    if task is None:
        raise ValueError("Presale task not found")
    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)
    if notes:
        task.payload = {**(task.payload or {}), "completion_notes": notes}
    await db.commit()
    await db.refresh(task)
    return task


async def create_package_draft(db: AsyncSession, lot_id: UUID, partner_code: str) -> dict[str, Any]:
    context = await load_lot_package_context(db, lot_id)
    readiness = await recompute_readiness(db, lot_id, notify=False)
    partner = readiness.get("partners", {}).get(partner_code)
    if not partner or partner.get("state") != "ready":
        raise ValueError(f"{partner_code} package is not ready")
    rule = await db.get(FundingPartnerRule, partner_code)
    if rule is None or not rule.package_docs:
        return {"mode": "facility_assignment", "url": f"/financing?property_id={context.lot.property_id or ''}"}
    attachments = await collect_package_attachments(db, context, list(rule.package_docs))
    subject, body = _package_email_content(context, rule, attachments)
    try:
        draft_id, message_id = await _create_gmail_draft(
            recipient=rule.package_recipient or "",
            subject=subject,
            body=body,
            attachments=attachments,
        )
        return {
            "mode": "gmail_draft",
            "draft_id": draft_id,
            "message_id": message_id,
            "gmail_url": f"https://mail.google.com/mail/u/0/#drafts/{message_id}",
            "subject": subject,
            "body": body,
        }
    except Exception as exc:
        return {
            "mode": "download",
            "download_url": f"/api/presales/lots/{lot_id}/packages/{partner_code}/fallback.zip",
            "subject": subject,
            "body": body,
            "reason": str(exc),
        }


async def package_fallback_zip(db: AsyncSession, lot_id: UUID, partner_code: str) -> tuple[bytes, str]:
    context = await load_lot_package_context(db, lot_id)
    rule = await db.get(FundingPartnerRule, partner_code)
    if rule is None:
        raise ValueError("Funding partner not found")
    attachments = await collect_package_attachments(db, context, list(rule.package_docs))
    subject, body = _package_email_content(context, rule, attachments)
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("email-body.txt", f"Subject: {subject}\nTo: {rule.package_recipient or ''}\n\n{body}")
        for name, content, _mime in attachments:
            archive.writestr(name, content)
    return output.getvalue(), f"presale-package-{_slug(_lot_address(context.lot))}-{partner_code.lower()}.zip"


async def mark_package_sent(db: AsyncSession, lot_id: UUID, partner_code: str) -> dict[str, Any]:
    context = await load_lot_package_context(db, lot_id)
    if context.lot.package_sent_at is not None:
        if context.lot.package_sent_to == partner_code:
            return await get_lot_detail(db, lot_id)
        raise ValueError(f"Package was already marked sent to {context.lot.package_sent_to}")
    readiness = await recompute_readiness(db, lot_id, notify=False)
    partner = readiness.get("partners", {}).get(partner_code)
    if not partner or partner.get("state") != "ready":
        raise ValueError(f"{partner_code} package is not ready")
    now = datetime.now(timezone.utc)
    context.lot.package_sent_to = partner_code
    context.lot.package_sent_at = now
    await _upsert_task(
        db,
        task_key=f"presale:{lot_id}:await:{partner_code}:{now.date().isoformat()}",
        task_type="await_partner_response",
        title=f"Await {partner_code} response — {_lot_address(context.lot)}",
        lot_id=lot_id,
        payload={"partner_code": partner_code, "sent_at": now.isoformat()},
    )
    await _notify(
        db,
        context.lot,
        "package_sent",
        f"Presale package for {_lot_address(context.lot)} marked sent to {partner_code}.",
        {"partner_code": partner_code, "sent_at": now.isoformat()},
    )
    await db.commit()
    return await get_lot_detail(db, lot_id)


async def collect_package_attachments(
    db: AsyncSession, context: LotPackageContext, doc_types: list[str]
) -> list[tuple[str, bytes, str]]:
    attachments: list[tuple[str, bytes, str]] = []
    for doc_type in doc_types:
        if doc_type == "approval_letter" and context.letter and context.letter.file_key:
            attachments.append((context.letter.original_filename or "approval-letter.pdf", get_financing_document(key=context.letter.file_key), "application/pdf"))
            continue
        if doc_type in {"otp_land", "otp_sale"}:
            document = context.source_documents.get(doc_type)
            if document:
                attachments.append((document.original_filename or f"{doc_type}.pdf", get_financing_document(key=document.minio_key), "application/pdf"))
            continue
        if doc_type in {"appraisal", "stamped_plans"}:
            item = context.package_items.get(doc_type)
            if item and item.file_key:
                attachments.append((item.original_filename or f"{doc_type}.pdf", get_financing_document(key=item.file_key), "application/pdf"))
            continue
        if doc_type == "prelim_budget" and context.prelim_budget:
            budget_text = _budget_attachment_text(context)
            attachments.append(("prelim-budget.txt", budget_text.encode("utf-8"), "text/plain"))
    missing = [name for name in doc_types if name not in context.available_docs]
    if missing:
        raise ValueError(f"Package is missing attachments: {', '.join(missing)}")
    return attachments


async def get_lot_detail(db: AsyncSession, lot_id: UUID) -> dict[str, Any]:
    context = await load_lot_package_context(db, lot_id)
    rules = await active_rules(db)
    readiness = evaluate_partner_rules(
        rules,
        ReadinessInputs(
            available_docs=context.available_docs,
            fields=context.fields,
            conditions=_conditions(context.letter),
            quality_score=context.letter.quality_score if context.letter else None,
            lender_contacted_at=context.letter.lender_contacted_at if context.letter else None,
            scu_capacity_ok=context.scu_capacity_ok,
        ),
    )
    letters = list(
        (await db.scalars(select(PresaleApprovalLetter).where(PresaleApprovalLetter.lot_id == lot_id).order_by(PresaleApprovalLetter.version.desc()))).all()
    )
    tasks = list(
        (await db.scalars(select(PresaleTask).where(PresaleTask.lot_id == lot_id, PresaleTask.status == "open").order_by(PresaleTask.created_at))).all()
    )
    return {
        "lot": _lot_payload(context.lot),
        "buyer_names": context.buyer_names,
        "active_letter": _letter_payload(context.letter) if context.letter else None,
        "letter_history": [_letter_payload(letter) for letter in letters],
        "package_items": _package_item_payloads(context),
        "readiness": readiness,
        "quality_flags": quality_flags(context, readiness),
        "tasks": [_task_payload(task) for task in tasks],
    }


async def list_presales_board(db: AsyncSession) -> list[dict[str, Any]]:
    lot_ids = list(
        (await db.scalars(select(Lot.id).where(Lot.sale_type == SaleType.PRESALE).order_by(Lot.created_at.desc()))).all()
    )
    return [await get_lot_detail(db, lot_id) for lot_id in lot_ids]


async def list_extension_lots(db: AsyncSession, search: str = "") -> list[dict[str, Any]]:
    lots = list(
        (await db.scalars(select(Lot).order_by(Lot.created_at.desc()))).all()
    )
    needle = " ".join(search.casefold().split())
    output: list[dict[str, Any]] = []
    for lot in lots:
        buyers = await _buyer_names(db, lot.id)
        haystack = " ".join([_lot_address(lot), *buyers]).casefold()
        if needle and needle not in haystack:
            continue
        output.append({
            "id": str(lot.id),
            "address": _lot_address(lot),
            "purchaser_names": buyers,
            "created_at": lot.created_at.isoformat(),
            "is_presale": lot.sale_type == SaleType.PRESALE,
        })
    return output


async def list_review_queue(db: AsyncSession) -> dict[str, Any]:
    letters = list(
        (await db.scalars(select(PresaleApprovalLetter).where(PresaleApprovalLetter.status == ApprovalLetterStatus.PENDING_REVIEW.value).order_by(PresaleApprovalLetter.created_at))).all()
    )
    tasks = list(
        (await db.scalars(select(PresaleTask).where(PresaleTask.status == "open").order_by(PresaleTask.created_at))).all()
    )
    return {
        "letters": [_letter_payload(letter) for letter in letters],
        "tasks": [_task_payload(task) for task in tasks],
    }


async def list_unmatched(db: AsyncSession) -> list[dict[str, Any]]:
    letters = list(
        (await db.scalars(select(PresaleApprovalLetter).where(PresaleApprovalLetter.lot_id.is_(None)).order_by(PresaleApprovalLetter.created_at.desc()))).all()
    )
    return [_letter_payload(letter) for letter in letters]


async def process_expiry_reminders(db: AsyncSession) -> int:
    target = date.today() + timedelta(days=14)
    letters = list(
        (await db.scalars(select(PresaleApprovalLetter).where(PresaleApprovalLetter.status == ApprovalLetterStatus.APPROVED.value))).all()
    )
    count = 0
    for letter in letters:
        expiry = _date((letter.extracted or {}).get("expiry_date"))
        if expiry != target or letter.lot_id is None:
            continue
        lot = await db.get(Lot, letter.lot_id)
        if lot is None or lot.status.value in {"possession", "warranty"}:
            continue
        exists = await db.scalar(select(PresaleNotification.id).where(
            PresaleNotification.lot_id == lot.id,
            PresaleNotification.notification_type == "approval_letter_expiry",
            PresaleNotification.payload["approval_letter_id"].as_string() == str(letter.id),
        ))
        if exists is None:
            await _notify(db, lot, "approval_letter_expiry", f"Approval letter for {_lot_address(lot)} expires in 14 days.", {"approval_letter_id": str(letter.id), "expiry_date": expiry.isoformat()})
            count += 1
    await db.commit()
    return count


def normalize_extracted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for field in MONEY_FIELDS:
        value = _decimal(result.get(field))
        result[field] = format(value, ".2f") if value is not None else None
    result["document_type"] = result.get("document_type") if result.get("document_type") in {"pre_approval", "firm_commitment", "other"} else "other"
    result["insurer"] = result.get("insurer") if result.get("insurer") in {"CMHC", "Sagen", "Canada Guaranty", "none", "unknown"} else "unknown"
    purchaser_names = result.get("purchaser_names")
    result["purchaser_names"] = [str(name).strip() for name in purchaser_names if str(name).strip()] if isinstance(purchaser_names, list) else []
    conditions = result.get("conditions")
    normalized_conditions: list[dict[str, Any]] = []
    if isinstance(conditions, list):
        for condition in conditions:
            if not isinstance(condition, dict) or not str(condition.get("text") or "").strip():
                continue
            category = str(condition.get("category") or "other")
            normalized_conditions.append({
                "text": str(condition.get("text")).strip(),
                "category": category if category in CONDITION_CATEGORIES else "other",
                "deadline": _date_string(condition.get("deadline")),
            })
    result["conditions"] = normalized_conditions
    result["expiry_date"] = _date_string(result.get("expiry_date"))
    result["signed"] = bool(result.get("signed"))
    result["property_address"] = str(result.get("property_address") or "").strip()
    return result


def quality_flags(
    context: LotPackageContext, readiness: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    letter = context.letter
    if letter is None:
        return []
    payload = letter.extracted or {}
    flags: list[dict[str, Any]] = []
    if payload.get("document_type") == "pre_approval" or _conditions(letter):
        flags.append({"code": "conditional", "label": "Conditional approval"})
    expiry = _date(payload.get("expiry_date"))
    closing = context.sale_agreement.possession_date if context.sale_agreement else None
    anchor = closing or date.today()
    if expiry and expiry < anchor + timedelta(days=30):
        flags.append({"code": "short_expiry", "label": "Expires within 30 days"})
    approved = _decimal(payload.get("approved_amount"))
    purchase = _decimal(payload.get("purchase_price"))
    down = _decimal(payload.get("down_payment")) or Decimal("0")
    if approved is not None and purchase is not None and approved < purchase - down:
        flags.append({"code": "amount_gap", "label": "Approval amount is below purchase price less down payment"})
    if not payload.get("signed"):
        flags.append({"code": "unsigned", "label": "Letter appears unsigned"})
    scu_rule = readiness if readiness is not None else (context.lot.funding_readiness or {})
    scu = scu_rule.get("partners", {}).get("SCU", {})
    if scu.get("state") == "disqualified":
        flags.append({"code": "scu_disqualified", "label": "SCU disqualified by a letter condition"})
    return flags


async def _create_missing_item_task(db: AsyncSession, lot: Lot, item: str) -> None:
    address = _lot_address(lot)
    definitions: dict[str, tuple[str, str, dict[str, Any]]] = {
        "appraisal": ("order_appraisal", f"Order formal appraisal — {address}", {"appraiser": "Red River Group"}),
        "prelim_budget": ("request_prelim_budget", f"Request prelim budget from Joan — {address}", {"recipient": "Joan", "building_type": _enum_value(lot.building_type), "plan_reference": lot.plan}),
        "stamped_plans": ("upload_stamped_plans", f"Upload stamped plans — {address}", {}),
        "otp_land": ("ingest_otp_land", f"Ingest OTP (Land) — {address}", {"href": "/documents"}),
        "otp_sale": ("ingest_otp_sale", f"Ingest OTP (Sale) — {address}", {"href": "/documents"}),
        "lot.building_type": ("set_building_type", f"Set building type — {address}", {"options": ["bungalow", "two_storey", "duplex", "other"]}),
    }
    definition = definitions.get(item)
    if definition is None:
        return
    task_type, title, payload = definition
    await _upsert_task(db, task_key=f"presale:{lot.id}:missing:{item}", task_type=task_type, title=title, lot_id=lot.id, payload=payload)


async def _upsert_review_task(db: AsyncSession, letter: PresaleApprovalLetter) -> PresaleTask:
    address = "Unmatched"
    if letter.lot_id:
        lot = await db.get(Lot, letter.lot_id)
        if lot:
            address = _lot_address(lot)
    payload = letter.extracted or {}
    title = f"Presale approval letter — {address}"
    return await _upsert_task(
        db,
        task_key=f"presale:letter:{letter.id}:review",
        task_type="review_approval_letter",
        title=title,
        lot_id=letter.lot_id,
        approval_letter_id=letter.id,
        payload={
            "summary": f"{payload.get('lender_name') or 'Unknown lender'} via {payload.get('broker_name') or 'unknown broker'} · {payload.get('document_type') or 'unknown'} · ${payload.get('approved_amount') or '—'} · expires {payload.get('expiry_date') or '—'} · {len(payload.get('conditions') or [])} conditions",
            "needs_manual_entry": letter.needs_manual_entry,
        },
    )


async def _upsert_task(
    db: AsyncSession,
    *,
    task_key: str,
    task_type: str,
    title: str,
    lot_id: UUID | None,
    payload: dict[str, Any],
    approval_letter_id: UUID | None = None,
) -> PresaleTask:
    assignee_id, assignee_name = await _task_assignee(db, task_type)
    payload = {**payload, "assignee_name": assignee_name}
    task = await db.scalar(select(PresaleTask).where(PresaleTask.task_key == task_key))
    if task is None:
        task = PresaleTask(
            task_key=task_key,
            task_type=task_type,
            title=title,
            lot_id=lot_id,
            approval_letter_id=approval_letter_id,
            assignee_id=assignee_id,
            payload=payload,
        )
        db.add(task)
    elif task.status != "open":
        task.status = "open"
        task.completed_at = None
    task.title = title
    task.payload = payload
    task.lot_id = lot_id
    task.approval_letter_id = approval_letter_id
    task.assignee_id = assignee_id
    return task


async def _get_or_create_item(db: AsyncSession, lot_id: UUID, item_type: str) -> PresalePackageItem:
    item = await db.scalar(select(PresalePackageItem).where(PresalePackageItem.lot_id == lot_id, PresalePackageItem.item_type == item_type))
    if item is None:
        item = PresalePackageItem(lot_id=lot_id, item_type=item_type)
        db.add(item)
        await db.flush()
    return item


async def _sync_package_lifecycle(db: AsyncSession, context: LotPackageContext) -> None:
    for item_type in ("otp_land", "otp_sale", "prelim_budget"):
        if item_type not in context.available_docs:
            continue
        item = context.package_items.get(item_type) or await _get_or_create_item(db, context.lot.id, item_type)
        received_at = (
            context.prelim_budget.received_at
            if item_type == "prelim_budget" and context.prelim_budget and context.prelim_budget.received_at
            else datetime.now(timezone.utc)
        )
        item.received_at = item.received_at or received_at
        if item_type in context.source_documents:
            item.document_id = context.source_documents[item_type].id
        if item_type == "prelim_budget" and context.prelim_budget:
            item.metadata_ = {**(item.metadata_ or {}), "budget_id": str(context.prelim_budget.id), "total": str(context.prelim_total or 0)}
        await _complete_task_by_key(db, f"presale:{context.lot.id}:missing:{item_type}")


async def _complete_task_by_key(db: AsyncSession, task_key: str) -> None:
    task = await db.scalar(select(PresaleTask).where(PresaleTask.task_key == task_key, PresaleTask.status == "open"))
    if task:
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)


async def _notify(db: AsyncSession, lot: Lot, notification_type: str, message: str, payload: dict[str, Any]) -> None:
    db.add(PresaleNotification(
        lot_id=lot.id,
        recipient_id=await _nicholas_user_id(db),
        notification_type=notification_type,
        message=message,
        payload=payload,
    ))


async def _schedule_expiry_reminder(db: AsyncSession, letter: PresaleApprovalLetter) -> None:
    expiry = _date((letter.extracted or {}).get("expiry_date"))
    if expiry is None or letter.lot_id is None:
        return
    due = datetime.combine(expiry - timedelta(days=14), datetime.min.time(), tzinfo=timezone.utc)
    if due <= datetime.now(timezone.utc):
        return
    existing = await db.scalar(select(Reminder.id).where(
        Reminder.entity_table == "core.presale_approval_letters",
        Reminder.entity_id == letter.id,
        Reminder.reminder_type == "approval_letter_expiry_14d",
    ))
    if existing is None:
        db.add(Reminder(lot_id=letter.lot_id, entity_table="core.presale_approval_letters", entity_id=letter.id, reminder_type="approval_letter_expiry_14d", due_at=due))


async def _nicholas_user_id(db: AsyncSession) -> UUID | None:
    user_id = await db.scalar(select(User.id).where(User.is_active.is_(True), or_(func.lower(User.full_name).like("nicholas%"), func.lower(User.email).like("nicholas%"))).order_by(User.created_at).limit(1))
    if user_id is None:
        user_id = await db.scalar(select(User.id).where(User.is_active.is_(True), User.role == UserRole.ADMIN).order_by(User.created_at).limit(1))
    return user_id


async def _task_assignee(db: AsyncSession, task_type: str) -> tuple[UUID | None, str]:
    if task_type == "request_prelim_budget":
        joan = await db.scalar(
            select(User)
            .where(
                User.is_active.is_(True),
                or_(func.lower(User.full_name).like("joan%"), func.lower(User.email).like("joan%")),
            )
            .order_by(User.created_at)
            .limit(1)
        )
        if joan is not None:
            return joan.id, joan.full_name
    nicholas_id = await _nicholas_user_id(db)
    if nicholas_id is None:
        return None, "Nicholas"
    nicholas = await db.get(User, nicholas_id)
    return nicholas_id, nicholas.full_name if nicholas else "Nicholas"


async def _buyer_names(db: AsyncSession, lot_id: UUID) -> list[str]:
    names = list((await db.scalars(
        select(Contact.full_name)
        .join(Party, Party.contact_id == Contact.id)
        .join(SalesAgreement, SalesAgreement.id == Party.agreement_id)
        .where(SalesAgreement.lot_id == lot_id, Party.party_role.in_([PartyRole.BUYER, PartyRole.CO_BUYER]))
        .order_by(SalesAgreement.created_at.desc(), Party.is_primary.desc())
    )).all())
    return list(dict.fromkeys(name for name in names if name))


async def _scu_capacity_ok(db: AsyncSession, expected_draw: Decimal | None) -> bool | None:
    if expected_draw is None or expected_draw <= 0:
        return None
    program_ids = list((await db.scalars(
        select(LenderProgram.id)
        .join(Lender, Lender.id == LenderProgram.lender_id)
        .where(LenderProgram.active.is_(True), or_(func.lower(Lender.name).contains("steinbach"), func.lower(Lender.name) == "scu"))
    )).all())
    if not program_ids:
        return False
    for program_id in program_ids:
        capacity = await get_program_capacity(db, program_id)
        if capacity.remaining < expected_draw:
            continue
        if any(allocation.remaining >= expected_draw and allocation.units_remaining > 0 for allocation in capacity.allocations):
            return True
    return False


async def _create_gmail_draft(
    *, recipient: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]]
) -> tuple[str, str]:
    import asyncio
    import os
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    scope = "https://www.googleapis.com/auth/gmail.compose"
    token_path = os.path.expanduser(settings.google_oauth_token_path)
    if not os.path.exists(token_path):
        raise RuntimeError("Google OAuth authorization with gmail.compose is required")

    def create() -> tuple[str, str]:
        credentials = Credentials.from_authorized_user_file(token_path)
        if not credentials.has_scopes([scope]):
            raise RuntimeError("Google OAuth token does not include gmail.compose")
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials.valid:
            raise RuntimeError("Google OAuth authorization is invalid")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.gmail_sender_email
        if recipient:
            message["To"] = recipient
        message.set_content(body)
        for filename, content, mime in attachments:
            main_type, _, sub_type = mime.partition("/")
            message.add_attachment(content, maintype=main_type or "application", subtype=sub_type or "octet-stream", filename=filename)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = build("gmail", "v1", credentials=credentials, cache_discovery=False).users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return str(result["id"]), str(result.get("message", {}).get("id") or result["id"])

    return await asyncio.to_thread(create)


def _package_email_content(
    context: LotPackageContext,
    rule: FundingPartnerRule,
    attachments: list[tuple[str, bytes, str]],
) -> tuple[str, str]:
    address = _lot_address(context.lot)
    subject = f"Presale funding package — {address} — Connection Homes"
    names = ", ".join(context.buyer_names) or "—"
    sale_price = _money_text(context.sale_agreement.sale_price if context.sale_agreement else None)
    building = _enum_value(context.lot.building_type) or "—"
    checklist = "\n".join(f"✓ {filename}" for filename, _content, _mime in attachments)
    body = (
        f"Hello,\n\nPlease find the presale funding package for {address}.\n\n"
        f"Purchaser: {names}\nSale price: {sale_price}\nBuilding type: {building}\n\n"
        f"Attachment checklist:\n{checklist}\n\nThank you,\nConnection Homes"
    )
    return subject, body


def _budget_attachment_text(context: LotPackageContext) -> str:
    return (
        f"Preliminary budget\nLot: {_lot_address(context.lot)}\n"
        f"Budget: {context.prelim_budget.label if context.prelim_budget else ''}\n"
        f"Total: {_money_text(context.prelim_total)}\n"
    )


def _package_item_payloads(context: LotPackageContext) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item_type in PACKAGE_ITEM_TYPES:
        item = context.package_items.get(item_type)
        output[item_type] = {
            "requested_at": item.requested_at.isoformat() if item and item.requested_at else None,
            "ordered_at": item.ordered_at.isoformat() if item and item.ordered_at else None,
            "received_at": item.received_at.isoformat() if item and item.received_at else None,
            "present": item_type in context.available_docs,
            "filename": item.original_filename if item else None,
            "metadata": item.metadata_ if item else {},
        }
    if context.letter:
        output["approval_letter"] = {
            "requested_at": context.letter.requested_at.isoformat() if context.letter.requested_at else None,
            "ordered_at": None,
            "received_at": context.letter.reviewed_at.isoformat() if context.letter.status == ApprovalLetterStatus.APPROVED.value and context.letter.reviewed_at else None,
            "present": "approval_letter" in context.available_docs,
            "filename": context.letter.original_filename,
            "metadata": {"quality_score": context.letter.quality_score},
        }
    else:
        output["approval_letter"] = {"requested_at": None, "ordered_at": None, "received_at": None, "present": False, "filename": None, "metadata": {}}
    return output


def _lot_payload(lot: Lot) -> dict[str, Any]:
    return {
        "id": str(lot.id),
        "property_id": str(lot.property_id) if lot.property_id else None,
        "address": _lot_address(lot),
        "sale_type": _enum_value(lot.sale_type),
        "building_type": _enum_value(lot.building_type),
        "realtor_name": lot.realtor_name,
        "realtor_email": lot.realtor_email,
        "realtor_brokerage": lot.realtor_brokerage,
        "funding_partner_suggested": lot.funding_partner_suggested,
        "package_sent_to": lot.package_sent_to,
        "package_sent_at": lot.package_sent_at.isoformat() if lot.package_sent_at else None,
    }


def _letter_payload(letter: PresaleApprovalLetter | None) -> dict[str, Any] | None:
    if letter is None:
        return None
    return {
        "id": str(letter.id),
        "lot_id": str(letter.lot_id) if letter.lot_id else None,
        "status": letter.status,
        "version": letter.version,
        "requested_at": letter.requested_at.isoformat() if letter.requested_at else None,
        "requested_from": letter.requested_from,
        "original_filename": letter.original_filename,
        "email_from": letter.email_from,
        "email_subject": letter.email_subject,
        "email_received_at": letter.email_received_at.isoformat() if letter.email_received_at else None,
        "extracted": letter.extracted or {},
        "extraction_confidence": letter.extraction_confidence or {},
        "low_confidence_fields": letter.low_confidence_fields or [],
        "needs_manual_entry": letter.needs_manual_entry,
        "quality_score": letter.quality_score,
        "lender_contacted_at": letter.lender_contacted_at.isoformat() if letter.lender_contacted_at else None,
        "lender_contact_notes": letter.lender_contact_notes,
        "rejection_reason": letter.rejection_reason,
        "reviewed_by": str(letter.reviewed_by) if letter.reviewed_by else None,
        "reviewed_at": letter.reviewed_at.isoformat() if letter.reviewed_at else None,
        "created_at": letter.created_at.isoformat(),
        "updated_at": letter.updated_at.isoformat(),
        "preview_url": f"/api/presales/approval-letters/{letter.id}/file" if letter.file_key else None,
    }


def _task_payload(task: PresaleTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "lot_id": str(task.lot_id) if task.lot_id else None,
        "approval_letter_id": str(task.approval_letter_id) if task.approval_letter_id else None,
        "task_type": task.task_type,
        "title": task.title,
        "status": task.status,
        "payload": task.payload or {},
        "created_at": task.created_at.isoformat(),
    }


def _rule_data(rule: FundingPartnerRule) -> PartnerRuleData:
    return PartnerRuleData(
        partner_code=rule.partner_code,
        display_name=rule.display_name,
        priority=rule.priority,
        required_docs=list(rule.required_docs or []),
        required_fields=list(rule.required_fields or []),
        disqualifying_conditions=list(rule.disqualifying_conditions or []),
        min_quality_score=rule.min_quality_score,
        formula=rule.formula,
        package_recipient=rule.package_recipient,
        package_docs=list(rule.package_docs or []),
    )


def _rule_payload(rule: FundingPartnerRule) -> dict[str, Any]:
    return {
        "partner_code": rule.partner_code,
        "display_name": rule.display_name,
        "priority": rule.priority,
        "required_docs": list(rule.required_docs or []),
        "required_fields": list(rule.required_fields or []),
        "disqualifying_conditions": list(rule.disqualifying_conditions or []),
        "min_quality_score": rule.min_quality_score,
        "formula": rule.formula,
        "max_advance_rule": rule.max_advance_rule,
        "package_recipient": rule.package_recipient,
        "package_docs": list(rule.package_docs or []),
        "active": rule.active,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _conditions(letter: PresaleApprovalLetter | None) -> list[dict[str, Any]]:
    conditions = (letter.extracted or {}).get("conditions") if letter else []
    return [condition for condition in conditions if isinstance(condition, dict)] if isinstance(conditions, list) else []


def _approval_notification_message(lot: Lot, readiness: dict[str, Any]) -> str:
    disqualified = [code for code, partner in readiness.get("partners", {}).items() if partner.get("state") == "disqualified"]
    message = f"Approval letter approved for {_lot_address(lot)}. Suggested partner: {readiness.get('suggested') or 'none yet'}."
    if disqualified:
        message += f" Disqualified: {', '.join(disqualified)}."
    return message


def _is_readiness_upgrade(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if not old:
        return False
    old_suggested = old.get("suggested")
    new_suggested = new.get("suggested")
    if new_suggested and new_suggested != old_suggested:
        return True
    return any(
        partner.get("state") == "ready"
        and old.get("partners", {}).get(code, {}).get("state") != "ready"
        for code, partner in new.get("partners", {}).items()
    )


def _required_value_missing(value: Any) -> bool:
    return value is None or value == ""


def _extraction_value_missing(field: str, payload: dict[str, Any]) -> bool:
    if field not in payload:
        return True
    value = payload.get(field)
    if field == "conditions":
        return not isinstance(value, list)
    if field == "approved_amount":
        amount = _decimal(value)
        return amount is None or amount <= 0
    return value in (None, "")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value).replace(",", "").replace("$", ""))
    except (InvalidOperation, ValueError):
        return None


def _round_dollars(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _money_text(value: Any) -> str:
    amount = _decimal(value)
    return f"${amount:,.2f}" if amount is not None else "—"


def _date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _date_string(value: Any) -> str | None:
    parsed = _date(value)
    return parsed.isoformat() if parsed else None


def _lot_address(lot: Lot) -> str:
    return lot.civic_address or lot.legal_description_normalized or "Unknown address"


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value.value) if hasattr(value, "value") else str(value)


def _safe_filename(value: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "-", value).strip()[:240] or "approval.pdf"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "lot"
