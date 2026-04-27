from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import AuditLog
from app.models.core import Contact
from app.models.core import ContactType
from app.models.core import Development
from app.models.core import Lot
from app.models.core import LotStatus
from app.models.core import Reminder
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion
from app.models.documents import Review
from app.models.land import Agreement
from app.models.land import DepositSchedule
from app.models.land import LotTerms
from app.models.land import SecurityDeposit
from app.models.land import TriggerType


@dataclass(slots=True)
class PromotionResult:
    review_id: UUID
    document_id: UUID
    lots_created: int
    lots_matched: int
    agreement_id: UUID
    promoted_at: datetime


class PromotionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._document: Document | None = None
        self._review: Review | None = None
        self._org_id: UUID | None = None
        self._reviewed_by: UUID | None = None
        self._agreement_date: date | None = None
        self._lots_created = 0
        self._lots_matched = 0

    async def promote(self, review_id: UUID) -> PromotionResult:
        row = await self.db.execute(
            select(Review, Document)
            .join(Extraction, Review.extraction_id == Extraction.id)
            .join(Ingestion, Extraction.ingestion_id == Ingestion.id)
            .join(Document, Ingestion.document_id == Document.id)
            .where(Review.id == review_id)
        )
        review_row = row.first()
        if review_row is None:
            raise ValueError(f"Review not found: {review_id}")

        review, document = review_row
        self._document = document
        self._review = review
        self._org_id = document.org_id
        self._reviewed_by = review.reviewed_by
        self._lots_created = 0
        self._lots_matched = 0

        try:
            payload = review.reviewed_payload
            if document.doc_type.value == "land_otp":
                agreement_id = await self._promote_land_otp(
                    payload=payload,
                    document_id=document.id,
                    review_id=review.id,
                )
            else:
                raise ValueError(f"Unsupported document type for promotion: {document.doc_type.value}")

            promoted_at = datetime.now(timezone.utc)
            review.promoted_at = promoted_at
            document.status = DocumentStatus.APPROVED

            await self._write_audit_log(
                schema_name="documents",
                table_name="reviews",
                record_id=review.id,
                action="PROMOTE",
                new_data={"decision": review.decision, "promoted_at": promoted_at.isoformat()},
            )
            await self._write_audit_log(
                schema_name="documents",
                table_name="documents",
                record_id=document.id,
                action="UPDATE",
                new_data={"status": DocumentStatus.APPROVED.value},
            )

            await self.db.commit()

            return PromotionResult(
                review_id=review.id,
                document_id=document.id,
                lots_created=self._lots_created,
                lots_matched=self._lots_matched,
                agreement_id=agreement_id,
                promoted_at=promoted_at,
            )
        except Exception:
            await self.db.rollback()
            raise

    async def _promote_land_otp(
        self,
        payload: dict[str, Any],
        document_id: UUID,
        review_id: UUID,
    ) -> UUID:
        agreement_payload = payload.get("agreement", {})
        security_deposit_payload = payload.get("security_deposit", {})
        lots_payload = payload.get("lots", [])
        notable_clauses = payload.get("notable_clauses", [])

        vendor_name = self._as_text(agreement_payload.get("vendor_name"))
        vendor_address = self._as_text(agreement_payload.get("vendor_address"))
        development_name = self._as_text(agreement_payload.get("development_name"))
        municipality = self._as_text(agreement_payload.get("municipality"))

        developer_contact_id = await self._upsert_contact(
            name=vendor_name,
            company_name=vendor_name,
            address=vendor_address,
            contact_type=ContactType.VENDOR.value,
        )
        development_id = await self._upsert_development(
            name=development_name,
            municipality=municipality,
            developer_contact_id=developer_contact_id,
        )
        agreement_id = await self._insert_agreement(
            agreement=agreement_payload,
            notable_clauses=notable_clauses,
            development_id=development_id,
            developer_contact_id=developer_contact_id,
            document_id=document_id,
            review_id=review_id,
        )
        await self._insert_security_deposit(
            security_deposit=security_deposit_payload,
            agreement_id=agreement_id,
            lot_count=len(lots_payload),
        )

        for lot_payload in lots_payload:
            lot_id = await self._upsert_lot(lot=lot_payload, development_id=development_id)
            lot_terms_id = await self._insert_lot_terms(
                lot=lot_payload,
                lot_id=lot_id,
                agreement_id=agreement_id,
            )
            deposit_rows = await self._insert_deposit_schedule(
                lot=lot_payload,
                lot_terms_id=lot_terms_id,
                lot_id=lot_id,
                agreement_id=agreement_id,
            )
            balance_due_date = self._calculate_balance_due_date(
                self._coerce_date(lot_payload.get("deposit_2_due_date"))
            )
            await self._create_deposit_reminders(
                lot_id=lot_id,
                deposit_rows=deposit_rows,
                balance_due_date=balance_due_date,
            )

        return agreement_id

    async def _upsert_contact(
        self,
        name: str,
        company_name: str,
        address: str,
        contact_type: str,
    ) -> UUID:
        normalized_name = self._normalize_text(name)
        if not normalized_name:
            raise ValueError("Contact name is required for promotion")

        existing = await self.db.scalar(
            select(Contact).where(func.lower(func.trim(Contact.full_name)) == normalized_name)
        )
        if existing is not None:
            await self._write_audit_log(
                schema_name="core",
                table_name="contacts",
                record_id=existing.id,
                action="MATCHED_EXISTING",
                new_data={"full_name": existing.full_name},
            )
            return existing.id

        if self._org_id is None:
            raise ValueError("Organization context is not available for contact upsert")

        contact = Contact(
            org_id=self._org_id,
            contact_type=ContactType(contact_type),
            full_name=name,
            company_name=company_name or None,
            address=address or None,
        )
        self.db.add(contact)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="core",
            table_name="contacts",
            record_id=contact.id,
            action="INSERT",
            new_data={"full_name": contact.full_name, "contact_type": contact.contact_type.value},
        )
        return contact.id

    async def _upsert_development(
        self,
        name: str,
        municipality: str,
        developer_contact_id: UUID,
    ) -> UUID:
        normalized_name = self._normalize_text(name)
        if not normalized_name:
            raise ValueError("Development name is required for promotion")

        existing = await self.db.scalar(
            select(Development).where(func.lower(func.trim(Development.name)) == normalized_name)
        )
        if existing is not None:
            await self._write_audit_log(
                schema_name="core",
                table_name="developments",
                record_id=existing.id,
                action="MATCHED_EXISTING",
                new_data={"name": existing.name},
            )
            return existing.id

        if self._org_id is None:
            raise ValueError("Organization context is not available for development upsert")

        development = Development(
            org_id=self._org_id,
            developer_contact_id=developer_contact_id,
            name=name,
            municipality=municipality or None,
        )
        self.db.add(development)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="core",
            table_name="developments",
            record_id=development.id,
            action="INSERT",
            new_data={"name": development.name},
        )
        return development.id

    async def _upsert_lot(self, lot: dict[str, Any], development_id: UUID) -> UUID:
        legal_description_normalized = self._build_legal_description(lot)

        existing = await self.db.scalar(
            select(Lot).where(Lot.legal_description_normalized == legal_description_normalized)
        )
        if existing is not None:
            self._lots_matched += 1
            await self._write_audit_log(
                schema_name="core",
                table_name="lots",
                record_id=existing.id,
                action="MATCHED_EXISTING",
                new_data={"legal_description_normalized": existing.legal_description_normalized},
            )
            return existing.id

        lot_record = Lot(
            development_id=development_id,
            legal_description_raw=legal_description_normalized,
            legal_description_normalized=legal_description_normalized,
            civic_address=self._as_text(lot.get("civic_address")) or None,
            street_number=self._as_text(lot.get("street_number")) or None,
            street_name=self._as_text(lot.get("street_name")) or None,
            lot_number=self._as_text(lot.get("lot_number")) or None,
            block=self._as_text(lot.get("block")) or None,
            plan=self._as_text(lot.get("plan")) or None,
            status=LotStatus.LAND_CONTRACTED,
        )
        self.db.add(lot_record)
        await self.db.flush()
        self._lots_created += 1
        await self._write_audit_log(
            schema_name="core",
            table_name="lots",
            record_id=lot_record.id,
            action="INSERT",
            new_data={"legal_description_normalized": lot_record.legal_description_normalized},
        )
        return lot_record.id

    async def _insert_agreement(
        self,
        agreement: dict[str, Any],
        notable_clauses: list[Any],
        development_id: UUID,
        developer_contact_id: UUID,
        document_id: UUID,
        review_id: UUID,
    ) -> UUID:
        agreement_date = self._coerce_date(agreement.get("agreement_date"))
        if agreement_date is None:
            raise ValueError("agreement.agreement_date is required for promotion")

        self._agreement_date = agreement_date
        metadata = {
            "vendor_address": agreement.get("vendor_address"),
            "vendor_attention": agreement.get("vendor_attention"),
            "purchaser_name": agreement.get("purchaser_name"),
            "lot_draw_label": agreement.get("lot_draw_label"),
            "gst_registration": agreement.get("gst_registration"),
        }
        agreement_record = Agreement(
            document_id=document_id,
            review_id=review_id,
            developer_contact_id=developer_contact_id,
            development_id=development_id,
            agreement_date=agreement_date,
            interest_rate=self._coerce_decimal(agreement.get("interest_rate"), scale=4),
            interest_type=self._as_text(agreement.get("interest_type")) or None,
            interest_terms=self._as_text(agreement.get("interest_terms_text")) or None,
            interest_free_from=self._coerce_date(agreement.get("interest_free_from")),
            balance_due_rule=self._as_text(agreement.get("balance_due_rule")) or None,
            total_purchase_price=self._require_decimal(
                agreement.get("total_purchase_price"),
                field_name="agreement.total_purchase_price",
            ),
            municipality=self._as_text(agreement.get("municipality")) or None,
            notable_clauses=notable_clauses or [],
            metadata_=metadata,
        )
        self.db.add(agreement_record)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="land",
            table_name="agreements",
            record_id=agreement_record.id,
            action="INSERT",
            new_data={"document_id": str(document_id), "review_id": str(review_id)},
        )
        return agreement_record.id

    async def _insert_security_deposit(
        self,
        security_deposit: dict[str, Any],
        agreement_id: UUID,
        lot_count: int,
    ) -> UUID:
        rate_per_lot = self._require_decimal(
            security_deposit.get("rate_per_lot"),
            field_name="security_deposit.rate_per_lot",
        )
        maximum_amount = self._require_decimal(
            security_deposit.get("maximum_amount"),
            field_name="security_deposit.maximum_amount",
        )
        calculated_amount = min(rate_per_lot * Decimal(lot_count), maximum_amount)
        deposit = SecurityDeposit(
            agreement_id=agreement_id,
            rate_per_lot=rate_per_lot,
            maximum_amount=maximum_amount,
            calculated_amount=calculated_amount,
            due_trigger=self._as_text(security_deposit.get("due_trigger")) or "on_signing",
        )
        self.db.add(deposit)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="land",
            table_name="security_deposit",
            record_id=deposit.id,
            action="INSERT",
            new_data={"agreement_id": str(agreement_id)},
        )
        return deposit.id

    async def _insert_lot_terms(
        self,
        lot: dict[str, Any],
        lot_id: UUID,
        agreement_id: UUID,
    ) -> UUID:
        deposit_2_due_date = self._coerce_date(lot.get("deposit_2_due_date"))
        balance_due_date = self._calculate_balance_due_date(deposit_2_due_date)

        lot_terms = LotTerms(
            lot_id=lot_id,
            agreement_id=agreement_id,
            purchase_price=self._require_decimal(
                lot.get("purchase_price"),
                field_name="lots.purchase_price",
            ),
            frontage_metres=self._coerce_decimal(lot.get("frontage_metres"), scale=2),
            frontage_feet=self._coerce_decimal(lot.get("frontage_feet"), scale=2),
            lot_notes=self._as_text(lot.get("lot_notes")) or None,
            balance_due_date=balance_due_date,
        )
        self.db.add(lot_terms)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="land",
            table_name="lot_terms",
            record_id=lot_terms.id,
            action="INSERT",
            new_data={"lot_id": str(lot_id), "agreement_id": str(agreement_id)},
        )
        return lot_terms.id

    async def _insert_deposit_schedule(
        self,
        lot: dict[str, Any],
        lot_terms_id: UUID,
        lot_id: UUID,
        agreement_id: UUID,
    ) -> list[DepositSchedule]:
        del agreement_id
        if self._agreement_date is None:
            raise ValueError("Agreement date is not available for deposit schedule insertion")

        deposit_rows: list[DepositSchedule] = []

        deposit_1 = DepositSchedule(
            lot_terms_id=lot_terms_id,
            lot_id=lot_id,
            deposit_number=1,
            amount=self._require_decimal(lot.get("deposit_1_amount"), field_name="lots.deposit_1_amount"),
            due_date=self._agreement_date,
            trigger_type=TriggerType.ON_SIGNING,
            trigger_description="on_signing",
        )
        deposit_rows.append(deposit_1)

        deposit_2_due_date = self._coerce_date(lot.get("deposit_2_due_date"))
        deposit_2 = DepositSchedule(
            lot_terms_id=lot_terms_id,
            lot_id=lot_id,
            deposit_number=2,
            amount=self._require_decimal(lot.get("deposit_2_amount"), field_name="lots.deposit_2_amount"),
            due_date=deposit_2_due_date,
            trigger_type=TriggerType.FIXED_DATE,
            trigger_description="fixed_date",
        )
        deposit_rows.append(deposit_2)

        for deposit_row in deposit_rows:
            self.db.add(deposit_row)
            await self.db.flush()
            await self._write_audit_log(
                schema_name="land",
                table_name="deposit_schedule",
                record_id=deposit_row.id,
                action="INSERT",
                new_data={"lot_id": str(lot_id), "deposit_number": deposit_row.deposit_number},
            )

        return deposit_rows

    async def _create_deposit_reminders(
        self,
        lot_id: UUID,
        deposit_rows: list[DepositSchedule],
        balance_due_date: date | None = None,
    ) -> None:
        for deposit_row in deposit_rows:
            if deposit_row.deposit_number == 2 and deposit_row.due_date is not None:
                reminder = Reminder(
                    lot_id=lot_id,
                    entity_table="land.deposit_schedule",
                    entity_id=deposit_row.id,
                    reminder_type="deposit_due",
                    due_at=datetime.combine(
                        deposit_row.due_date - timedelta(days=14),
                        datetime.min.time(),
                    ).replace(tzinfo=timezone.utc),
                )
                self.db.add(reminder)
                await self.db.flush()
                await self._write_audit_log(
                    schema_name="core",
                    table_name="reminders",
                    record_id=reminder.id,
                    action="INSERT",
                    new_data={"entity_table": reminder.entity_table, "entity_id": str(reminder.entity_id)},
                )

        if balance_due_date is not None:
            reminder = Reminder(
                lot_id=lot_id,
                entity_table="land.lot_terms",
                entity_id=deposit_rows[0].lot_terms_id,
                reminder_type="balance_due",
                due_at=datetime.combine(
                    balance_due_date - timedelta(days=30),
                    datetime.min.time(),
                ).replace(tzinfo=timezone.utc),
            )
            self.db.add(reminder)
            await self.db.flush()
            await self._write_audit_log(
                schema_name="core",
                table_name="reminders",
                record_id=reminder.id,
                action="INSERT",
                new_data={"entity_table": reminder.entity_table, "entity_id": str(reminder.entity_id)},
            )

    async def _write_audit_log(
        self,
        schema_name: str,
        table_name: str,
        record_id: UUID,
        action: str,
        old_data: dict[str, Any] | None = None,
        new_data: dict[str, Any] | None = None,
    ) -> None:
        audit_log = AuditLog(
            user_id=self._reviewed_by,
            schema_name=schema_name,
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_data=old_data,
            new_data=new_data,
        )
        self.db.add(audit_log)
        await self.db.flush()

    def _build_legal_description(self, lot: dict[str, Any]) -> str:
        block = self._as_text(lot.get("block"))
        lot_number = self._as_text(lot.get("lot_number"))
        plan = self._as_text(lot.get("plan"))
        if not block or not lot_number or not plan:
            raise ValueError("Lot block, lot_number, and plan are required for promotion")
        return f"BLK {block} LT {lot_number} PLAN {plan}"

    def _calculate_balance_due_date(self, deposit_2_due_date: date | None) -> date | None:
        if deposit_2_due_date is None:
            return None
        return self._add_months(deposit_2_due_date, 12)

    def _add_months(self, value: date, months: int) -> date:
        month_index = value.month - 1 + months
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    def _normalize_text(self, value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    def _as_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _require_decimal(self, value: object, field_name: str) -> Decimal:
        decimal_value = self._coerce_decimal(value, scale=2)
        if decimal_value is None:
            raise ValueError(f"{field_name} is required for promotion")
        return decimal_value

    def _coerce_decimal(self, value: object, scale: int) -> Decimal | None:
        if value in (None, ""):
            return None
        if isinstance(value, Decimal):
            decimal_value = value
        else:
            text_value = str(value).strip().replace(",", "").replace("$", "")
            if text_value.startswith("(") and text_value.endswith(")"):
                text_value = f"-{text_value[1:-1]}"
            try:
                decimal_value = Decimal(text_value)
            except (InvalidOperation, ValueError):
                return None
        quantizer = Decimal("1").scaleb(-scale)
        return decimal_value.quantize(quantizer)

    def _coerce_date(self, value: object) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()

        text_value = str(value).strip()
        for parser in (
            lambda x: date.fromisoformat(x),
            lambda x: datetime.fromisoformat(x).date(),
        ):
            try:
                return parser(text_value)
            except ValueError:
                continue
        return None
