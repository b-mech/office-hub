from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from datetime import date
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy import bindparam
from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.addresses import normalize_address as normalize_canonical_address
from app.models.core import Org
from app.models.documents import DocType
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion
from app.schemas.financing import DashboardSummary
from app.schemas.financing import FacilityCreate
from app.schemas.financing import FacilityDocumentOut
from app.schemas.financing import FacilityOut
from app.schemas.financing import FacilityStatementSnapshotOut
from app.schemas.financing import FacilityUpdate
from app.schemas.financing import FinancingDashboardOut
from app.schemas.financing import FinancingPropertyOut
from app.schemas.financing import LenderStatementDetailOut
from app.schemas.financing import LenderStatementOut
from app.schemas.financing import LenderSummary
from app.schemas.financing import ManualStatementSnapshotCreate
from app.schemas.financing import ProFacilityOut
from app.schemas.financing import ProLedgerEventOut
from app.schemas.financing import ProLedgerOut
from app.schemas.financing import ProDrawRequestOut
from app.schemas.financing import ClientDrawScheduleOut
from app.schemas.financing import ClientPrepDrawOut
from app.schemas.financing import ClientDrawRequestOut
from app.schemas.financing import ConstructionMilestoneOut
from app.schemas.financing import ConstructionMilestoneUpdate
from app.financing.engines.pro import ProFacility
from app.financing.engines.pro import ProTransaction
from app.financing.engines.pro import balance_on
from app.financing.engines.pro import compute_ledger
from app.financing.engines.pro import money
from app.financing.parsers.pro_statement import ParsedProFacilityStatement
from app.financing.parsers.pro_statement import parse_statement_text
from app.services.ocr.extractor import PDFExtractor
from app.services.financing_calculator import calculate_draw
from app.services.document_extractor import extract_client_otp_document
from app.services.extraction.service import get_extraction_service
from app.services.minio_financing import get_financing_document
from app.services.construction_stage_history import record_stage_change


LENDER_TYPES = ("SCU", "PRO", "STRIDE", "RSU", "CLIENT", "OTHER")
CLIENT_STAGE_ORDER = ("FOUNDATION", "LOCKUP", "DRYWALL", "CABINETRY", "COMPLETED")
ACTIVE_CLIENT_REQUEST_STATUSES = ("prepared", "sent_to_lawyer", "funded")


def normalize_address(address: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", address.upper()).strip()
    return re.sub(r"\s+", " ", cleaned)


def normalize_lender_type(value: str | None) -> str:
    raw = (value or "").upper()
    if "SCU" in raw:
        return "SCU"
    if "PROAUTO" in raw or "PRO AUTO" in raw or re.search(r"\bPRO\b", raw):
        return "PRO"
    if "STRIDE" in raw:
        return "STRIDE"
    if "RSU" in raw:
        return "RSU"
    if "CLIENT" in raw:
        return "CLIENT"
    return "OTHER"


async def get_or_create_property(db: AsyncSession, address: str) -> tuple[UUID, bool]:
    normalized = normalize_address(address)
    canonical = normalize_canonical_address(address)
    result = await db.execute(
        text(
            """
            SELECT id
            FROM core.properties
            WHERE address_normalized = :normalized
               OR canonical_address_key = :canonical_address_key
            ORDER BY CASE WHEN canonical_address_key = :canonical_address_key THEN 0 ELSE 1 END
            LIMIT 1
            """
        ),
        {"normalized": normalized, "canonical_address_key": canonical.canonical_key},
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False

    created = await db.execute(
        text(
            """
            INSERT INTO core.properties (address, address_normalized, canonical_address_key, property_type)
            VALUES (:address, :normalized, :canonical_address_key, :property_type)
            RETURNING id
            """
        ),
        {
            "address": address.strip(),
            "normalized": normalized,
            "canonical_address_key": canonical.canonical_key,
            "property_type": "development" if canonical.canonical_key.startswith("DEV:") else "lot",
        },
    )
    return created.scalar_one(), True


async def upsert_stage_row(db: AsyncSession, row: dict[str, Any]) -> bool:
    property_id, created = await get_or_create_property(db, row["address_raw"])
    await record_stage_change(
        db,
        property_id=property_id,
        incoming_stage=row.get("stage_clean"),
        synced_at=datetime.now(timezone.utc),
    )
    previous_stage = (
        await db.execute(
            text(
                """
                SELECT stage_clean
                FROM documents.construction_stage_sync
                WHERE address_raw = :address_raw
                FOR UPDATE
                """
            ),
            {"address_raw": row["address_raw"]},
        )
    ).scalar_one_or_none()
    await db.execute(
        text(
            """
            INSERT INTO documents.construction_stage_sync (
                property_id, address_raw, banker_raw, lender_type, sold_or_spec,
                stage_clean, client_name, build_start, possession_date, last_synced_at
            )
            VALUES (
                :property_id, :address_raw, :banker_raw, :lender_type, :sold_or_spec,
                :stage_clean, :client_name, :build_start, :possession_date, now()
            )
            ON CONFLICT (address_raw) DO UPDATE SET
                property_id = EXCLUDED.property_id,
                banker_raw = EXCLUDED.banker_raw,
                lender_type = EXCLUDED.lender_type,
                sold_or_spec = EXCLUDED.sold_or_spec,
                stage_clean = EXCLUDED.stage_clean,
                client_name = EXCLUDED.client_name,
                build_start = EXCLUDED.build_start,
                possession_date = EXCLUDED.possession_date,
                last_synced_at = now()
            """
        ),
        {**row, "property_id": property_id},
    )
    next_stage = row.get("stage_clean")
    excluded_stages = {None, "", "NA", "SYNC_CONFLICT"}
    if next_stage not in excluded_stages and next_stage != previous_stage:
        await db.execute(
            text(
                """
                INSERT INTO documents.construction_stage_milestones (
                    property_id, stage, achieved_at, source
                )
                VALUES (:property_id, :stage, now(), 'sheet_sync')
                """
            ),
            {"property_id": property_id, "stage": next_stage},
        )
    return created


async def get_dashboard(db: AsyncSession) -> FinancingDashboardOut:
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    p.id AS property_id,
                    p.address,
                    p.canonical_address_key,
                    css.banker_raw,
                    COALESCE(lf.lender_type, css.lender_type, 'OTHER') AS lender_type,
                    css.sold_or_spec,
                    css.stage_clean,
                    css.client_name,
                    css.build_start,
                    css.possession_date,
                    css.last_synced_at,
                    lf.id AS facility_id,
                    lf.facility_key,
                    lf.property_name,
                    lf.borrower,
                    lf.annual_rate,
                    lf.original_advance_date,
                    lf.original_advance_amount,
                    lf.status,
                    lf.lender_name,
                    lf.total_facility,
                    lf.opening_balance,
                    lf.rate,
                    lf.already_drawn,
                    lf.draw_eligible_override,
                    lf.requested_draw_amount,
                    lf.requested_draw_as_of,
                    lf.commitment_source,
                    lf.commitment_confirmed_at,
                    lf.last_draw_date,
                    lf.last_draw_amount,
                    lf.account_number,
                    lf.account_title,
                    lf.account_type,
                    lf.current_balance,
                    lf.outstanding_balance,
                    lf.account_currency,
                    lf.maturity_date,
                    lf.member_number,
                    lf.next_interest_payment_date,
                    lf.next_payment_date,
                    lf.account_nickname,
                    lf.open_date,
                    lf.original_loan_amount,
                    lf.payment_schedule,
                    lf.term_length_days,
                    lf.notes
                FROM core.properties p
                LEFT JOIN documents.construction_stage_sync css ON css.property_id = p.id
                LEFT JOIN core.lender_facilities lf
                  ON lf.property_id = p.id
                 AND COALESCE(lf.lender, lf.lender_type) <> 'PRO'
                WHERE NOT (
                    COALESCE(css.lender_type, '') = 'PRO'
                    AND (
                        EXISTS (
                            SELECT 1
                            FROM core.lender_facilities pro_lf
                            WHERE COALESCE(pro_lf.lender, pro_lf.lender_type) = 'PRO'
                              AND (
                                  pro_lf.property_id = p.id
                                  OR (
                                      pro_lf.property_id IS NULL
                                      AND pro_lf.canonical_address_key IS NOT NULL
                                      AND pro_lf.canonical_address_key = p.canonical_address_key
                                  )
                              )
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM core.lender_facilities official_pro
                            WHERE official_pro.commitment_source IS NOT NULL
                        )
                    )
                )
                UNION ALL
                SELECT
                    COALESCE(p.id, lf.id) AS property_id,
                    COALESCE(p.address, lf.property_name, lf.facility_key) AS address,
                    COALESCE(p.canonical_address_key, lf.canonical_address_key) AS canonical_address_key,
                    css.banker_raw,
                    COALESCE(lf.lender_type, lf.lender, 'PRO') AS lender_type,
                    css.sold_or_spec,
                    css.stage_clean,
                    css.client_name,
                    css.build_start,
                    css.possession_date,
                    css.last_synced_at,
                    lf.id AS facility_id,
                    lf.facility_key,
                    lf.property_name,
                    lf.borrower,
                    lf.annual_rate,
                    lf.original_advance_date,
                    lf.original_advance_amount,
                    lf.status,
                    lf.lender_name,
                    lf.total_facility,
                    lf.opening_balance,
                    lf.rate,
                    lf.already_drawn,
                    lf.draw_eligible_override,
                    lf.requested_draw_amount,
                    lf.requested_draw_as_of,
                    lf.commitment_source,
                    lf.commitment_confirmed_at,
                    lf.last_draw_date,
                    lf.last_draw_amount,
                    lf.account_number,
                    lf.account_title,
                    lf.account_type,
                    lf.current_balance,
                    lf.outstanding_balance,
                    lf.account_currency,
                    lf.maturity_date,
                    lf.member_number,
                    lf.next_interest_payment_date,
                    lf.next_payment_date,
                    lf.account_nickname,
                    lf.open_date,
                    lf.original_loan_amount,
                    lf.payment_schedule,
                    lf.term_length_days,
                    lf.notes
                FROM core.lender_facilities lf
                LEFT JOIN core.properties p
                  ON p.id = lf.property_id
                  OR (
                      lf.property_id IS NULL
                      AND lf.canonical_address_key IS NOT NULL
                      AND p.canonical_address_key = lf.canonical_address_key
                  )
                LEFT JOIN documents.construction_stage_sync css ON css.property_id = p.id
                WHERE COALESCE(lf.lender, lf.lender_type) = 'PRO'
                  AND COALESCE(lf.status, 'active') <> 'statement_only'
                  AND (
                      COALESCE(css.lender_type, '') = 'PRO'
                      OR lf.commitment_source IS NOT NULL
                  )
                ORDER BY address
                """
            )
        )
    ).mappings().all()

    milestone_history = await _milestone_history_by_property(
        db,
        {row["property_id"] for row in rows if row["property_id"] is not None},
    )
    properties: list[FinancingPropertyOut] = []
    today = date.today()
    for row in rows:
        pro_balance = None
        pro_principal = None
        if (
            row["facility_id"]
            and (row["lender_type"] or "").upper() == "PRO"
            and row["facility_key"]
            and row["original_advance_date"] is not None
            and row["original_advance_amount"] is not None
        ):
            transactions = await _pro_transactions(db, row["facility_id"])
            pro_balance = balance_on(_pro_facility_from_row(row), transactions, today)
            pro_principal = (row["original_advance_amount"] or Decimal("0")) + sum(
                (
                    txn.amount if txn.txn_type == "draw" else -txn.amount
                    for txn in transactions
                    if txn.txn_type in {"draw", "repayment"}
                ),
                Decimal("0"),
            )
        properties.append(
            _property_from_row(
                row,
                pro_balance=pro_balance,
                pro_principal=pro_principal,
                milestone_history=milestone_history.get(row["property_id"], []),
            )
        )
    properties = _dedupe_dashboard_properties(properties)
    properties.sort(key=lambda item: item.draw_eligible or Decimal("0"), reverse=True)
    last_synced = max((row["last_synced_at"] for row in rows if row["last_synced_at"]), default=None)
    dashboard = FinancingDashboardOut(
        last_synced_at=last_synced,
        summary=_summary(properties),
        properties=properties,
    )
    pro_row_total = sum(
        (item.draw_eligible or Decimal("0") for item in properties if item.lender_type == "PRO"),
        Decimal("0"),
    )
    assert dashboard.summary.PRO.total_drawable == pro_row_total
    _assert_no_duplicate_pro_properties(properties)
    return dashboard


async def get_property_detail(db: AsyncSession, property_id: UUID) -> FinancingPropertyOut | None:
    dashboard = await get_dashboard(db)
    return next((item for item in dashboard.properties if item.property_id == property_id), None)


async def list_pro_draw_requests(
    db: AsyncSession,
    property_id: UUID | None = None,
) -> list[ProDrawRequestOut]:
    where = "WHERE request.property_id = :property_id" if property_id else ""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT request.*, property.address AS property_address
                FROM documents.pro_draw_requests request
                JOIN core.properties property ON property.id = request.property_id
                {where}
                ORDER BY request.created_at DESC
                """
            ),
            {"property_id": property_id} if property_id else {},
        )
    ).mappings().all()
    return [ProDrawRequestOut(**row) for row in rows]


