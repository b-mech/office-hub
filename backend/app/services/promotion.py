from __future__ import annotations

import calendar
import re
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.addresses import normalize_address
from app.models.core import AuditLog
from app.models.core import Contact
from app.models.core import ContactType
from app.models.core import Development
from app.models.core import DevelopmentType
from app.models.core import Lot
from app.models.core import LotStatus
from app.models.core import LotTriggerType
from app.models.core import Reminder
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion
from app.models.documents import Review
from app.models.financing import Property
from app.models.land import Agreement
from app.models.land import DepositSchedule
from app.models.land import LotTerms
from app.models.land import SecurityDeposit
from app.models.land import TriggerType
from app.models.sales import Party
from app.models.sales import PartyRole
from app.models.sales import SalesAgreement
from app.models.sales import SalesAgreementStatus
from app.models.sales import SalesDepositSchedule
from app.services.developments import DevelopmentService
from app.services.developments import municipality_key


@dataclass(slots=True)
class PromotionResult:
    review_id: UUID
    document_id: UUID
    lots_created: int
    lots_matched: int
    project_ids: list[UUID]
    agreement_id: UUID | None
    promoted_at: datetime | None
    dry_run: bool = False
    preview: dict[str, Any] | None = None


class PromotionAlreadyExistsError(ValueError):
    def __init__(self, document_id: UUID, agreement_id: UUID | None) -> None:
        self.document_id = document_id
        self.agreement_id = agreement_id
        existing = str(agreement_id) if agreement_id is not None else "unknown"
        super().__init__(
            f"Document {document_id} has already been promoted as agreement {existing}"
        )


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
        self._project_ids: list[UUID] = []
        self._dry_run = False
        self._preview: dict[str, Any] = {}

    async def promote(self, review_id: UUID, *, dry_run: bool = False) -> PromotionResult:
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
        persisted_review_id = review.id
        persisted_document_id = document.id
        self._document = document
        self._review = review
        self._org_id = document.org_id
        self._reviewed_by = review.reviewed_by
        self._lots_created = 0
        self._lots_matched = 0
        self._project_ids = []
        self._dry_run = dry_run
        self._preview = self._new_preview(document.doc_type.value, review.reviewed_payload)
        if document.doc_type.value == "land_otp":
            self._collect_land_input_warnings(review.reviewed_payload)

        try:
            payload = review.reviewed_payload
            if document.doc_type.value == "land_otp":
                await self._ensure_not_already_promoted(document.id, Agreement)
                agreement_id = await self._promote_land_otp(
                    payload=payload,
                    document_id=document.id,
                    review_id=review.id,
                )
            elif document.doc_type.value == "sale_otp":
                await self._ensure_not_already_promoted(document.id, SalesAgreement)
                agreement_id = await self._promote_sale_otp(
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

            if dry_run:
                await self.db.rollback()
            else:
                await self.db.commit()

            return PromotionResult(
                review_id=persisted_review_id,
                document_id=persisted_document_id,
                lots_created=self._lots_created,
                lots_matched=self._lots_matched,
                project_ids=self._project_ids,
                agreement_id=agreement_id,
                promoted_at=promoted_at,
                dry_run=dry_run,
                preview=self._preview if dry_run else None,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            constraint_name = getattr(getattr(exc, "orig", None), "diag", None)
            constraint_name = getattr(constraint_name, "constraint_name", None)
            if constraint_name in {
                "uq_land_agreements_document_id",
                "uq_sales_agreements_document_id",
            }:
                model = (
                    Agreement
                    if document.doc_type.value == "land_otp"
                    else SalesAgreement
                )
                existing_id = await self.db.scalar(
                    select(model.id).where(model.document_id == document.id).limit(1)
                )
                raise PromotionAlreadyExistsError(document.id, existing_id) from exc
            raise
        except PromotionAlreadyExistsError:
            await self.db.rollback()
            raise
        except ValueError as exc:
            await self.db.rollback()
            if dry_run:
                self._preview["execution_error"] = str(exc)
                self._add_warning("promotion_error", str(exc))
                return PromotionResult(
                    review_id=persisted_review_id,
                    document_id=persisted_document_id,
                    lots_created=self._lots_created,
                    lots_matched=self._lots_matched,
                    project_ids=self._project_ids,
                    agreement_id=None,
                    promoted_at=None,
                    dry_run=True,
                    preview=self._preview,
                )
            raise
        except Exception:
            await self.db.rollback()
            raise

    def _new_preview(self, doc_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        agreement = payload.get("agreement", {})
        if not isinstance(agreement, dict):
            agreement = {}
        preview: dict[str, Any] = {
            "document_type": doc_type,
            "agreement": dict(agreement),
            "contacts": [],
            "developments": [],
            "lots": [],
            "linkable_properties": [],
            "warnings": [],
        }
        if doc_type == "land_otp":
            security = payload.get("security_deposit", {})
            lots = payload.get("lots", [])
            lot_count = len(lots) if isinstance(lots, list) else 0
            rate = self._coerce_decimal(
                security.get("rate_per_lot") if isinstance(security, dict) else None,
                scale=2,
            )
            maximum = self._coerce_decimal(
                security.get("maximum_amount") if isinstance(security, dict) else None,
                scale=2,
            )
            preview["agreement"] = {
                "vendor": agreement.get("vendor_name"),
                "development": agreement.get("development_name"),
                "municipality": agreement.get("municipality"),
                "agreement_date": agreement.get("agreement_date"),
                "total_purchase_price": agreement.get("total_purchase_price"),
                "security_deposit": security if isinstance(security, dict) else {},
                "calculated_security_deposit": (
                    min(rate * Decimal(lot_count), maximum)
                    if rate is not None and maximum is not None
                    else None
                ),
            }
        elif doc_type == "sale_otp":
            preview["agreement"] = {
                **agreement,
                "deposit_structure": payload.get("payment_schedule", []),
            }
        return preview

    def _collect_land_input_warnings(self, payload: dict[str, Any]) -> None:
        agreement = payload.get("agreement", {})
        if not isinstance(agreement, dict):
            agreement = {}
        for field in (
            "vendor_name",
            "development_name",
            "municipality",
            "agreement_date",
            "total_purchase_price",
        ):
            if agreement.get(field) in (None, ""):
                self._add_warning("missing_required_field", f"agreement.{field} is missing")
        lots = payload.get("lots", [])
        security = payload.get("security_deposit", {})
        if not isinstance(security, dict):
            security = {}
        for field in ("rate_per_lot", "maximum_amount"):
            if security.get(field) in (None, ""):
                self._add_warning(
                    "missing_required_field",
                    f"security_deposit.{field} is missing",
                )
        if not isinstance(lots, list):
            self._add_warning("missing_required_field", "lots must be a list")
            return
        for index, lot in enumerate(lots):
            if not isinstance(lot, dict):
                self._add_warning("incomplete_legal_description", f"lots[{index}] is not an object")
                continue
            missing = [
                field
                for field in ("block", "lot_number", "plan")
                if lot.get(field) in (None, "")
            ]
            if missing:
                self._add_warning(
                    "incomplete_legal_description",
                    f"lots[{index}] is missing {', '.join(missing)}",
                    lot_index=index,
                )
                self._preview["lots"].append(
                    {
                        "action": "blocked",
                        "legal_description_normalized": None,
                        "civic_address": self._as_text(lot.get("civic_address")) or None,
                        "purchase_price": lot.get("purchase_price"),
                        "deposits": [
                            {"number": 1, "amount": lot.get("deposit_1_amount")},
                            {
                                "number": 2,
                                "amount": lot.get("deposit_2_amount"),
                                "due_date": lot.get("deposit_2_due_date"),
                            },
                        ],
                    }
                )
            for field in ("purchase_price", "deposit_1_amount", "deposit_2_amount"):
                if lot.get(field) in (None, ""):
                    self._add_warning(
                        "missing_required_field",
                        f"lots[{index}].{field} is missing",
                        lot_index=index,
                    )

    def _add_warning(self, code: str, message: str, **details: Any) -> None:
        self._preview.setdefault("warnings", []).append(
            {"code": code, "message": message, **details}
        )

    async def _ensure_not_already_promoted(
        self,
        document_id: UUID,
        agreement_model: type[Agreement] | type[SalesAgreement],
    ) -> None:
        existing_id = await self.db.scalar(
            select(agreement_model.id)
            .where(agreement_model.document_id == document_id)
            .order_by(agreement_model.created_at.asc())
            .limit(1)
        )
        if existing_id is not None:
            raise PromotionAlreadyExistsError(document_id, existing_id)

    async def _promote_land_otp(
        self,
        payload: dict[str, Any],
        document_id: UUID,
        review_id: UUID,
    ) -> UUID:
        agreement_payload = payload.get("agreement", {})
        security_deposit_payload = payload.get("security_deposit", {})
        development_guidelines = payload.get("development_guidelines", {})
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
            development_guidelines=development_guidelines,
            source_document_id=document_id,
            review_id=review_id,
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

    async def _promote_sale_otp(
        self,
        payload: dict[str, Any],
        document_id: UUID,
        review_id: UUID,
    ) -> UUID:
        agreement_payload = payload.get("agreement", {})
        payment_schedule = payload.get("payment_schedule", [])
        conditions = payload.get("conditions", {})
        notable_clauses = payload.get("notable_clauses", [])

        lot_id = await self._match_sale_lot(agreement_payload)
        self._project_ids = [lot_id]
        agreement_id = await self._insert_sales_agreement(
            agreement=agreement_payload,
            conditions=self._build_sales_conditions_payload(payload),
            notable_clauses=notable_clauses,
            lot_id=lot_id,
            document_id=document_id,
            review_id=review_id,
        )
        await self._insert_sales_parties(agreement=agreement_payload, agreement_id=agreement_id)
        await self._insert_sales_deposit_schedule(
            payment_schedule=payment_schedule,
            agreement_id=agreement_id,
        )

        lot = await self.db.get(Lot, lot_id)
        if lot is not None:
            lot.status = LotStatus.SALE_SIGNED
            if lot.trigger_type is None:
                lot.trigger_type = LotTriggerType.OTP
            await self._write_audit_log(
                schema_name="core",
                table_name="lots",
                record_id=lot.id,
                action="UPDATE",
                new_data={
                    "status": LotStatus.SALE_SIGNED.value,
                    "trigger_type": lot.trigger_type.value,
                },
            )

        self._lots_matched = 1
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
            if self._dry_run:
                self._preview["contacts"].append(
                    {
                        "action": "match",
                        "id": str(existing.id),
                        "name": existing.full_name,
                        "type": existing.contact_type.value,
                    }
                )
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
        if self._dry_run:
            self._preview["contacts"].append(
                {
                    "action": "create",
                    "id": str(contact.id),
                    "name": contact.full_name,
                    "type": contact.contact_type.value,
                }
            )
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
        development_guidelines: object | None = None,
        source_document_id: UUID | None = None,
        review_id: UUID | None = None,
    ) -> UUID:
        if not self._normalize_text(name):
            raise ValueError("Development name is required for promotion")
        if not self._normalize_text(municipality):
            raise ValueError("Municipality is required for promotion")
        if self._org_id is None:
            raise ValueError("Organization context is not available for development upsert")

        municipalities_before = list(
            (
                await self.db.scalars(
                    select(Development).where(
                        Development.org_id == self._org_id,
                        Development.development_type == DevelopmentType.MUNICIPALITY,
                    )
                )
            ).all()
        )
        municipality_existed = any(
            municipality_key(item.name) == municipality_key(municipality)
            for item in municipalities_before
        )
        resolution = await DevelopmentService(self.db).resolve_for_promotion(
            org_id=self._org_id,
            development_name=name,
            municipality_name=municipality,
            developer_contact_id=developer_contact_id,
        )
        development = resolution.development
        if self._dry_run:
            parent = (
                await self.db.get(Development, development.parent_id)
                if development.parent_id is not None
                else None
            )
            path = [development.name]
            if parent is not None:
                path.insert(0, parent.name)
                self._preview["developments"].append(
                    {
                        "action": "match" if municipality_existed else "create",
                        "id": str(parent.id),
                        "name": parent.name,
                        "type": parent.development_type.value,
                        "parent_id": None,
                        "path": [parent.name],
                    }
                )
            self._preview["developments"].append(
                {
                    "action": "create" if resolution.created else "match",
                    "id": str(development.id),
                    "name": development.name,
                    "type": development.development_type.value,
                    "parent_id": str(development.parent_id) if development.parent_id else None,
                    "path": path,
                }
            )
        if not resolution.created:
            await self._apply_development_guidelines(
                development=development,
                development_guidelines=development_guidelines,
                source_document_id=source_document_id,
                review_id=review_id,
            )
            await self._write_audit_log(
                schema_name="core",
                table_name="developments",
                record_id=development.id,
                action="MATCHED_EXISTING",
                new_data={"name": development.name, "parent_id": str(development.parent_id)},
            )
            return development.id

        await self._apply_development_guidelines(
            development=development,
            development_guidelines=development_guidelines,
            source_document_id=source_document_id,
            review_id=review_id,
        )
        await self._write_audit_log(
            schema_name="core",
            table_name="developments",
            record_id=development.id,
            action="INSERT",
            new_data={"name": development.name, "parent_id": str(development.parent_id)},
        )
        return development.id

    async def _apply_development_guidelines(
        self,
        development: Development,
        development_guidelines: object | None,
        source_document_id: UUID | None,
        review_id: UUID | None,
    ) -> None:
        metadata = self._build_development_metadata(
            development_guidelines=development_guidelines,
            source_document_id=source_document_id,
            review_id=review_id,
            existing_metadata=development.metadata_,
        )
        if metadata == (development.metadata_ or {}):
            return

        old_data = {"metadata": development.metadata_ or {}}
        development.metadata_ = metadata
        await self.db.flush()
        await self._write_audit_log(
            schema_name="core",
            table_name="developments",
            record_id=development.id,
            action="UPDATE",
            old_data=old_data,
            new_data={"metadata": metadata},
        )

    def _build_development_metadata(
        self,
        development_guidelines: object | None,
        source_document_id: UUID | None,
        review_id: UUID | None,
        existing_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(existing_metadata or {})
        cleaned_guidelines = self._clean_development_guidelines(development_guidelines)
        if not cleaned_guidelines:
            return metadata

        metadata["development_guidelines"] = cleaned_guidelines
        metadata["development_guidelines_source"] = {
            "document_id": str(source_document_id) if source_document_id is not None else None,
            "review_id": str(review_id) if review_id is not None else None,
        }
        return metadata

    def _clean_development_guidelines(self, value: object | None) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        cleaned: dict[str, Any] = {}
        for key, raw_value in value.items():
            if isinstance(raw_value, list):
                items = [self._as_text(item) for item in raw_value]
                non_empty_items = [item for item in items if item]
                if non_empty_items:
                    cleaned[key] = non_empty_items
                continue

            text_value = self._as_text(raw_value)
            if text_value:
                cleaned[key] = text_value

        return cleaned

    async def _upsert_lot(self, lot: dict[str, Any], development_id: UUID) -> UUID:
        legal_description_normalized = self._build_legal_description(lot)
        civic_address = self._as_text(lot.get("civic_address"))

        existing = await self.db.scalar(
            select(Lot).where(Lot.legal_description_normalized == legal_description_normalized)
        )
        if existing is not None:
            if self._dry_run:
                await self._record_land_lot_preview(
                    lot=lot,
                    legal_description=legal_description_normalized,
                    action="reuse",
                    lot_id=existing.id,
                    current_civic_address=existing.civic_address,
                )
                scheduled_key = normalize_address(civic_address).canonical_key
                existing_key = normalize_address(existing.civic_address or "").canonical_key
                if civic_address and scheduled_key != existing_key:
                    self._add_warning(
                        "civic_address_mismatch",
                        "Scheduled civic address does not match the existing lot",
                        legal_description=legal_description_normalized,
                        scheduled_civic_address=civic_address,
                        existing_civic_address=existing.civic_address,
                        existing_lot_id=str(existing.id),
                    )
                if existing.development_id != development_id:
                    self._add_warning(
                        "development_mismatch",
                        "Existing lot belongs to a different development",
                        legal_description=legal_description_normalized,
                        existing_lot_id=str(existing.id),
                        existing_development_id=str(existing.development_id),
                        proposed_development_id=str(development_id),
                    )
            self._lots_matched += 1
            if existing.id not in self._project_ids:
                self._project_ids.append(existing.id)
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
        if self._dry_run:
            await self._record_land_lot_preview(
                lot=lot,
                legal_description=legal_description_normalized,
                action="create",
                lot_id=lot_record.id,
                current_civic_address=None,
            )
        self._lots_created += 1
        self._project_ids.append(lot_record.id)
        await self._write_audit_log(
            schema_name="core",
            table_name="lots",
            record_id=lot_record.id,
            action="INSERT",
            new_data={"legal_description_normalized": lot_record.legal_description_normalized},
        )
        return lot_record.id

    async def _record_land_lot_preview(
        self,
        *,
        lot: dict[str, Any],
        legal_description: str,
        action: str,
        lot_id: UUID,
        current_civic_address: str | None,
    ) -> None:
        civic_address = self._as_text(lot.get("civic_address"))
        entry = {
            "action": action,
            "legal_description_normalized": legal_description,
            "civic_address": civic_address or None,
            "purchase_price": lot.get("purchase_price"),
            "deposits": [
                {"number": 1, "amount": lot.get("deposit_1_amount")},
                {
                    "number": 2,
                    "amount": lot.get("deposit_2_amount"),
                    "due_date": lot.get("deposit_2_due_date"),
                },
            ],
            "existing_lot_id": str(lot_id) if action == "reuse" else None,
            "existing_civic_address": current_civic_address,
        }
        self._preview["lots"].append(entry)
        if not civic_address:
            return
        key = normalize_address(civic_address).canonical_key
        properties = list(
            (
                await self.db.scalars(
                    select(Property).where(Property.canonical_address_key == key)
                )
            ).all()
        )
        for property_record in properties:
            linked_lot = await self.db.scalar(
                select(Lot.id).where(Lot.property_id == property_record.id).limit(1)
            )
            if linked_lot is None:
                candidate = {
                    "property_id": str(property_record.id),
                    "property_address": property_record.address,
                    "lot_id": str(lot_id),
                    "legal_description_normalized": legal_description,
                }
                if candidate not in self._preview["linkable_properties"]:
                    self._preview["linkable_properties"].append(candidate)

    async def _match_sale_lot(self, agreement: dict[str, Any]) -> UUID:
        legal_description = agreement.get("legal_description")
        if isinstance(legal_description, dict):
            try:
                normalized = self._build_legal_description(
                    {
                        "block": legal_description.get("block"),
                        "lot_number": legal_description.get("lot"),
                        "plan": legal_description.get("plan"),
                    }
                )
            except ValueError:
                normalized = ""
            if normalized:
                existing = await self.db.scalar(
                    select(Lot).where(Lot.legal_description_normalized == normalized)
                )
                if existing is not None:
                    if self._dry_run:
                        self._record_sale_lot_preview(existing, "reuse", normalized)
                    await self._write_audit_log(
                        schema_name="core",
                        table_name="lots",
                        record_id=existing.id,
                        action="MATCHED_EXISTING",
                        new_data={"legal_description_normalized": existing.legal_description_normalized},
                    )
                    return existing.id

        civic_address = self._normalize_text(self._as_text(agreement.get("civic_address")))
        if civic_address:
            existing = await self.db.scalar(
                select(Lot).where(func.lower(func.trim(Lot.civic_address)) == civic_address)
            )
            if existing is not None:
                if self._dry_run:
                    self._record_sale_lot_preview(
                        existing,
                        "reuse",
                        existing.legal_description_normalized,
                    )
                await self._write_audit_log(
                    schema_name="core",
                    table_name="lots",
                    record_id=existing.id,
                    action="MATCHED_EXISTING",
                    new_data={"civic_address": existing.civic_address},
                )
                return existing.id

        lot_id = await self._create_sale_lot_from_agreement(agreement)
        if self._dry_run:
            lot = await self.db.get(Lot, lot_id)
            if lot is not None:
                self._record_sale_lot_preview(
                    lot,
                    "create",
                    lot.legal_description_normalized,
                )
        return lot_id

    def _record_sale_lot_preview(
        self,
        lot: Lot,
        action: str,
        legal_description: str | None,
    ) -> None:
        self._preview["lots"].append(
            {
                "action": action,
                "legal_description_normalized": legal_description,
                "civic_address": lot.civic_address,
                "existing_lot_id": str(lot.id) if action == "reuse" else None,
                "existing_civic_address": lot.civic_address if action == "reuse" else None,
            }
        )

    async def _create_sale_lot_from_agreement(self, agreement: dict[str, Any]) -> UUID:
        legal_description = agreement.get("legal_description")
        if not isinstance(legal_description, dict):
            legal_description = {}

        lot_payload = {
            "block": legal_description.get("block"),
            "lot_number": legal_description.get("lot"),
            "plan": legal_description.get("plan"),
            "civic_address": agreement.get("civic_address"),
        }
        legal_description_normalized = self._build_legal_description(lot_payload)
        development_id = await self._upsert_sale_development(agreement)
        street_number, street_name = self._split_civic_address(
            self._as_text(agreement.get("civic_address"))
        )

        lot_record = Lot(
            development_id=development_id,
            legal_description_raw=legal_description_normalized,
            legal_description_normalized=legal_description_normalized,
            civic_address=self._as_text(agreement.get("civic_address")) or None,
            street_number=street_number,
            street_name=street_name,
            lot_number=self._as_text(legal_description.get("lot")) or None,
            block=self._as_text(legal_description.get("block")) or None,
            plan=self._as_text(legal_description.get("plan")) or None,
            status=LotStatus.SALE_SIGNED,
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

    async def _upsert_sale_development(self, agreement: dict[str, Any]) -> UUID:
        civic_address = self._as_text(agreement.get("civic_address"))
        development_name = self._extract_development_name(civic_address)
        if self._org_id is None:
            raise ValueError("Organization context is not available for development upsert")
        resolution = await DevelopmentService(self.db).resolve_municipality(
            org_id=self._org_id,
            name=development_name,
        )
        development = resolution.development
        if not resolution.created:
            await self._write_audit_log(
                schema_name="core",
                table_name="developments",
                record_id=development.id,
                action="MATCHED_EXISTING",
                new_data={"name": development.name},
            )
            return development.id
        await self._write_audit_log(
            schema_name="core",
            table_name="developments",
            record_id=development.id,
            action="INSERT",
            new_data={"name": development.name},
        )
        return development.id

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

    async def _insert_sales_agreement(
        self,
        agreement: dict[str, Any],
        conditions: dict[str, Any],
        notable_clauses: list[Any],
        lot_id: UUID,
        document_id: UUID,
        review_id: UUID,
    ) -> UUID:
        condition_source = conditions.get("conditions", conditions)
        if not isinstance(condition_source, dict):
            condition_source = {}
        condition_dates = [
            self._coerce_date(condition_source.get("financing_condition_date")),
            self._coerce_date(condition_source.get("lawyer_approval_date")),
            self._coerce_date(condition_source.get("design_meeting_date")),
            self._coerce_date(condition_source.get("acceptance_date")),
        ]
        condition_removal_date = max((value for value in condition_dates if value is not None), default=None)
        sales_agreement = SalesAgreement(
            lot_id=lot_id,
            document_id=document_id,
            review_id=review_id,
            sale_price=self._require_decimal(
                agreement.get("purchase_price_total"),
                field_name="agreement.purchase_price_total",
            ),
            agreement_date=self._coerce_date(agreement.get("agreement_date")),
            possession_date=self._coerce_date(agreement.get("estimated_occupancy_date")),
            condition_removal_date=condition_removal_date,
            status=SalesAgreementStatus.RECEIVED,
            conditions=conditions or {},
            notable_clauses=notable_clauses or [],
        )
        self.db.add(sales_agreement)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="sales",
            table_name="agreements",
            record_id=sales_agreement.id,
            action="INSERT",
            new_data={"document_id": str(document_id), "review_id": str(review_id)},
        )
        return sales_agreement.id

    async def _insert_sales_parties(
        self,
        agreement: dict[str, Any],
        agreement_id: UUID,
    ) -> None:
        purchaser_names = agreement.get("purchaser_names")
        if isinstance(purchaser_names, str):
            purchaser_names = [purchaser_names]
        if not isinstance(purchaser_names, list):
            purchaser_names = []

        for index, purchaser_name in enumerate(purchaser_names):
            name = self._as_text(purchaser_name)
            if not name:
                continue
            contact_id = await self._upsert_contact(
                name=name,
                company_name="",
                address=self._as_text(agreement.get("purchaser_address")),
                contact_type=ContactType.BUYER.value,
            )
            await self._insert_party(
                agreement_id=agreement_id,
                contact_id=contact_id,
                party_role=PartyRole.BUYER if index == 0 else PartyRole.CO_BUYER,
                is_primary=index == 0,
            )

        realtor_fields = [
            ("buyers_realtor_name", "buyers_brokerage", PartyRole.BUYERS_REALTOR),
            ("sellers_realtor_name", "sellers_brokerage", PartyRole.SELLERS_REALTOR),
        ]
        for name_field, brokerage_field, role in realtor_fields:
            name = self._as_text(agreement.get(name_field))
            if not name:
                continue
            contact_id = await self._upsert_contact(
                name=name,
                company_name=self._as_text(agreement.get(brokerage_field)),
                address="",
                contact_type=ContactType.REALTOR.value,
            )
            await self._insert_party(
                agreement_id=agreement_id,
                contact_id=contact_id,
                party_role=role,
                is_primary=False,
            )

    async def _insert_party(
        self,
        agreement_id: UUID,
        contact_id: UUID,
        party_role: PartyRole,
        is_primary: bool,
    ) -> None:
        party = Party(
            agreement_id=agreement_id,
            contact_id=contact_id,
            party_role=party_role,
            is_primary=is_primary,
        )
        self.db.add(party)
        await self.db.flush()
        await self._write_audit_log(
            schema_name="sales",
            table_name="parties",
            record_id=party.id,
            action="INSERT",
            new_data={"agreement_id": str(agreement_id), "party_role": party_role.value},
        )

    async def _insert_sales_deposit_schedule(
        self,
        payment_schedule: object,
        agreement_id: UUID,
    ) -> None:
        if not isinstance(payment_schedule, list):
            return

        deposit_number = 1
        for payment in payment_schedule:
            if not isinstance(payment, dict):
                continue
            amount = self._coerce_decimal(payment.get("amount"), scale=2)
            if amount is None:
                continue
            stage = self._normalize_text(self._as_text(payment.get("stage")))
            trigger = self._normalize_text(self._as_text(payment.get("trigger")))
            if "deposit" not in stage and "deposit" not in trigger:
                continue
            row = SalesDepositSchedule(
                agreement_id=agreement_id,
                deposit_number=deposit_number,
                amount=amount,
                due_date=self._coerce_date(payment.get("due_date")),
                held_by=self._coerce_held_by(payment.get("payable_to")),
            )
            self.db.add(row)
            await self.db.flush()
            await self._write_audit_log(
                schema_name="sales",
                table_name="deposit_schedule",
                record_id=row.id,
                action="INSERT",
                new_data={"agreement_id": str(agreement_id), "deposit_number": deposit_number},
            )
            deposit_number += 1

    def _build_sales_conditions_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "conditions": payload.get("conditions", {}),
            "construction_summary": payload.get("construction_summary", {}),
            "standard_specs": payload.get("standard_specs", {}),
            "upgrades": payload.get("upgrades", []),
            "landscaping": payload.get("landscaping", {}),
            "financial": payload.get("financial", {}),
            "payment_schedule": payload.get("payment_schedule", []),
            "agreement_snapshot": payload.get("agreement", {}),
        }

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

    def _extract_development_name(self, civic_address: str) -> str:
        parts = [part.strip() for part in civic_address.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[1]
        return "Unassigned Sale Lots"

    def _split_civic_address(self, civic_address: str) -> tuple[str | None, str | None]:
        first_part = civic_address.split(",", 1)[0].strip()
        if not first_part:
            return None, None
        match = re.match(r"^(\d+[A-Za-z]?)\s+(.+)$", first_part)
        if match is None:
            return None, first_part
        return match.group(1), match.group(2).strip()

    def _coerce_held_by(self, value: object) -> str | None:
        text_value = self._normalize_text(self._as_text(value))
        if not text_value:
            return None
        if "lawyer" in text_value or "solicitor" in text_value:
            return "lawyer"
        if "realtor" in text_value or "broker" in text_value or "realty" in text_value:
            return "realtor"
        if "builder" in text_value or "connection" in text_value:
            return "builder"
        return None