async def create_pro_draw_request(
    db: AsyncSession,
    property_id: UUID,
    *,
    amount: Decimal | None,
    notes: str | None,
) -> ProDrawRequestOut:
    property_detail = await get_property_detail(db, property_id)
    if property_detail is None:
        raise ValueError("Property not found")
    if property_detail.lender_type != "PRO":
        raise ValueError("Draw requests from this workflow are only available for PRO")
    request_amount = amount if amount is not None else property_detail.draw_eligible
    if request_amount is None or request_amount <= Decimal("0"):
        raise ValueError("No PRO draw is currently available for this property")

    request_id = uuid4()
    reference = f"OH-PRO-{str(request_id).split('-')[0].upper()}"
    subject = f"{reference} | PRO draw request | {property_detail.address}"
    body = "\n".join(
        [
            "Hi Michaela,",
            "",
            "We would like to request the following:",
            "",
            f"Total requested amount: ${request_amount:,.2f}",
            "",
            f"- {property_detail.address} {property_detail.stage or ''} - ${request_amount:,.2f}",
            "",
            "Much appreciated!",
            "",
            "Thank You,",
            "",
            "Robert Wieler",
            "Connection Homes",
            "",
            f"Office Hub reference: {reference}",
            "",
            "Please keep the Office Hub reference in the subject so funding progress remains linked.",
        ]
    )
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.pro_draw_requests (
                    id, batch_id, property_id, facility_id, amount, stage, status,
                    initial_recipient, intermediary_email, email_subject,
                    email_body, notes
                )
                VALUES (
                    :id, :id, :property_id, :facility_id, :amount, :stage, 'prepared',
                    'nicholas@connectionhomes.ca', 'robert@connectionhomes.ca',
                    :email_subject, :email_body, :notes
                )
                RETURNING *
                """
            ),
            {
                "id": request_id,
                "property_id": property_id,
                "facility_id": property_detail.facility_id,
                "amount": request_amount,
                "stage": property_detail.stage,
                "email_subject": subject,
                "email_body": body,
                "notes": notes,
            },
        )
    ).mappings().one()
    await db.commit()
    return ProDrawRequestOut(**row)


async def create_pro_draw_request_batch(
    db: AsyncSession,
    property_ids: list[UUID],
) -> list[ProDrawRequestOut]:
    selected_ids = set(property_ids)
    dashboard = await get_dashboard(db)
    properties = [
        item
        for item in dashboard.properties
        if item.property_id in selected_ids
        and item.lender_type == "PRO"
        and item.draw_eligible is not None
        and item.draw_eligible > Decimal("0")
    ]
    if len(properties) != len(selected_ids):
        raise ValueError("Every selected property must be PRO with a positive Draw Now amount")

    properties.sort(key=lambda item: item.address)
    batch_id = uuid4()
    reference = f"OH-PRO-{str(batch_id).split('-')[0].upper()}"
    total = sum((item.draw_eligible or Decimal("0") for item in properties), Decimal("0"))
    lines = [
        f"- {item.address} {item.stage or ''} - ${(item.draw_eligible or Decimal('0')):,.2f}"
        for item in properties
    ]
    subject = f"{reference} | PRO draw request | {len(properties)} properties"
    body = "\n".join(
        [
            "Hi Michaela,",
            "",
            "We would like to request the following:",
            "",
            f"Total requested amount: ${total:,.2f}",
            "",
            *lines,
            "",
            "Much appreciated!",
            "",
            "Thank You,",
            "",
            "Robert Wieler",
            "Connection Homes",
            "",
            f"Office Hub reference: {reference}",
            "",
            "Please keep the Office Hub reference in the subject so funding progress remains linked.",
        ]
    )
    created: list[ProDrawRequestOut] = []
    for item in properties:
        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO documents.pro_draw_requests (
                        id, batch_id, property_id, facility_id, amount, stage, status,
                        initial_recipient, intermediary_email, email_subject, email_body
                    )
                    VALUES (
                        :id, :batch_id, :property_id, :facility_id, :amount, :stage,
                        'prepared', 'nicholas@connectionhomes.ca',
                        'robert@connectionhomes.ca', :email_subject, :email_body
                    )
                    RETURNING *
                    """
                ),
                {
                    "id": uuid4(),
                    "batch_id": batch_id,
                    "property_id": item.property_id,
                    "facility_id": item.facility_id,
                    "amount": item.draw_eligible,
                    "stage": item.stage,
                    "email_subject": subject,
                    "email_body": body,
                },
            )
        ).mappings().one()
        created.append(ProDrawRequestOut(**row))
    await db.commit()
    return created


async def update_pro_draw_request_status(
    db: AsyncSession,
    request_id: UUID,
    *,
    status: str,
    notes: str | None,
) -> ProDrawRequestOut | None:
    timestamps = {
        "sent": "sent_at",
        "acknowledged": "acknowledged_at",
        "lawyer_processing": "lawyer_processing_at",
        "funded": "funded_at",
        "closed": "closed_at",
    }
    if status not in {
        "prepared",
        "sent",
        "acknowledged",
        "lawyer_processing",
        "funded",
        "closed",
        "cancelled",
    }:
        raise ValueError("Invalid PRO draw request status")
    timestamp_sql = f", {timestamps[status]} = COALESCE({timestamps[status]}, now())" if status in timestamps else ""
    row = (
        await db.execute(
            text(
                f"""
                UPDATE documents.pro_draw_requests
                SET status = :status,
                    notes = COALESCE(:notes, notes),
                    updated_at = now()
                    {timestamp_sql}
                WHERE id = :request_id
                RETURNING *
                """
            ),
            {"request_id": request_id, "status": status, "notes": notes},
        )
    ).mappings().one_or_none()
    await db.commit()
    return ProDrawRequestOut(**row) if row else None


async def update_pro_draw_batch_status(
    db: AsyncSession,
    batch_id: UUID,
    *,
    status: str,
    notes: str | None,
) -> list[ProDrawRequestOut]:
    timestamps = {
        "sent": "sent_at",
        "acknowledged": "acknowledged_at",
        "lawyer_processing": "lawyer_processing_at",
        "funded": "funded_at",
        "closed": "closed_at",
    }
    if status not in {
        "prepared",
        "sent",
        "acknowledged",
        "lawyer_processing",
        "funded",
        "closed",
        "cancelled",
    }:
        raise ValueError("Invalid PRO draw request status")
    timestamp_sql = f", {timestamps[status]} = COALESCE({timestamps[status]}, now())" if status in timestamps else ""
    rows = (
        await db.execute(
            text(
                f"""
                UPDATE documents.pro_draw_requests
                SET status = :status,
                    notes = COALESCE(:notes, notes),
                    updated_at = now()
                    {timestamp_sql}
                WHERE batch_id = :batch_id
                RETURNING *
                """
            ),
            {"batch_id": batch_id, "status": status, "notes": notes},
        )
    ).mappings().all()
    await db.commit()
    return [ProDrawRequestOut(**row) for row in rows]


async def get_active_client_draw_schedule(db: AsyncSession, property_id: UUID) -> ClientDrawScheduleOut | None:
    row = (
        await db.execute(
            text(
                """
                SELECT *
                FROM documents.client_draw_schedules
                WHERE property_id = :property_id
                  AND superseded_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().one_or_none()
    return ClientDrawScheduleOut(**row) if row else None


async def list_client_draw_requests(db: AsyncSession, property_id: UUID) -> list[ClientDrawRequestOut]:
    rows = (
        await db.execute(
            text(
                """
                SELECT *
                FROM documents.client_draw_requests
                WHERE property_id = :property_id
                ORDER BY prepared_at DESC
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().all()
    return [ClientDrawRequestOut(**row) for row in rows]


async def record_client_otp_schedule(
    db: AsyncSession,
    *,
    property_id: UUID,
    minio_bucket: str,
    minio_key: str,
    original_filename: str,
    content: bytes,
    extracted: dict[str, Any],
) -> ClientDrawScheduleOut:
    property_row = await _property_row(db, property_id)
    if property_row is None:
        raise ValueError("Property not found")

    org_id = await db.scalar(select(Org.id).order_by(Org.created_at.asc()).limit(1))
    if org_id is None:
        raise ValueError("Default org was not found")

    document = Document(
        org_id=org_id,
        doc_type=DocType.SALE_OTP,
        status=DocumentStatus.IN_REVIEW,
        original_filename=original_filename,
        minio_bucket=minio_bucket,
        minio_key=minio_key,
        file_size_bytes=len(content),
        checksum_sha256=None,
        received_from_email="financing:client-otp",
    )
    db.add(document)
    await db.flush()

    now = datetime.now(timezone.utc)
    ingestion = Ingestion(
        document_id=document.id,
        ocr_method="manual",
        ocr_text=None,
        ocr_confidence=None,
        page_count=None,
        started_at=now,
        completed_at=now,
        error_message=None,
    )
    db.add(ingestion)
    await db.flush()

    normalized = await _normalize_client_schedule_payload(db, extracted)
    extraction = Extraction(
        ingestion_id=ingestion.id,
        model_provider="claude",
        model_version="claude-sonnet-4-6",
        prompt_version="client-otp-draw-schedule-v1",
        extracted_payload=_json_safe(normalized),
        field_confidences={},
        low_confidence_fields=[] if normalized["extraction_confidence"] == "high" else ["schedule"],
    )
    db.add(extraction)

    await db.execute(
        text(
            """
            UPDATE documents.client_draw_schedules
            SET superseded_at = now(), updated_at = now()
            WHERE property_id = :property_id
              AND superseded_at IS NULL
            """
        ),
        {"property_id": property_id},
    )

    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.client_draw_schedules (
                    property_id, document_id, minio_object_key, original_filename,
                    purchase_price, client_name, otp_date, schedule, deposits,
                    extraction_confidence, extraction_status, extraction_notes
                )
                VALUES (
                    :property_id, :document_id, :minio_object_key, :original_filename,
                    :purchase_price, :client_name, :otp_date,
                    CAST(:schedule AS jsonb), CAST(:deposits AS jsonb),
                    :extraction_confidence, 'ready_for_review', :extraction_notes
                )
                RETURNING *
                """
            ),
            {
                "property_id": property_id,
                "document_id": document.id,
                "minio_object_key": minio_key,
                "original_filename": original_filename,
                "purchase_price": normalized["purchase_price"],
                "client_name": normalized["client_name"],
                "otp_date": normalized["otp_date"],
                "schedule": _json_dumps(normalized["schedule"]),
                "deposits": _json_dumps(normalized["deposits"]),
                "extraction_confidence": normalized["extraction_confidence"],
                "extraction_notes": normalized["extraction_notes"],
            },
        )
    ).mappings().one()
    await db.commit()
    return ClientDrawScheduleOut(**row)


async def create_client_otp_upload(
    db: AsyncSession,
    *,
    property_id: UUID,
    minio_bucket: str,
    minio_key: str,
    original_filename: str,
    content_length: int,
) -> ClientDrawScheduleOut:
    property_row = await _property_row(db, property_id)
    if property_row is None:
        raise ValueError("Property not found")
    org_id = await db.scalar(select(Org.id).order_by(Org.created_at.asc()).limit(1))
    if org_id is None:
        raise ValueError("Default org was not found")

    document = Document(
        org_id=org_id,
        doc_type=DocType.SALE_OTP,
        status=DocumentStatus.EXTRACTING,
        original_filename=original_filename,
        minio_bucket=minio_bucket,
        minio_key=minio_key,
        file_size_bytes=content_length,
        checksum_sha256=None,
        received_from_email="financing:client-otp",
    )
    db.add(document)
    await db.flush()

    await db.execute(
        text(
            """
            UPDATE documents.client_draw_schedules
            SET superseded_at = now(), updated_at = now()
            WHERE property_id = :property_id
              AND superseded_at IS NULL
            """
        ),
        {"property_id": property_id},
    )
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.client_draw_schedules (
                    property_id, document_id, minio_object_key, original_filename,
                    schedule, deposits, extraction_confidence, extraction_status, extraction_notes
                )
                VALUES (
                    :property_id, :document_id, :minio_object_key, :original_filename,
                    CAST('[]' AS jsonb), CAST('[]' AS jsonb), 'needs_review', 'extracting',
                    'Extraction is running.'
                )
                RETURNING *
                """
            ),
            {
                "property_id": property_id,
                "document_id": document.id,
                "minio_object_key": minio_key,
                "original_filename": original_filename,
            },
        )
    ).mappings().one()
    await db.commit()
    return ClientDrawScheduleOut(**row)


async def extract_client_otp_schedule_background(
    schedule_id: UUID,
    *,
    content: bytes,
    content_type: str,
) -> None:
    async with AsyncSessionLocal() as db:
        schedule = await _client_schedule_row(db, schedule_id)
        if schedule is None:
            return
        document_id = schedule["document_id"]
        now = datetime.now(timezone.utc)
        ingestion = Ingestion(
            document_id=document_id,
            ocr_method="manual",
            ocr_text=None,
            ocr_confidence=None,
            page_count=None,
            started_at=now,
            completed_at=None,
            error_message=None,
        )
        db.add(ingestion)
        await db.flush()
        try:
            extracted = await extract_client_otp_document(content=content, content_type=content_type)
            normalized = await _normalize_client_schedule_payload(db, extracted)
            ingestion.completed_at = datetime.now(timezone.utc)
            extraction = Extraction(
                ingestion_id=ingestion.id,
                model_provider="claude",
                model_version="claude-sonnet-4-6",
                prompt_version="client-otp-draw-schedule-v1",
                extracted_payload=_json_safe(normalized),
                field_confidences={},
                low_confidence_fields=[] if normalized["extraction_confidence"] == "high" else ["schedule"],
            )
            db.add(extraction)
            await _prepare_sale_otp_review_extraction(
                db,
                document_id=document_id,
                content=content,
            )
            await db.execute(
                text(
                    """
                    UPDATE documents.client_draw_schedules
                    SET purchase_price = :purchase_price,
                        client_name = :client_name,
                        otp_date = :otp_date,
                        schedule = CAST(:schedule AS jsonb),
                        deposits = CAST(:deposits AS jsonb),
                        extraction_confidence = :extraction_confidence,
                        extraction_status = 'ready_for_review',
                        extraction_notes = :extraction_notes,
                        updated_at = now()
                    WHERE id = :schedule_id
                    """
                ),
                {
                    "schedule_id": schedule_id,
                    "purchase_price": normalized["purchase_price"],
                    "client_name": normalized["client_name"],
                    "otp_date": normalized["otp_date"],
                    "schedule": _json_dumps(normalized["schedule"]),
                    "deposits": _json_dumps(normalized["deposits"]),
                    "extraction_confidence": normalized["extraction_confidence"],
                    "extraction_notes": normalized["extraction_notes"],
                },
            )
            await db.execute(
                text("UPDATE documents.documents SET status = 'in_review' WHERE id = :document_id"),
                {"document_id": document_id},
            )
        except Exception as exc:
            ingestion.completed_at = datetime.now(timezone.utc)
            ingestion.error_message = str(exc)
            await db.execute(
                text(
                    """
                    UPDATE documents.client_draw_schedules
                    SET extraction_status = 'failed',
                        extraction_confidence = 'needs_review',
                        extraction_notes = :error,
                        updated_at = now()
                    WHERE id = :schedule_id
                    """
                ),
                {"schedule_id": schedule_id, "error": str(exc)},
            )
            await db.execute(
                text("UPDATE documents.documents SET status = 'rejected' WHERE id = :document_id"),
                {"document_id": document_id},
            )
        await db.commit()


async def _prepare_sale_otp_review_extraction(
    db: AsyncSession,
    *,
    document_id: UUID,
    content: bytes,
) -> None:
    existing_id = (
        await db.execute(
            text(
                """
                SELECT extraction.id
                FROM documents.extractions extraction
                JOIN documents.ingestions ingestion
                    ON ingestion.id = extraction.ingestion_id
                WHERE ingestion.document_id = :document_id
                  AND extraction.extracted_payload::jsonb ? 'agreement'
                LIMIT 1
                """
            ),
            {"document_id": document_id},
        )
    ).scalar_one_or_none()
    if existing_id:
        existing = await db.get(Extraction, existing_id)
        if existing is not None:
            await _apply_sale_otp_financing_context(
                db,
                document_id=document_id,
                extraction=existing,
            )
        return

    started_at = datetime.now(timezone.utc)
    ingestion = Ingestion(
        document_id=document_id,
        ocr_method="manual",
        ocr_text=None,
        ocr_confidence=None,
        page_count=None,
        started_at=started_at,
        completed_at=None,
        error_message=None,
    )
    db.add(ingestion)
    await db.flush()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
        temp.write(content)
        temp_path = Path(temp.name)
    try:
        ocr_result = await asyncio.to_thread(PDFExtractor().extract, temp_path)
        extraction_result = await asyncio.to_thread(
            get_extraction_service().extract,
            DocType.SALE_OTP.value,
            ocr_result.raw_text,
        )
        ingestion.ocr_method = (
            ocr_result.method_used
            if ocr_result.method_used in {"pdfplumber", "tesseract"}
            else "manual"
        )
        ingestion.ocr_text = ocr_result.raw_text
        ingestion.ocr_confidence = Decimal(
            str(max(0, min(1, ocr_result.overall_confidence)))
        ).quantize(Decimal("0.001"))
        ingestion.page_count = ocr_result.total_pages
        ingestion.completed_at = datetime.now(timezone.utc)
        extraction = Extraction(
            ingestion_id=ingestion.id,
            model_provider=extraction_result.model_provider,
            model_version=extraction_result.model_version,
            prompt_version=extraction_result.prompt_version,
            extracted_payload=extraction_result.extracted_payload,
            field_confidences=extraction_result.field_confidences,
            low_confidence_fields=extraction_result.low_confidence_fields,
        )
        db.add(extraction)
        await db.flush()
        await _apply_sale_otp_financing_context(
            db,
            document_id=document_id,
            extraction=extraction,
        )
    except Exception as exc:
        ingestion.completed_at = datetime.now(timezone.utc)
        ingestion.error_message = f"Official OTP extraction failed: {exc}"
    finally:
        temp_path.unlink(missing_ok=True)


async def _apply_sale_otp_financing_context(
    db: AsyncSession,
    *,
    document_id: UUID,
    extraction: Extraction,
) -> None:
    context = (
        await db.execute(
            text(
                """
                SELECT
                    property.address,
                    schedule.client_name,
                    schedule.purchase_price,
                    schedule.otp_date
                FROM documents.client_draw_schedules schedule
                JOIN core.properties property ON property.id = schedule.property_id
                WHERE schedule.document_id = :document_id
                ORDER BY schedule.created_at DESC
                LIMIT 1
                """
            ),
            {"document_id": document_id},
        )
    ).mappings().one_or_none()
    if context is None:
        return

    payload = dict(extraction.extracted_payload or {})
    agreement = dict(payload.get("agreement") or {})
    contextual_fields: dict[str, Any] = {
        "civic_address": context["address"],
        "purchaser_names": (
            [context["client_name"]] if context["client_name"] else None
        ),
        "purchase_price_total": context["purchase_price"],
        "agreement_date": context["otp_date"],
    }
    confidences = dict(extraction.field_confidences or {})
    low_confidence = set(extraction.low_confidence_fields or [])
    for field, value in contextual_fields.items():
        if value is None or agreement.get(field):
            continue
        agreement[field] = value
        path = f"agreement.{field}"
        confidences[path] = 1.0
        low_confidence.discard(path)
    payload["agreement"] = _json_safe(agreement)
    extraction.extracted_payload = _json_safe(payload)
    extraction.field_confidences = confidences
    extraction.low_confidence_fields = sorted(low_confidence)


async def prepare_client_otp_official_review(
    db: AsyncSession,
    schedule_id: UUID,
) -> UUID | None:
    schedule = (
        await db.execute(
            text(
                """
                SELECT document_id, minio_object_key
                FROM documents.client_draw_schedules
                WHERE id = :schedule_id
                """
            ),
            {"schedule_id": schedule_id},
        )
    ).mappings().one_or_none()
    if schedule is None:
        return None
    content = get_financing_document(key=schedule["minio_object_key"])
    await _prepare_sale_otp_review_extraction(
        db,
        document_id=schedule["document_id"],
        content=content,
    )
    await db.execute(
        text(
            """
            UPDATE documents.documents
            SET status = 'in_review'
            WHERE id = :document_id
            """
        ),
        {"document_id": schedule["document_id"]},
    )
    await db.commit()
    return schedule["document_id"]


async def review_client_draw_schedule(
    db: AsyncSession,
    schedule_id: UUID,
    payload: dict[str, Any],
    *,
    reviewed_by: UUID | None = None,
) -> ClientDrawScheduleOut | None:
    schedule = await _client_schedule_row(db, schedule_id)
    if schedule is None:
        return None
    normalized = await _normalize_client_schedule_payload(db, payload)
    for item in normalized["schedule"]:
        if item.get("stage_key"):
            await _upsert_stage_label_alias(db, str(item.get("label_raw") or ""), item["stage_key"])
    row = (
        await db.execute(
            text(
                """
                UPDATE documents.client_draw_schedules
                SET purchase_price = :purchase_price,
                    client_name = :client_name,
                    otp_date = :otp_date,
                    schedule = CAST(:schedule AS jsonb),
                    deposits = CAST(:deposits AS jsonb),
                    extraction_confidence = 'high',
                    extraction_status = 'reviewed',
                    extraction_notes = :extraction_notes,
                    reviewed_by = :reviewed_by,
                    reviewed_at = now(),
                    updated_at = now()
                WHERE id = :schedule_id
                RETURNING *
                """
            ),
            {
                "schedule_id": schedule_id,
                "purchase_price": normalized["purchase_price"],
                "client_name": normalized["client_name"],
                "otp_date": normalized["otp_date"],
                "schedule": _json_dumps(normalized["schedule"]),
                "deposits": _json_dumps(normalized["deposits"]),
                "extraction_notes": normalized["extraction_notes"],
                "reviewed_by": reviewed_by,
            },
        )
    ).mappings().one()
    await db.commit()
    return ClientDrawScheduleOut(**row)


async def prep_client_draw(db: AsyncSession, property_id: UUID) -> ClientPrepDrawOut:
    property_row = await _property_stage_row(db, property_id)
    if property_row is None:
        raise ValueError("Property not found")
    schedule = await get_active_client_draw_schedule(db, property_id)
    property_payload = {
        "id": str(property_row["property_id"]),
        "address": property_row["address"],
        "client_name": property_row["client_name"],
        "lender_type": property_row["lender_type"],
    }
    if schedule is None or schedule.reviewed_at is None:
        return ClientPrepDrawOut(status="needs_otp", property=property_payload, schedule=schedule)

    requests = await list_client_draw_requests(db, property_id)
    request_index = _client_request_index(requests)
    stage = (property_row["stage_clean"] or "NA").upper()
    unavailable = stage in {"", "NA", "SYNC_CONFLICT"}
    current_rank = CLIENT_STAGE_ORDER.index(stage) if stage in CLIENT_STAGE_ORDER else None

    schedule_table: list[dict[str, Any]] = []
    requestable_items: list[dict[str, Any]] = []
    already_requested: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []

    for item in sorted(schedule.schedule, key=lambda row: int(row.get("seq") or 0)):
        seq = int(item.get("seq") or 0)
        stage_key = (item.get("stage_key") or "").upper() or None
        amount = _decimal_or_zero(item.get("amount"))
        request = request_index.get(seq)
        status = "upcoming"
        row = {**item, "amount": str(amount), "status": status}
        if request:
            row["status"] = "funded" if request.status == "funded" else "requested"
            row["request_id"] = str(request.id)
            row["request_status"] = request.status
            row["prepared_at"] = request.prepared_at.isoformat()
            already_requested.append(row)
        elif not stage_key:
            row["status"] = "unmapped"
            unmapped.append(row)
        elif unavailable or current_rank is None:
            row["status"] = "unavailable"
        elif CLIENT_STAGE_ORDER.index(stage_key) <= current_rank:
            row["status"] = "requestable"
            requestable_items.append(row)
        else:
            upcoming.append(row)
        schedule_table.append(row)

    requestable_total = sum((_decimal_or_zero(item.get("amount")) for item in requestable_items), Decimal("0"))
    next_upcoming = upcoming[0] if upcoming else None
    note = _client_lawyer_note(property_row, schedule, requestable_items, requestable_total) if requestable_items and not unavailable else None
    return ClientPrepDrawOut(
        status="stage_unavailable" if unavailable else "ready",
        property=property_payload,
        current_stage=stage,
        current_stage_synced_at=property_row["last_synced_at"],
        schedule=schedule,
        schedule_table=schedule_table,
        requestable_items=requestable_items,
        already_requested_items=already_requested,
        unmapped_items=unmapped,
        next_upcoming_item=next_upcoming,
        requestable_total=None if unavailable else requestable_total,
        eligibility_unavailable_reason="stage unknown" if unavailable else None,
        lawyer_note=note,
    )


async def confirm_client_prep_draw(
    db: AsyncSession,
    property_id: UUID,
    *,
    draw_items: list[dict[str, Any]],
    amount: Decimal,
    notes: str | None = None,
    prepared_by: UUID | None = None,
) -> ClientDrawRequestOut:
    schedule = await get_active_client_draw_schedule(db, property_id)
    if schedule is None or schedule.reviewed_at is None:
        raise ValueError("Reviewed OTP schedule is required")
    seqs = {int(item.get("seq") or 0) for item in draw_items}
    if not seqs:
        raise ValueError("At least one draw item is required")
    existing = await list_client_draw_requests(db, property_id)
    active_seqs = {
        int(item.get("seq") or 0)
        for request in existing
        if request.status in ACTIVE_CLIENT_REQUEST_STATUSES
        for item in request.draw_items
    }
    if seqs & active_seqs:
        raise ValueError("One or more draw items already have an active request")
    property_row = await _property_stage_row(db, property_id)
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.client_draw_requests (
                    property_id, schedule_id, draw_items, amount, stage_at_prep, prepared_by, status, notes
                )
                VALUES (
                    :property_id, :schedule_id, CAST(:draw_items AS jsonb), :amount, :stage_at_prep,
                    :prepared_by, 'prepared', :notes
                )
                RETURNING *
                """
            ),
            {
                "property_id": property_id,
                "schedule_id": schedule.id,
                "draw_items": _json_dumps(draw_items),
                "amount": amount,
                "stage_at_prep": property_row["stage_clean"] if property_row else None,
                "prepared_by": prepared_by,
                "notes": notes,
            },
        )
    ).mappings().one()
    await db.commit()
    return ClientDrawRequestOut(**row)


async def update_client_draw_request_status(
    db: AsyncSession,
    request_id: UUID,
    *,
    status: str,
    notes: str | None = None,
) -> ClientDrawRequestOut | None:
    if status not in {"prepared", "sent_to_lawyer", "funded", "cancelled"}:
        raise ValueError("Invalid draw request status")
    row = (
        await db.execute(
            text(
                """
                UPDATE documents.client_draw_requests
                SET status = :status,
                    notes = COALESCE(:notes, notes),
                    updated_at = now()
                WHERE id = :request_id
                RETURNING *
                """
            ),
            {"request_id": request_id, "status": status, "notes": notes},
        )
    ).mappings().one_or_none()
    await db.commit()
    return ClientDrawRequestOut(**row) if row else None


async def create_facility(db: AsyncSession, data: FacilityCreate) -> FacilityOut:
    values = data.model_dump()
    row = (
        await db.execute(
            text(
                """
                INSERT INTO core.lender_facilities (
                    property_id, lender_type, lender_name, total_facility, opening_balance,
                    rate, already_drawn, draw_eligible_override, requested_draw_amount,
                    requested_draw_as_of, commitment_source, commitment_confirmed_at,
                    last_draw_date, last_draw_amount,
                    account_number, account_title, account_type, current_balance, outstanding_balance,
                    account_currency, maturity_date, member_number, next_interest_payment_date,
                    next_payment_date, account_nickname, open_date, original_loan_amount,
                    payment_schedule, term_length_days, notes
                )
                VALUES (
                    :property_id, :lender_type, :lender_name, :total_facility, :opening_balance,
                    :rate, :already_drawn, :draw_eligible_override, :requested_draw_amount,
                    :requested_draw_as_of, :commitment_source, :commitment_confirmed_at,
                    :last_draw_date, :last_draw_amount,
                    :account_number, :account_title, :account_type, :current_balance, :outstanding_balance,
                    :account_currency, :maturity_date, :member_number, :next_interest_payment_date,
                    :next_payment_date, :account_nickname, :open_date, :original_loan_amount,
                    :payment_schedule, :term_length_days, :notes
                )
                RETURNING *
                """
            ),
            values,
        )
    ).mappings().one()
    await db.commit()
    return FacilityOut(**row)


async def update_facility(db: AsyncSession, facility_id: UUID, data: FacilityUpdate) -> FacilityOut | None:
    updates = data.model_dump(exclude_unset=True)
    if "lot_id" in updates and "property_id" not in updates:
        updates["property_id"] = updates.pop("lot_id")
    if not updates:
        row = (await db.execute(text("SELECT * FROM core.lender_facilities WHERE id = :id"), {"id": facility_id})).mappings().one_or_none()
        return FacilityOut(**row) if row else None
    if updates.get("property_id"):
        updates["status"] = "active"

    set_clause = ", ".join(f"{key} = :{key}" for key in updates)
    row = (
        await db.execute(
            text(
                f"""
                UPDATE core.lender_facilities
                SET {set_clause}, updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {**updates, "id": facility_id},
        )
    ).mappings().one_or_none()
    if row and row.get("property_id") and row.get("property_name"):
        await _persist_alias(db, facility_id, row["property_name"])
    await db.commit()
    return FacilityOut(**row) if row else None


async def delete_facility(db: AsyncSession, facility_id: UUID) -> bool:
    result = await db.execute(text("DELETE FROM core.lender_facilities WHERE id = :id"), {"id": facility_id})
    await db.commit()
    return (result.rowcount or 0) > 0


async def list_documents(db: AsyncSession, facility_id: UUID) -> list[FacilityDocumentOut]:
    rows = (
        await db.execute(
            text(
                """
                SELECT *
                FROM documents.lender_facility_documents
                WHERE facility_id = :facility_id
                ORDER BY uploaded_at DESC
                """
            ),
            {"facility_id": facility_id},
        )
    ).mappings().all()
    return [FacilityDocumentOut(**row) for row in rows]


async def delete_document(db: AsyncSession, doc_id: UUID) -> bool:
    result = await db.execute(text("DELETE FROM documents.lender_facility_documents WHERE id = :id"), {"id": doc_id})
    await db.commit()
    return (result.rowcount or 0) > 0


async def _record_review_document(
    db: AsyncSession,
    *,
    minio_bucket: str,
    minio_key: str,
    original_filename: str | None,
    content: bytes,
    lender_type: str,
    extracted_values: dict[str, Any],
) -> UUID | None:
    org_id = await db.scalar(select(Org.id).order_by(Org.created_at.asc()).limit(1))
    if org_id is None:
        return None

    document = Document(
        org_id=org_id,
        doc_type=DocType.OTHER,
        status=DocumentStatus.IN_REVIEW,
        original_filename=original_filename,
        minio_bucket=minio_bucket,
        minio_key=minio_key,
        file_size_bytes=len(content),
        checksum_sha256=None,
        received_from_email=f"financing:{lender_type.upper()}",
    )
    db.add(document)
    await db.flush()

    now = datetime.now(timezone.utc)
    ingestion = Ingestion(
        document_id=document.id,
        ocr_method="manual",
        ocr_text=None,
        ocr_confidence=None,
        page_count=None,
        started_at=now,
        completed_at=now,
        error_message=None,
    )
    db.add(ingestion)
    await db.flush()

    extraction = Extraction(
        ingestion_id=ingestion.id,
        model_provider="financing",
        model_version="financing-document-extractor",
        prompt_version=f"financing-{lender_type.lower()}",
        extracted_payload={
            "document_title": original_filename,
            "lender_type": lender_type.upper(),
            "financing_extraction": extracted_values,
        },
        field_confidences={},
        low_confidence_fields=[],
    )
    db.add(extraction)
    return document.id


async def record_document(
    db: AsyncSession,
    *,
    facility_id: UUID | None,
    lender_type: str,
    document_type: str,
    minio_bucket: str,
    minio_key: str,
    original_filename: str | None,
    content: bytes,
    extracted_values: dict[str, Any],
) -> tuple[UUID, UUID | None]:
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.lender_facility_documents (
                    facility_id, lender_type, document_type, minio_bucket, minio_key,
                    original_filename, extracted_values
                )
                VALUES (
                    :facility_id, :lender_type, :document_type, :minio_bucket, :minio_key,
                    :original_filename, CAST(:extracted_values AS jsonb)
                )
                RETURNING id
                """
            ),
            {
                "facility_id": facility_id,
                "lender_type": lender_type,
                "document_type": document_type,
                "minio_bucket": minio_bucket,
                "minio_key": minio_key,
                "original_filename": original_filename,
                "extracted_values": json.dumps(extracted_values),
            },
        )
    ).scalar_one()
    review_document_id = await _record_review_document(
        db,
        minio_bucket=minio_bucket,
        minio_key=minio_key,
        original_filename=original_filename,
        content=content,
        lender_type=lender_type,
        extracted_values=extracted_values,
    )
    await db.commit()
    return row, review_document_id


async def list_pro_facilities(db: AsyncSession) -> list[ProFacilityOut]:
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    lf.id,
                    lf.facility_key,
                    lf.property_name,
                    lf.borrower,
                    lf.facility_scope,
                    lf.instrument,
                    lf.annual_rate,
                    lf.original_advance_date,
                    lf.original_advance_amount,
                    lf.status,
                    latest.reconciliation_status AS last_statement_status,
                    latest.delta AS last_statement_delta
                FROM core.lender_facilities lf
                LEFT JOIN LATERAL (
                    SELECT fss.reconciliation_status, fss.delta
                    FROM documents.facility_statement_snapshots fss
                    WHERE fss.facility_id = lf.id
                    ORDER BY fss.reported_period_end_date DESC, fss.created_at DESC
                    LIMIT 1
                ) latest ON true
                WHERE COALESCE(lf.lender, lf.lender_type) = 'PRO'
                  AND lf.facility_key IS NOT NULL
                ORDER BY lf.property_name
                """
            )
        )
    ).mappings().all()

    today = date.today()
    output: list[ProFacilityOut] = []
    for row in rows:
        transactions = await _pro_transactions(db, row["id"])
        output.append(
            ProFacilityOut(
                **row,
                balance_as_of=balance_on(_pro_facility_from_row(row), transactions, today),
            )
        )
    return output


async def get_pro_ledger(db: AsyncSession, facility_id: UUID, as_of: date | None = None) -> ProLedgerOut | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    id,
                    facility_key,
                    property_name,
                    borrower,
                    annual_rate,
                    original_advance_date,
                    original_advance_amount
                FROM core.lender_facilities
                WHERE id = :facility_id
                  AND COALESCE(lender, lender_type) = 'PRO'
                """
            ),
            {"facility_id": facility_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return None

    ledger_as_of = as_of or date.today()
    facility = _pro_facility_from_row(row)
    transactions = await _pro_transactions(db, facility_id)
    result = compute_ledger(facility, transactions, ledger_as_of)
    return ProLedgerOut(
        facility_id=facility_id,
        facility_key=row["facility_key"],
        property_name=row["property_name"],
        as_of=ledger_as_of,
        balance_as_of=balance_on(facility, transactions, ledger_as_of),
        events=[ProLedgerEventOut(**event.__dict__) for event in result.events],
    )


async def record_statement(
    db: AsyncSession,
    *,
    lender: str,
    period: str,
    minio_object_key: str,
    original_filename: str | None,
) -> UUID:
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.lender_statements (
                    lender, period, minio_object_key, original_filename, status
                )
                VALUES (:lender, :period, :minio_object_key, :original_filename, 'uploaded')
                RETURNING id
                """
            ),
            {
                "lender": lender,
                "period": period,
                "minio_object_key": minio_object_key,
                "original_filename": original_filename,
            },
        )
    ).scalar_one()
    await db.commit()
    return row


async def parse_and_reconcile_statement(db: AsyncSession, statement_id: UUID, content: bytes) -> None:
    try:
        extracted = _extract_statement_text(content)
        parsed = parse_statement_text(extracted["text"])
        snapshots = []
        for page_index, statement in enumerate(parsed, start=1):
            snapshot = await _upsert_statement_snapshot(db, statement_id, statement, page_index, extracted)
            snapshots.append(snapshot)
        await db.execute(
            text(
                """
                UPDATE documents.lender_statements
                SET status = 'parsed',
                    parsed_at = now(),
                    parse_payload = CAST(:payload AS jsonb)
                WHERE id = :statement_id
                """
            ),
            {
                "statement_id": statement_id,
                "payload": json.dumps({"pages": len(parsed), "snapshots": snapshots, "extraction": extracted}, default=str),
            },
        )
    except Exception as exc:
        await db.execute(
            text(
                """
                UPDATE documents.lender_statements
                SET status = 'failed',
                    parse_payload = CAST(:payload AS jsonb)
                WHERE id = :statement_id
                """
            ),
            {"statement_id": statement_id, "payload": json.dumps({"error": str(exc)})},
        )
    await db.commit()


async def retry_statement_parse(
    db: AsyncSession,
    statement_id: UUID,
) -> LenderStatementDetailOut | None:
    statement = (
        await db.execute(
            text(
                """
                SELECT minio_object_key
                FROM documents.lender_statements
                WHERE id = :statement_id
                """
            ),
            {"statement_id": statement_id},
        )
    ).mappings().one_or_none()
    if statement is None:
        return None
    content = get_financing_document(key=statement["minio_object_key"])
    await parse_and_reconcile_statement(db, statement_id, content)
    return await get_statement(db, statement_id)


async def create_manual_statement_snapshot(
    db: AsyncSession,
    statement_id: UUID,
    data: ManualStatementSnapshotCreate,
) -> LenderStatementDetailOut | None:
    statement_exists = (
        await db.execute(
            text(
                "SELECT 1 FROM documents.lender_statements WHERE id = :statement_id"
            ),
            {"statement_id": statement_id},
        )
    ).scalar_one_or_none()
    if not statement_exists:
        return None
    facility = (
        await db.execute(
            text(
                """
                SELECT
                    id,
                    property_name,
                    canonical_address_key,
                    facility_key,
                    borrower,
                    annual_rate,
                    original_advance_date,
                    original_advance_amount
                FROM core.lender_facilities
                WHERE id = :facility_id
                  AND COALESCE(lender, lender_type) = 'PRO'
                """
            ),
            {"facility_id": data.facility_id},
        )
    ).mappings().one_or_none()
    if facility is None:
        raise ValueError("PRO facility not found")

    transactions = await _pro_transactions(db, data.facility_id)
    computed_balance = balance_on(
        _pro_facility_from_row(facility),
        transactions,
        data.reported_period_end_date,
    )
    delta = money(computed_balance - data.reported_period_end_balance)
    proposed: list[dict[str, Any]] = []
    for draw in data.draws:
        exists = (
            await db.execute(
                text(
                    """
                    SELECT 1
                    FROM core.facility_transactions
                    WHERE facility_id = :facility_id
                      AND txn_date = :txn_date
                      AND amount = :amount
                    LIMIT 1
                    """
                ),
                {
                    "facility_id": data.facility_id,
                    "txn_date": draw.txn_date,
                    "amount": draw.amount,
                },
            )
        ).scalar_one_or_none()
        if not exists:
            proposed.append(
                {
                    "date": draw.txn_date.isoformat(),
                    "amount": str(draw.amount),
                    "reference": draw.reference,
                }
            )
    status = (
        "new_draws_detected"
        if proposed
        else "matched"
        if abs(delta) <= Decimal("0.02")
        else "balance_mismatch"
    )
    payload = {
        "source": "manual",
        "draws": proposed,
        "note": data.note,
    }
    snapshot_id = (
        await db.execute(
            text(
                """
                INSERT INTO documents.facility_statement_snapshots (
                    statement_id,
                    facility_id,
                    matched_property_name,
                    canonical_address_key,
                    reported_period_end_date,
                    reported_period_end_balance,
                    computed_balance,
                    delta,
                    reconciliation_status,
                    parse_payload,
                    new_draws_detected
                )
                VALUES (
                    :statement_id,
                    :facility_id,
                    :matched_property_name,
                    :canonical_address_key,
                    :reported_period_end_date,
                    :reported_period_end_balance,
                    :computed_balance,
                    :delta,
                    :reconciliation_status,
                    CAST(:parse_payload AS jsonb),
                    CAST(:new_draws_detected AS jsonb)
                )
                ON CONFLICT ON CONSTRAINT uq_statement_snapshot_property
                DO UPDATE SET
                    facility_id = EXCLUDED.facility_id,
                    canonical_address_key = EXCLUDED.canonical_address_key,
                    reported_period_end_date = EXCLUDED.reported_period_end_date,
                    reported_period_end_balance = EXCLUDED.reported_period_end_balance,
                    computed_balance = EXCLUDED.computed_balance,
                    delta = EXCLUDED.delta,
                    reconciliation_status = EXCLUDED.reconciliation_status,
                    parse_payload = EXCLUDED.parse_payload,
                    new_draws_detected = EXCLUDED.new_draws_detected
                RETURNING id
                """
            ),
            {
                "statement_id": statement_id,
                "facility_id": data.facility_id,
                "matched_property_name": facility["property_name"],
                "canonical_address_key": facility["canonical_address_key"],
                "reported_period_end_date": data.reported_period_end_date,
                "reported_period_end_balance": data.reported_period_end_balance,
                "computed_balance": computed_balance,
                "delta": delta,
                "reconciliation_status": status,
                "parse_payload": json.dumps(payload),
                "new_draws_detected": json.dumps(proposed),
            },
        )
    ).scalar_one()
    await db.execute(
        text(
            """
            UPDATE documents.lender_statements
            SET
                status = 'parsed',
                parsed_at = COALESCE(parsed_at, now()),
                parse_payload = COALESCE(parse_payload, '{}'::jsonb)
                    || jsonb_build_object('manual_entry', true)
            WHERE id = :statement_id
            """
        ),
        {"statement_id": statement_id},
    )
    await db.commit()
    if snapshot_id is None:
        return None
    return await get_statement(db, statement_id)


async def approve_snapshot_draws(db: AsyncSession, snapshot_id: UUID) -> FacilityStatementSnapshotOut | None:
    snapshot = (
        await db.execute(
            text("SELECT * FROM documents.facility_statement_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
    ).mappings().one_or_none()
    if not snapshot or not snapshot["facility_id"]:
        return None
    for draw in snapshot["new_draws_detected"] or []:
        await db.execute(
            text(
                """
                INSERT INTO core.facility_transactions (facility_id, txn_date, txn_type, amount, reference, source, statement_id)
                VALUES (:facility_id, :txn_date, 'draw', :amount, :reference, 'statement', :statement_id)
                ON CONFLICT ON CONSTRAINT uq_facility_transactions_identity DO NOTHING
                """
            ),
            {
                "facility_id": snapshot["facility_id"],
                "txn_date": date.fromisoformat(draw["date"]),
                "amount": Decimal(str(draw["amount"])),
                "reference": draw.get("reference"),
                "statement_id": snapshot["statement_id"],
            },
        )
    await _reconcile_snapshot(db, snapshot_id)
    await db.commit()
    return await _snapshot_out(db, snapshot_id)


async def link_snapshot_facility(db: AsyncSession, snapshot_id: UUID, facility_id: UUID) -> FacilityStatementSnapshotOut | None:
    snapshot = (
        await db.execute(
            text("SELECT matched_property_name FROM documents.facility_statement_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
    ).mappings().one_or_none()
    if not snapshot:
        return None
    await db.execute(
        text("UPDATE documents.facility_statement_snapshots SET facility_id = :facility_id WHERE id = :id"),
        {"facility_id": facility_id, "id": snapshot_id},
    )
    await _persist_alias(db, facility_id, snapshot["matched_property_name"])
    await _reconcile_snapshot(db, snapshot_id)
    await db.commit()
    return await _snapshot_out(db, snapshot_id)


async def list_statements(db: AsyncSession, lender: str | None = None) -> list[LenderStatementOut]:
    where = "WHERE lender = :lender" if lender else ""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, lender, period, minio_object_key, original_filename, uploaded_at, parsed_at, status
                FROM documents.lender_statements
                {where}
                ORDER BY period DESC, uploaded_at DESC
                """
            ),
            {"lender": lender} if lender else {},
        )
    ).mappings().all()
    return [LenderStatementOut(**row) for row in rows]


async def get_statement(db: AsyncSession, statement_id: UUID) -> LenderStatementDetailOut | None:
    statement = (
        await db.execute(
            text(
                """
                SELECT id, lender, period, minio_object_key, original_filename, uploaded_at, parsed_at, parse_payload, status
                FROM documents.lender_statements
                WHERE id = :statement_id
                """
            ),
            {"statement_id": statement_id},
        )
    ).mappings().one_or_none()
    if statement is None:
        return None
    snapshots = (
        await db.execute(
            text(
                """
                SELECT *
                FROM documents.facility_statement_snapshots
                WHERE statement_id = :statement_id
                ORDER BY matched_property_name
                """
            ),
            {"statement_id": statement_id},
        )
    ).mappings().all()
    return LenderStatementDetailOut(
        **statement,
        snapshots=[FacilityStatementSnapshotOut(**snapshot) for snapshot in snapshots],
    )


def _extract_statement_text(content: bytes) -> dict[str, Any]:
    if content.startswith(b"%PDF"):
        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract is required for scanned statement OCR. Install with: brew install tesseract ghostscript")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        try:
            result = PDFExtractor().extract(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "text": "\f".join(page.text for page in result.pages),
            "total_pages": result.total_pages,
            "method": result.method_used,
            "pages": [{"page": page.page_number, "method": page.method, "text": page.text} for page in result.pages],
        }
    return {"text": content.decode("utf-8"), "total_pages": None, "method": "text", "pages": []}


async def _upsert_statement_snapshot(
    db: AsyncSession,
    statement_id: UUID,
    statement: ParsedProFacilityStatement,
    page_index: int,
    extracted: dict[str, Any],
) -> dict[str, Any]:
    canonical = normalize_canonical_address(statement.property_name)
    facility_id = await _match_facility(db, statement.property_name, canonical.canonical_key)
    proposed = await _proposed_draws(db, facility_id, statement)
    computed_balance = None
    delta = None
    status = "unmatched"
    if facility_id:
        facility_row = (
            await db.execute(
                text(
                    """
                    SELECT facility_key, property_name, borrower, annual_rate, original_advance_date, original_advance_amount
                    FROM core.lender_facilities
                    WHERE id = :facility_id
                    """
                ),
                {"facility_id": facility_id},
            )
        ).mappings().one()
        computed_balance = balance_on(_pro_facility_from_row(facility_row), await _pro_transactions(db, facility_id), statement.period_end_date)
        delta = money(computed_balance - statement.period_end_balance)
        if proposed:
            status = "new_draws_detected"
        elif abs(delta) <= Decimal("0.02") and not statement.validation_errors:
            status = "matched"
        else:
            status = "balance_mismatch"

    payload = {
        "page": page_index,
        "property_name": statement.property_name,
        "draws": [draw.__dict__ for draw in statement.draws],
        "validation_errors": statement.validation_errors,
        "ocr_text": (extracted.get("pages") or [{}])[page_index - 1].get("text") if extracted.get("pages") else None,
    }
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents.facility_statement_snapshots (
                    statement_id, facility_id, matched_property_name, canonical_address_key,
                    reported_period_end_date, reported_period_end_balance, computed_balance,
                    delta, reconciliation_status, parse_payload, new_draws_detected
                )
                VALUES (
                    :statement_id, :facility_id, :matched_property_name, :canonical_address_key,
                    :reported_period_end_date, :reported_period_end_balance, :computed_balance,
                    :delta, :reconciliation_status, CAST(:parse_payload AS jsonb), CAST(:new_draws_detected AS jsonb)
                )
                ON CONFLICT ON CONSTRAINT uq_statement_snapshot_property DO UPDATE SET
                    facility_id = EXCLUDED.facility_id,
                    canonical_address_key = EXCLUDED.canonical_address_key,
                    reported_period_end_date = EXCLUDED.reported_period_end_date,
                    reported_period_end_balance = EXCLUDED.reported_period_end_balance,
                    computed_balance = EXCLUDED.computed_balance,
                    delta = EXCLUDED.delta,
                    reconciliation_status = EXCLUDED.reconciliation_status,
                    parse_payload = EXCLUDED.parse_payload,
                    new_draws_detected = EXCLUDED.new_draws_detected
                RETURNING id, reconciliation_status
                """
            ),
            {
                "statement_id": statement_id,
                "facility_id": facility_id,
                "matched_property_name": statement.property_name,
                "canonical_address_key": canonical.canonical_key,
                "reported_period_end_date": statement.period_end_date,
                "reported_period_end_balance": statement.period_end_balance,
                "computed_balance": computed_balance,
                "delta": delta,
                "reconciliation_status": status,
                "parse_payload": json.dumps(payload, default=str),
                "new_draws_detected": json.dumps(proposed, default=str),
            },
        )
    ).mappings().one()
    return {"id": row["id"], "status": row["reconciliation_status"], "property_name": statement.property_name}


async def _match_facility(db: AsyncSession, raw_name: str, canonical_key: str) -> UUID | None:
    alias = (
        await db.execute(
            text(
                """
                SELECT facility_id
                FROM core.facility_aliases
                WHERE alias IN (:raw_name, :canonical_key)
                LIMIT 1
                """
            ),
            {"raw_name": raw_name, "canonical_key": canonical_key},
        )
    ).scalar_one_or_none()
    if alias:
        return alias
    candidates = (
        await db.execute(
            text(
                """
                SELECT id
                FROM core.lender_facilities
                WHERE COALESCE(lender, lender_type) = 'PRO'
                  AND canonical_address_key = :canonical_key
                """
            ),
            {"canonical_key": canonical_key},
        )
    ).scalars().all()
    return candidates[0] if len(candidates) == 1 else None


async def _proposed_draws(db: AsyncSession, facility_id: UUID | None, statement: ParsedProFacilityStatement) -> list[dict[str, Any]]:
    if not facility_id:
        return [{"date": draw.txn_date.isoformat(), "amount": str(draw.amount), "reference": draw.reference} for draw in statement.draws]
    proposed = []
    for draw in statement.draws:
        exists = (
            await db.execute(
                text(
                    """
                    SELECT 1
                    FROM core.facility_transactions
                    WHERE facility_id = :facility_id
                      AND txn_date = :txn_date
                      AND amount = :amount
                    LIMIT 1
                    """
                ),
                {"facility_id": facility_id, "txn_date": draw.txn_date, "amount": draw.amount},
            )
        ).scalar_one_or_none()
        if not exists:
            proposed.append({"date": draw.txn_date.isoformat(), "amount": str(draw.amount), "reference": draw.reference})
    return proposed


async def _reconcile_snapshot(db: AsyncSession, snapshot_id: UUID) -> None:
    snapshot = (
        await db.execute(
            text("SELECT * FROM documents.facility_statement_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
    ).mappings().one()
    if not snapshot["facility_id"]:
        return
    facility_row = (
        await db.execute(
            text(
                """
                SELECT facility_key, property_name, borrower, annual_rate, original_advance_date, original_advance_amount
                FROM core.lender_facilities
                WHERE id = :facility_id
                """
            ),
            {"facility_id": snapshot["facility_id"]},
        )
    ).mappings().one()
    computed_balance = balance_on(_pro_facility_from_row(facility_row), await _pro_transactions(db, snapshot["facility_id"]), snapshot["reported_period_end_date"])
    delta = money(computed_balance - snapshot["reported_period_end_balance"])
    parse_payload = snapshot["parse_payload"] or {}
    parsed_draws = [
        ProTransaction(
            txn_date=date.fromisoformat(draw["txn_date"] if "txn_date" in draw else draw["date"]),
            txn_type="draw",
            amount=Decimal(str(draw["amount"])),
            reference=draw.get("reference"),
        )
        for draw in parse_payload.get("draws", [])
    ]
    proposed = []
    for draw in parsed_draws:
        exists = (
            await db.execute(
                text(
                    """
                    SELECT 1
                    FROM core.facility_transactions
                    WHERE facility_id = :facility_id
                      AND txn_date = :txn_date
                      AND amount = :amount
                    LIMIT 1
                    """
                ),
                {"facility_id": snapshot["facility_id"], "txn_date": draw.txn_date, "amount": draw.amount},
            )
        ).scalar_one_or_none()
        if not exists:
            proposed.append({"date": draw.txn_date.isoformat(), "amount": str(draw.amount), "reference": draw.reference})
    status = "matched" if abs(delta) <= Decimal("0.02") else "balance_mismatch"
    await db.execute(
        text(
            """
            UPDATE documents.facility_statement_snapshots
            SET computed_balance = :computed_balance,
                delta = :delta,
                reconciliation_status = :status,
                new_draws_detected = CAST(:new_draws_detected AS jsonb)
            WHERE id = :id
            """
        ),
        {
            "id": snapshot_id,
            "computed_balance": computed_balance,
            "delta": delta,
            "status": status if not proposed else "new_draws_detected",
            "new_draws_detected": json.dumps(proposed, default=str),
        },
    )


async def _snapshot_out(db: AsyncSession, snapshot_id: UUID) -> FacilityStatementSnapshotOut | None:
    row = (
        await db.execute(
            text("SELECT * FROM documents.facility_statement_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        )
    ).mappings().one_or_none()
    return FacilityStatementSnapshotOut(**row) if row else None


async def _pro_transactions(db: AsyncSession, facility_id: UUID) -> list[ProTransaction]:
    rows = (
        await db.execute(
            text(
                """
                SELECT txn_date, txn_type, amount, reference
                FROM core.facility_transactions
                WHERE facility_id = :facility_id
                ORDER BY txn_date, created_at
                """
            ),
            {"facility_id": facility_id},
        )
    ).mappings().all()
    return [
        ProTransaction(
            txn_date=row["txn_date"],
            txn_type=row["txn_type"],
            amount=row["amount"],
            reference=row["reference"],
        )
        for row in rows
    ]


def _pro_facility_from_row(row: Any) -> ProFacility:
    return ProFacility(
        facility_key=row["facility_key"],
        property_name=row["property_name"],
        borrower=row["borrower"] or "",
        annual_rate=row["annual_rate"],
        original_advance_date=row["original_advance_date"],
        original_advance_amount=row["original_advance_amount"],
    )


async def _milestone_history_by_property(
    db: AsyncSession,
    property_ids: set[UUID],
) -> dict[UUID, list[ConstructionMilestoneOut]]:
    if not property_ids:
        return {}
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    milestone.id,
                    milestone.property_id,
                    milestone.stage,
                    milestone.achieved_at,
                    milestone.source,
                    milestone.confirmed_at,
                    milestone.confirmation_note,
                    COALESCE(
                        jsonb_agg(
                            jsonb_build_object(
                                'id', revision.id,
                                'previous_achieved_at', revision.previous_achieved_at,
                                'achieved_at', revision.achieved_at,
                                'action', revision.action,
                                'note', revision.note,
                                'created_at', revision.created_at
                            )
                            ORDER BY revision.created_at
                        ) FILTER (WHERE revision.id IS NOT NULL),
                        '[]'::jsonb
                    ) AS revisions
                FROM documents.construction_stage_milestones milestone
                LEFT JOIN documents.construction_stage_milestone_revisions revision
                    ON revision.milestone_id = milestone.id
                WHERE milestone.property_id IN :property_ids
                GROUP BY milestone.id
                ORDER BY milestone.achieved_at, milestone.created_at
                """
            ).bindparams(bindparam("property_ids", expanding=True)),
            {"property_ids": list(property_ids)},
        )
    ).mappings().all()
    history: dict[UUID, list[ConstructionMilestoneOut]] = {}
    for row in rows:
        history.setdefault(row["property_id"], []).append(ConstructionMilestoneOut(**row))
    return history


async def update_construction_milestone(
    db: AsyncSession,
    milestone_id: UUID,
    data: ConstructionMilestoneUpdate,
) -> ConstructionMilestoneOut | None:
    milestone = (
        await db.execute(
            text(
                """
                SELECT id, achieved_at
                FROM documents.construction_stage_milestones
                WHERE id = :milestone_id
                FOR UPDATE
                """
            ),
            {"milestone_id": milestone_id},
        )
    ).mappings().one_or_none()
    if milestone is None:
        return None

    achieved_at = datetime(
        data.achieved_on.year,
        data.achieved_on.month,
        data.achieved_on.day,
        12,
        tzinfo=timezone.utc,
    )
    action = (
        "confirmed"
        if milestone["achieved_at"].date() == data.achieved_on
        else "date_corrected"
    )
    note = data.note.strip() if data.note and data.note.strip() else None
    await db.execute(
        text(
            """
            INSERT INTO documents.construction_stage_milestone_revisions (
                milestone_id,
                previous_achieved_at,
                achieved_at,
                action,
                note
            )
            VALUES (
                :milestone_id,
                :previous_achieved_at,
                :achieved_at,
                :action,
                :note
            )
            """
        ),
        {
            "milestone_id": milestone_id,
            "previous_achieved_at": milestone["achieved_at"],
            "achieved_at": achieved_at,
            "action": action,
            "note": note,
        },
    )
    updated = (
        await db.execute(
            text(
                """
                UPDATE documents.construction_stage_milestones
                SET
                    achieved_at = :achieved_at,
                    confirmed_at = now(),
                    confirmation_note = :note
                WHERE id = :milestone_id
                RETURNING property_id
                """
            ),
            {
                "milestone_id": milestone_id,
                "achieved_at": achieved_at,
                "note": note,
            },
        )
    ).mappings().one()
    await db.commit()
    history = await _milestone_history_by_property(db, {updated["property_id"]})
    return next(
        (
            event
            for event in history.get(updated["property_id"], [])
            if event.id == milestone_id
        ),
        None,
    )


def _property_from_row(
    row: Any,
    *,
    pro_balance: Decimal | None = None,
    pro_principal: Decimal | None = None,
    milestone_history: list[ConstructionMilestoneOut] | None = None,
) -> FinancingPropertyOut:
    history = milestone_history or []
    current_stage = row["stage_clean"]
    achieved_at = next(
        (event.achieved_at for event in reversed(history) if event.stage == current_stage),
        None,
    )
    lender_type = row["lender_type"] or "OTHER"
    if lender_type == "PRO" and pro_balance is not None:
        rate = (row["annual_rate"] * Decimal("100")) if row["annual_rate"] is not None else None
        facility_total = row["total_facility"] or pro_principal
        principal_drawn = pro_principal or Decimal("0")
        accrued_interest = max(Decimal("0"), pro_balance - principal_drawn)
        interest = _interest_estimates(pro_balance, rate)
        calc = calculate_draw(
            lender_type="PRO",
            stage=row["stage_clean"],
            total_facility=facility_total,
            opening_balance=row["opening_balance"],
            already_drawn=principal_drawn,
        )
        draw_eligible = row["draw_eligible_override"]
        if draw_eligible is None:
            draw_eligible = calc.draw_eligible
        cumulative_entitled = (
            principal_drawn + draw_eligible
            if row["draw_eligible_override"] is not None
            else calc.cumulative_entitled
        )
        return FinancingPropertyOut(
            property_id=row["property_id"],
            address=row["address"],
            lender_type="PRO",
            sold_or_spec=row["sold_or_spec"],
            stage=row["stage_clean"],
            stage_is_estimate=False,
            milestone_achieved_at=achieved_at,
            milestone_history=history,
            possession_date=row["possession_date"],
            build_start=row["build_start"],
            client_name=row["client_name"],
            banker_raw=row["banker_raw"],
            lender_name=row["lender_name"] or "ProAuto",
            total_facility=facility_total,
            opening_balance=row["original_advance_amount"],
            already_drawn=principal_drawn,
            last_draw_date=row["last_draw_date"],
            last_draw_amount=row["last_draw_amount"],
            requested_draw_amount=row["requested_draw_amount"],
            requested_draw_as_of=row["requested_draw_as_of"],
            commitment_source=row["commitment_source"],
            commitment_confirmed_at=row["commitment_confirmed_at"],
            rate=rate,
            account_number=row["account_number"],
            account_title=row["account_title"],
            account_type=row["account_type"],
            current_balance=pro_balance,
            outstanding_balance=pro_balance,
            accrued_interest=accrued_interest,
            account_currency=row["account_currency"] or "CAD",
            maturity_date=row["maturity_date"],
            member_number=row["member_number"],
            next_interest_payment_date=row["next_interest_payment_date"],
            next_payment_date=row["next_payment_date"],
            account_nickname=row["account_nickname"],
            open_date=row["original_advance_date"] or row["open_date"],
            original_loan_amount=row["original_advance_amount"],
            payment_schedule=row["payment_schedule"],
            term_length_days=row["term_length_days"],
            daily_interest_estimate=interest["daily"],
            monthly_interest_estimate=interest["monthly"],
            annual_interest_estimate=interest["annual"],
            notes=row["notes"],
            draw_eligible=draw_eligible,
            cumulative_entitled=cumulative_entitled,
            funds_remaining=(
                max(Decimal("0"), facility_total - principal_drawn)
                if facility_total is not None
                else None
            ),
            flag=(
                "NEEDS_LINK"
                if row["status"] == "needs_link"
                else None if row["draw_eligible_override"] is not None else calc.flag
            ),
            formula=(
                "Lender-confirmed PRO draw availability override."
                if row["draw_eligible_override"] is not None
                else calc.formula
            ),
            facility_id=row["facility_id"],
        )
    if lender_type == "PRO":
        principal_drawn = row["already_drawn"] or Decimal("0")
        calc = calculate_draw(
            lender_type="PRO",
            stage=row["stage_clean"],
            total_facility=row["total_facility"],
            opening_balance=row["opening_balance"],
            already_drawn=principal_drawn,
        )
        draw_eligible = row["draw_eligible_override"]
        if draw_eligible is None:
            draw_eligible = calc.draw_eligible
        cumulative_entitled = (
            principal_drawn + draw_eligible
            if row["draw_eligible_override"] is not None
            else calc.cumulative_entitled
        )
        return FinancingPropertyOut(
            property_id=row["property_id"],
            address=row["address"],
            lender_type="PRO",
            sold_or_spec=row["sold_or_spec"],
            stage=row["stage_clean"],
            stage_is_estimate=False,
            milestone_achieved_at=achieved_at,
            milestone_history=history,
            possession_date=row["possession_date"],
            build_start=row["build_start"],
            client_name=row["client_name"],
            banker_raw=row["banker_raw"],
            lender_name=row["lender_name"],
            total_facility=row["total_facility"],
            opening_balance=row["opening_balance"],
            already_drawn=principal_drawn,
            last_draw_date=row["last_draw_date"],
            last_draw_amount=row["last_draw_amount"],
            requested_draw_amount=row["requested_draw_amount"],
            requested_draw_as_of=row["requested_draw_as_of"],
            commitment_source=row["commitment_source"],
            commitment_confirmed_at=row["commitment_confirmed_at"],
            rate=row["rate"],
            account_number=row["account_number"],
            account_title=row["account_title"],
            account_type=row["account_type"],
            current_balance=row["current_balance"],
            outstanding_balance=row["outstanding_balance"],
            account_currency=row["account_currency"],
            maturity_date=row["maturity_date"],
            member_number=row["member_number"],
            next_interest_payment_date=row["next_interest_payment_date"],
            next_payment_date=row["next_payment_date"],
            account_nickname=row["account_nickname"],
            open_date=row["open_date"],
            original_loan_amount=row["original_loan_amount"],
            payment_schedule=row["payment_schedule"],
            term_length_days=row["term_length_days"],
            daily_interest_estimate=None,
            monthly_interest_estimate=None,
            annual_interest_estimate=None,
            notes=row["notes"],
            draw_eligible=draw_eligible,
            cumulative_entitled=cumulative_entitled,
            funds_remaining=(
                max(Decimal("0"), row["total_facility"] - principal_drawn)
                if row["total_facility"] is not None
                else None
            ),
            flag=None if row["draw_eligible_override"] is not None else calc.flag or "NO_STATEMENT",
            formula=(
                "Lender-confirmed PRO draw availability override."
                if row["draw_eligible_override"] is not None
                else calc.formula
            ),
            facility_id=row["facility_id"],
        )
    calc = calculate_draw(
        lender_type=lender_type,
        stage=row["stage_clean"],
        total_facility=row["total_facility"],
        opening_balance=row["opening_balance"],
        already_drawn=row["already_drawn"],
    )
    opening = row["opening_balance"]
    drawn = row["already_drawn"] or Decimal("0")
    interest = _interest_estimates(row["outstanding_balance"], row["rate"])
    return FinancingPropertyOut(
        property_id=row["property_id"],
        address=row["address"],
        lender_type=lender_type,
        sold_or_spec=row["sold_or_spec"],
        stage=row["stage_clean"],
        stage_is_estimate=calc.stage_is_estimate,
        milestone_achieved_at=achieved_at,
        milestone_history=history,
        possession_date=row["possession_date"],
        build_start=row["build_start"],
        client_name=row["client_name"],
        banker_raw=row["banker_raw"],
        lender_name=row["lender_name"],
        total_facility=row["total_facility"],
        opening_balance=opening,
        already_drawn=drawn,
        last_draw_date=row["last_draw_date"],
        last_draw_amount=row["last_draw_amount"],
        requested_draw_amount=row["requested_draw_amount"],
        requested_draw_as_of=row["requested_draw_as_of"],
        commitment_source=row["commitment_source"],
        commitment_confirmed_at=row["commitment_confirmed_at"],
        rate=row["rate"],
        account_number=row["account_number"],
        account_title=row["account_title"],
        account_type=row["account_type"],
        current_balance=row["current_balance"],
        outstanding_balance=row["outstanding_balance"],
        account_currency=row["account_currency"],
        maturity_date=row["maturity_date"],
        member_number=row["member_number"],
        next_interest_payment_date=row["next_interest_payment_date"],
        next_payment_date=row["next_payment_date"],
        account_nickname=row["account_nickname"],
        open_date=row["open_date"],
        original_loan_amount=row["original_loan_amount"],
        payment_schedule=row["payment_schedule"],
        term_length_days=row["term_length_days"],
        daily_interest_estimate=interest["daily"],
        monthly_interest_estimate=interest["monthly"],
        annual_interest_estimate=interest["annual"],
        notes=row["notes"],
        draw_eligible=calc.draw_eligible,
        cumulative_entitled=calc.cumulative_entitled,
        funds_remaining=(opening - drawn) if opening is not None else None,
        flag=calc.flag,
        formula=calc.formula,
        facility_id=row["facility_id"],
    )


async def _property_row(db: AsyncSession, property_id: UUID) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id, address, canonical_address_key
                FROM core.properties
                WHERE id = :property_id
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


async def _property_stage_row(db: AsyncSession, property_id: UUID) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    p.id AS property_id,
                    p.address,
                    css.client_name,
                    COALESCE(css.lender_type, 'OTHER') AS lender_type,
                    css.stage_clean,
                    css.last_synced_at
                FROM core.properties p
                LEFT JOIN documents.construction_stage_sync css ON css.property_id = p.id
                WHERE p.id = :property_id
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


async def _client_schedule_row(db: AsyncSession, schedule_id: UUID) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text("SELECT * FROM documents.client_draw_schedules WHERE id = :schedule_id"),
            {"schedule_id": schedule_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


async def _normalize_client_schedule_payload(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    purchase_price = _decimal_or_none(payload.get("purchase_price"))
    schedule: list[dict[str, Any]] = []
    for index, raw_item in enumerate(payload.get("schedule") or [], start=1):
        if not isinstance(raw_item, dict):
            continue
        label = str(raw_item.get("label_raw") or raw_item.get("label") or "").strip()
        if not label:
            continue
        percent = _decimal_or_none(raw_item.get("percent"))
        amount = _decimal_or_none(raw_item.get("amount"))
        amount_type = str(raw_item.get("amount_type") or ("percent" if percent is not None else "fixed")).lower()
        if amount is None and amount_type == "percent" and percent is not None and purchase_price is not None:
            amount = (purchase_price * percent / Decimal("100")).quantize(Decimal("0.01"))
        stage_key = _clean_stage_key(raw_item.get("stage_key")) or await _stage_key_for_label(db, label)
        schedule.append(
            {
                "seq": int(raw_item.get("seq") or index),
                "label_raw": label,
                "stage_key": stage_key,
                "amount": str(amount) if amount is not None else None,
                "amount_type": "percent" if amount_type == "percent" else "fixed",
                "percent": str(percent) if percent is not None else None,
                "conditions_raw": raw_item.get("conditions_raw"),
                "source_page": _int_or_none(raw_item.get("source_page")),
            }
        )

    deposits: list[dict[str, Any]] = []
    for index, raw_deposit in enumerate(payload.get("deposits") or [], start=1):
        if not isinstance(raw_deposit, dict):
            continue
        deposits.append(
            {
                "seq": _int_or_none(raw_deposit.get("seq")) or index,
                "label_raw": raw_deposit.get("label_raw"),
                "amount": str(_decimal_or_none(raw_deposit.get("amount"))) if _decimal_or_none(raw_deposit.get("amount")) is not None else None,
                "due_raw": raw_deposit.get("due_raw"),
                "source_page": _int_or_none(raw_deposit.get("source_page")),
            }
        )

    notes = str(payload.get("notes") or payload.get("extraction_notes") or "").strip()
    confidence = str(payload.get("confidence") or payload.get("extraction_confidence") or "needs_review").lower()
    validation_notes = _client_schedule_validation_notes(purchase_price, schedule, deposits)
    if validation_notes:
        notes = "; ".join(part for part in (notes, validation_notes) if part)
        confidence = "needs_review"
    return {
        "purchase_price": purchase_price,
        "client_name": payload.get("client_name") or payload.get("purchaser_name"),
        "otp_date": _date_or_none(payload.get("otp_date")),
        "schedule": schedule,
        "deposits": deposits,
        "extraction_confidence": "high" if confidence == "high" and schedule else "needs_review",
        "extraction_notes": notes or None,
    }


def _client_schedule_validation_notes(
    purchase_price: Decimal | None,
    schedule: list[dict[str, Any]],
    deposits: list[dict[str, Any]],
) -> str | None:
    if not schedule:
        return "No draw schedule was extracted."
    missing_pages = [str(item["seq"]) for item in schedule if item.get("amount") and not item.get("source_page")]
    notes: list[str] = []
    if missing_pages:
        notes.append(f"Missing source page on schedule item(s): {', '.join(missing_pages)}")
    if purchase_price is not None:
        total = sum((_decimal_or_zero(item.get("amount")) for item in schedule), Decimal("0"))
        total += sum((_decimal_or_zero(item.get("amount")) for item in deposits), Decimal("0"))
        if total and abs(total - purchase_price) > Decimal("1.00"):
            notes.append(f"Draw schedule plus deposits totals {total}, not purchase price {purchase_price}.")
    return "; ".join(notes) if notes else None


async def _stage_key_for_label(db: AsyncSession, label: str) -> str | None:
    normalized = _normalize_stage_label(label)
    exact = (
        await db.execute(
            text(
                """
                SELECT stage_key
                FROM documents.stage_label_aliases
                WHERE label_normalized = :label
                """
            ),
            {"label": normalized},
        )
    ).scalar_one_or_none()
    if exact:
        return str(exact)
    aliases = (
        await db.execute(
            text("SELECT label_normalized, stage_key FROM documents.stage_label_aliases")
        )
    ).mappings().all()
    for alias in aliases:
        if str(alias["label_normalized"]) in normalized:
            return str(alias["stage_key"])
    return None


async def _upsert_stage_label_alias(db: AsyncSession, label: str, stage_key: str) -> None:
    normalized = _normalize_stage_label(label)
    if not normalized:
        return
    await db.execute(
        text(
            """
            INSERT INTO documents.stage_label_aliases (label_raw, label_normalized, stage_key)
            VALUES (:label_raw, :label_normalized, :stage_key)
            ON CONFLICT ON CONSTRAINT uq_stage_label_aliases_label_normalized DO UPDATE SET
                stage_key = EXCLUDED.stage_key,
                updated_at = now()
            """
        ),
        {"label_raw": label, "label_normalized": normalized, "stage_key": stage_key},
    )


def _client_request_index(requests: list[ClientDrawRequestOut]) -> dict[int, ClientDrawRequestOut]:
    index: dict[int, ClientDrawRequestOut] = {}
    for request in requests:
        if request.status not in ACTIVE_CLIENT_REQUEST_STATUSES:
            continue
        for item in request.draw_items:
            seq = int(item.get("seq") or 0)
            if seq:
                index[seq] = request
    return index


def _client_lawyer_note(
    property_row: dict[str, Any],
    schedule: ClientDrawScheduleOut,
    requestable_items: list[dict[str, Any]],
    requestable_total: Decimal,
) -> str:
    milestones = ", ".join(
        f"{item.get('label_raw')} (page {item.get('source_page') or 'n/a'})"
        for item in requestable_items
    )
    client = schedule.client_name or property_row.get("client_name") or "the purchaser"
    otp_date = schedule.otp_date.isoformat() if schedule.otp_date else "the OTP"
    return (
        f"Please request {requestable_total} from {client} for {property_row['address']}. "
        f"The current construction stage is {property_row.get('stage_clean') or 'NA'}; "
        f"the reached OTP milestone(s) per {otp_date}: {milestones}."
    )


def _normalize_stage_label(label: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", label.upper()).strip()


def _clean_stage_key(value: object) -> str | None:
    if value in (None, ""):
        return None
    stage = str(value).upper().strip()
    return stage if stage in CLIENT_STAGE_ORDER else None


def _date_or_none(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value).replace(",", "").replace("$", "").strip())


def _decimal_or_zero(value: object) -> Decimal:
    return _decimal_or_none(value) or Decimal("0")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _interest_estimates(
    outstanding_balance: Decimal | None,
    rate: Decimal | None,
) -> dict[str, Decimal | None]:
    if outstanding_balance is None or rate is None:
        return {"daily": None, "monthly": None, "annual": None}
    annual_rate = rate / Decimal("100") if rate > Decimal("1") else rate
    annual = (outstanding_balance * annual_rate).quantize(Decimal("0.01"))
    monthly = (annual / Decimal("12")).quantize(Decimal("0.01"))
    daily = (annual / Decimal("365")).quantize(Decimal("0.01"))
    return {"daily": daily, "monthly": monthly, "annual": annual}


def _summary(properties: list[FinancingPropertyOut]) -> DashboardSummary:
    data: dict[str, dict[str, Any]] = {
        lender: {"total_drawable": Decimal("0"), "properties": 0, "flagged": 0}
        for lender in LENDER_TYPES
    }
    data["CLIENT"]["total_drawable"] = None
    data["OTHER"]["total_drawable"] = None

    for item in properties:
        lender = item.lender_type if item.lender_type in data else "OTHER"
        data[lender]["properties"] += 1
        if item.flag:
            data[lender]["flagged"] += 1
        if data[lender]["total_drawable"] is not None:
            data[lender]["total_drawable"] += item.draw_eligible or Decimal("0")

    return DashboardSummary(
        **{key: LenderSummary(**value) for key, value in data.items()}
    )


def _dedupe_dashboard_properties(properties: list[FinancingPropertyOut]) -> list[FinancingPropertyOut]:
    selected: dict[UUID, FinancingPropertyOut] = {}
    for item in properties:
        current = selected.get(item.property_id)
        if current is None or _dashboard_property_rank(item) > _dashboard_property_rank(current):
            selected[item.property_id] = item
    return list(selected.values())


def _dashboard_property_rank(item: FinancingPropertyOut) -> tuple[int, int, int, int]:
    return (
        1 if item.facility_id is not None else 0,
        1 if item.lender_type != "OTHER" else 0,
        1 if item.stage not in {None, "", "NA"} else 0,
        1 if item.already_drawn and item.already_drawn > Decimal("0") else 0,
    )


def _assert_no_duplicate_pro_properties(properties: list[FinancingPropertyOut]) -> None:
    pro_keys = [item.property_id for item in properties if item.lender_type == "PRO"]
    assert len(pro_keys) == len(set(pro_keys))


async def _persist_alias(db: AsyncSession, facility_id: UUID, alias: str) -> None:
    await db.execute(
        text(
            """
            INSERT INTO core.facility_aliases (facility_id, alias)
            VALUES (:facility_id, :alias)
            ON CONFLICT (alias) DO UPDATE SET facility_id = EXCLUDED.facility_id
            """
        ),
        {"facility_id": facility_id, "alias": alias},
    )
