from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.core import Org
from app.models.documents import DocType
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion
from app.modules.costbook.models import Budget
from app.modules.costbook.models import BudgetLine
from app.modules.costbook.models import CostCategory
from app.modules.costbook.service import current_fiscal_year
from app.services.extraction.service import get_extraction_service
from app.services.ocr.extractor import PDFExtractor


DOCUMENTS_BUCKET = "documents"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestResult:
    document_id: UUID
    status: DocumentStatus
    extraction_summary: str
    resource_type: str = "document"
    resource_id: UUID | None = None


class BudgetProjectMatchRequired(ValueError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        search_text: str,
        candidates: list[dict[str, str | None]] | None = None,
    ) -> None:
        super().__init__(message)
        self.detail = {
            "code": code,
            "message": message,
            "search_text": search_text,
            "candidates": candidates or [],
        }


class IngestService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def ingest_budget_file(
        self,
        *,
        file: UploadFile,
        matched_lot_id: UUID | None = None,
    ) -> IngestResult:
        filename = Path(file.filename or "budget-import").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            raise ValueError("Budget imports must be .csv or .xlsx files")

        file_bytes = await file.read()
        await file.close()
        if not file_bytes:
            raise ValueError("Uploaded budget file is empty")

        rows = self._parse_budget_rows(file_bytes=file_bytes, suffix=suffix)
        org_id = await self._fetch_default_org_id()
        matched_project = await self._resolve_budget_project(
            org_id=org_id,
            filename=filename,
            rows=rows,
            matched_lot_id=matched_lot_id,
        )

        checksum = hashlib.sha256(file_bytes).hexdigest()
        minio_key = f"imports/budgets/{uuid4()}-{filename}"
        content_type = file.content_type or self._content_type_for_suffix(suffix)
        self._upload_bytes(file_bytes=file_bytes, minio_key=minio_key, content_type=content_type)

        document = Document(
            org_id=org_id,
            doc_type=DocType.OTHER,
            status=DocumentStatus.APPROVED,
            original_filename=filename,
            minio_bucket=DOCUMENTS_BUCKET,
            minio_key=minio_key,
            file_size_bytes=len(file_bytes),
            checksum_sha256=checksum,
        )
        self._db.add(document)
        try:
            await self._db.flush()
        except IntegrityError:
            await self._db.rollback()
            document = Document(
                org_id=org_id,
                doc_type=DocType.OTHER,
                status=DocumentStatus.APPROVED,
                original_filename=filename,
                minio_bucket=DOCUMENTS_BUCKET,
                minio_key=minio_key,
                file_size_bytes=len(file_bytes),
                checksum_sha256=None,
            )
            self._db.add(document)
            await self._db.flush()

        budget = await self._create_budget_from_import(
            org_id=org_id,
            filename=filename,
            rows=rows,
            lot_id=UUID(str(matched_project["id"])),
        )

        now = datetime.now(timezone.utc)
        ingestion = Ingestion(
            document_id=document.id,
            ocr_method="manual",
            ocr_text=self._budget_rows_text(rows),
            ocr_confidence=Decimal("1.000"),
            page_count=None,
            started_at=now,
            completed_at=now,
            error_message=None,
        )
        self._db.add(ingestion)
        await self._db.flush()

        extraction = Extraction(
            ingestion_id=ingestion.id,
            model_provider="system",
            model_version="budget-import-v1",
            prompt_version="budget-import-v1",
            extracted_payload={
                "document_title": filename,
                "budget_id": str(budget.id),
                "lot_id": matched_project["id"],
                "land_agreement_id": matched_project["land_agreement_id"],
                "sale_agreement_id": matched_project["sale_agreement_id"],
                "rows_imported": len(rows),
            },
            field_confidences={},
            low_confidence_fields=[],
        )
        self._db.add(extraction)
        await self._db.commit()

        return IngestResult(
            document_id=document.id,
            status=document.status,
            extraction_summary=f"Budget import created draft budget {budget.label}",
            resource_type="budget",
            resource_id=budget.id,
        )

    async def ingest_pdf(self, *, file: UploadFile, doc_type: str) -> IngestResult:
        requested_doc_type = self._normalize_requested_doc_type(doc_type)
        filename = Path(file.filename or "document.pdf").name

        with NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            digest = hashlib.sha256()
            file_size = 0
            while chunk := await file.read(1024 * 1024):
                temp_file.write(chunk)
                digest.update(chunk)
                file_size += len(chunk)

        if file_size == 0:
            temp_path.unlink(missing_ok=True)
            raise ValueError("Uploaded PDF is empty")

        checksum = digest.hexdigest()
        minio_key = f"inbox/{uuid4()}-{filename}"

        try:
            self._upload_pdf(temp_path=temp_path, minio_key=minio_key)

            ocr_started_at = datetime.now(timezone.utc)
            ocr_result = await asyncio.to_thread(PDFExtractor().extract, temp_path)
            ocr_completed_at = datetime.now(timezone.utc)

            resolved_doc_type = (
                self._infer_doc_type(filename=filename, ocr_text=ocr_result.raw_text)
                if requested_doc_type is None
                else requested_doc_type
            )

            org_id = await self._fetch_default_org_id()
            document = Document(
                org_id=org_id,
                doc_type=resolved_doc_type,
                status=DocumentStatus.RECEIVED,
                original_filename=filename,
                minio_bucket=DOCUMENTS_BUCKET,
                minio_key=minio_key,
                file_size_bytes=file_size,
                checksum_sha256=checksum,
            )
            self._db.add(document)

            try:
                await self._db.flush()
            except IntegrityError:
                await self._db.rollback()
                document = Document(
                    org_id=org_id,
                    doc_type=resolved_doc_type,
                    status=DocumentStatus.RECEIVED,
                    original_filename=filename,
                    minio_bucket=DOCUMENTS_BUCKET,
                    minio_key=minio_key,
                    file_size_bytes=file_size,
                    checksum_sha256=None,
                )
                self._db.add(document)
                await self._db.flush()

            ingestion = Ingestion(
                document_id=document.id,
                ocr_method=self._normalize_ocr_method(ocr_result.method_used),
                ocr_text=ocr_result.raw_text,
                ocr_confidence=self._normalize_confidence(ocr_result.overall_confidence),
                page_count=ocr_result.total_pages,
                started_at=ocr_started_at,
                completed_at=ocr_completed_at,
                error_message=None,
            )
            self._db.add(ingestion)
            await self._db.flush()

            extraction_service = get_extraction_service()
            extraction_result = None
            try:
                extraction_result = await asyncio.to_thread(
                    extraction_service.extract,
                    resolved_doc_type.value,
                    ocr_result.raw_text,
                )
            except Exception as exc:
                ingestion.error_message = f"Extraction failed: {exc}"

            if extraction_result is not None:
                extraction = Extraction(
                    ingestion_id=ingestion.id,
                    model_provider=extraction_result.model_provider,
                    model_version=extraction_result.model_version,
                    prompt_version=extraction_result.prompt_version,
                    extracted_payload=extraction_result.extracted_payload,
                    field_confidences=extraction_result.field_confidences,
                    low_confidence_fields=extraction_result.low_confidence_fields,
                )
                self._db.add(extraction)

            document.status = DocumentStatus.IN_REVIEW
            await self._db.commit()

            extraction_summary = (
                self._build_summary(
                    doc_type=resolved_doc_type,
                    payload=extraction_result.extracted_payload,
                )
                if extraction_result is not None
                else "Document received; extraction failed"
            )

            return IngestResult(
                document_id=document.id,
                status=document.status,
                extraction_summary=extraction_summary,
            )
        finally:
            await file.close()
            temp_path.unlink(missing_ok=True)

    async def stage_pdf(self, *, file: UploadFile, doc_type: str) -> IngestResult:
        """Store an uploaded PDF and commit its staging record before extraction."""
        requested_doc_type = self._normalize_requested_doc_type(doc_type)
        filename = Path(file.filename or "document.pdf").name
        file_bytes = await file.read()
        await file.close()
        if not file_bytes:
            raise ValueError("Uploaded PDF is empty")

        resolved_doc_type = requested_doc_type or self._infer_doc_type(
            filename=filename,
            ocr_text="",
        )
        checksum = hashlib.sha256(file_bytes).hexdigest()
        minio_key = f"inbox/{uuid4()}-{filename}"
        self._upload_bytes(
            file_bytes=file_bytes,
            minio_key=minio_key,
            content_type="application/pdf",
        )

        org_id = await self._fetch_default_org_id()
        document = Document(
            org_id=org_id,
            doc_type=resolved_doc_type,
            status=DocumentStatus.RECEIVED,
            original_filename=filename,
            minio_bucket=DOCUMENTS_BUCKET,
            minio_key=minio_key,
            file_size_bytes=len(file_bytes),
            checksum_sha256=checksum,
        )
        self._db.add(document)
        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            document = Document(
                org_id=org_id,
                doc_type=resolved_doc_type,
                status=DocumentStatus.RECEIVED,
                original_filename=filename,
                minio_bucket=DOCUMENTS_BUCKET,
                minio_key=minio_key,
                file_size_bytes=len(file_bytes),
                checksum_sha256=None,
            )
            self._db.add(document)
            await self._db.commit()
        await self._db.refresh(document)

        return IngestResult(
            document_id=document.id,
            status=document.status,
            extraction_summary="Document received; extraction in progress",
        )

    @staticmethod
    async def process_staged_pdf(document_id: UUID) -> None:
        """OCR and extract a staged PDF using a session independent of the request."""
        async with AsyncSessionLocal() as db:
            service = IngestService(db)
            document = await db.get(Document, document_id)
            if document is None:
                logger.error("Staged document %s disappeared before extraction", document_id)
                return

            with NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
            started_at = datetime.now(timezone.utc)
            try:
                service._download_pdf(
                    temp_path=temp_path,
                    bucket=document.minio_bucket,
                    minio_key=document.minio_key,
                )
                ocr_result = await asyncio.to_thread(PDFExtractor().extract, temp_path)
                ingestion = Ingestion(
                    document_id=document.id,
                    ocr_method=service._normalize_ocr_method(ocr_result.method_used),
                    ocr_text=ocr_result.raw_text,
                    ocr_confidence=service._normalize_confidence(ocr_result.overall_confidence),
                    page_count=ocr_result.total_pages,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message=None,
                )
                db.add(ingestion)
                await db.flush()

                try:
                    extraction_result = await asyncio.to_thread(
                        get_extraction_service().extract,
                        document.doc_type.value,
                        ocr_result.raw_text,
                    )
                except Exception as exc:
                    ingestion.error_message = f"Extraction failed: {exc}"
                else:
                    db.add(
                        Extraction(
                            ingestion_id=ingestion.id,
                            model_provider=extraction_result.model_provider,
                            model_version=extraction_result.model_version,
                            prompt_version=extraction_result.prompt_version,
                            extracted_payload=extraction_result.extracted_payload,
                            field_confidences=extraction_result.field_confidences,
                            low_confidence_fields=extraction_result.low_confidence_fields,
                        )
                    )
                document.status = DocumentStatus.IN_REVIEW
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.exception("Background extraction failed for document %s", document_id)
                document = await db.get(Document, document_id)
                if document is not None:
                    db.add(
                        Ingestion(
                            document_id=document.id,
                            ocr_method="manual",
                            ocr_text=None,
                            ocr_confidence=None,
                            page_count=None,
                            started_at=started_at,
                            completed_at=datetime.now(timezone.utc),
                            error_message=f"Ingestion failed: {exc}",
                        )
                    )
                    await db.commit()
            finally:
                temp_path.unlink(missing_ok=True)

    def _upload_bytes(self, *, file_bytes: bytes, minio_key: str, content_type: str) -> None:
        s3_client = self._s3_client()
        self._ensure_documents_bucket(s3_client)

        try:
            s3_client.put_object(
                Bucket=DOCUMENTS_BUCKET,
                Key=minio_key,
                Body=file_bytes,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError("Failed to upload file to MinIO") from exc

    def _upload_pdf(self, *, temp_path: Path, minio_key: str) -> None:
        s3_client = self._s3_client()
        self._ensure_documents_bucket(s3_client)

        try:
            s3_client.upload_file(
                str(temp_path),
                DOCUMENTS_BUCKET,
                minio_key,
                ExtraArgs={"ContentType": "application/pdf"},
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError("Failed to upload PDF to MinIO") from exc

    def _download_pdf(self, *, temp_path: Path, bucket: str, minio_key: str) -> None:
        try:
            self._s3_client().download_file(bucket, minio_key, str(temp_path))
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError("Failed to download PDF from MinIO") from exc

    def _s3_client(self):
        return boto3.client(
            "s3",
            endpoint_url=settings.minio_url,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _ensure_documents_bucket(self, s3_client) -> None:
        try:
            s3_client.head_bucket(Bucket=DOCUMENTS_BUCKET)
        except ClientError:
            s3_client.create_bucket(Bucket=DOCUMENTS_BUCKET)

    async def _fetch_default_org_id(self) -> UUID:
        org_id = await self._db.scalar(select(Org.id).order_by(Org.created_at.asc()).limit(1))
        if org_id is None:
            raise RuntimeError("No core.orgs record exists for document ingestion")
        return org_id

    def _normalize_requested_doc_type(self, doc_type: str) -> DocType | None:
        if doc_type == "auto":
            return None
        try:
            return DocType(doc_type)
        except ValueError as exc:
            raise ValueError("doc_type must be one of: auto, land_otp, sale_otp") from exc

    async def _create_budget_from_import(
        self,
        *,
        org_id: UUID,
        filename: str,
        rows: list[list[str]],
        lot_id: UUID,
    ) -> Budget:
        fiscal_year = current_fiscal_year()
        next_project_number = await self._next_import_project_number(org_id, fiscal_year)
        budget = Budget(
            org_id=org_id,
            lot_agreement_id=lot_id,
            label=Path(filename).stem,
            status="draft",
            fiscal_year=fiscal_year,
            project_number=next_project_number,
            notes=f"Imported from {filename}",
        )
        self._db.add(budget)
        await self._db.flush()

        categories = (
            await self._db.execute(
                select(CostCategory)
                .where(CostCategory.is_active == True)
                .order_by(CostCategory.sort_order)
            )
        ).scalars().all()
        imported_amounts = self._extract_budget_amounts(rows)
        for category in categories:
            amount = imported_amounts.get(category.po_number, Decimal("0"))
            self._db.add(
                BudgetLine(
                    budget_id=budget.id,
                    cost_category_id=category.id,
                    estimate=amount,
                    actual=Decimal("0"),
                    origin_of_number="import",
                )
            )
        return budget

    async def _next_import_project_number(self, org_id: UUID, fiscal_year: int) -> int:
        max_project_number = await self._db.scalar(
            select(Budget.project_number)
            .where(Budget.org_id == org_id, Budget.fiscal_year == fiscal_year)
            .order_by(Budget.project_number.desc())
            .limit(1)
        )
        return (max_project_number or 0) + 1

    async def _resolve_budget_project(
        self,
        *,
        org_id: UUID,
        filename: str,
        rows: list[list[str]],
        matched_lot_id: UUID | None,
    ) -> dict[str, str | None]:
        search_text = self._budget_project_search_text(filename=filename, rows=rows)
        projects = await self._fetch_budget_project_candidates(org_id=org_id, search_text=search_text)

        if matched_lot_id is not None:
            selected = await self._fetch_budget_project_by_lot_id(org_id=org_id, lot_id=matched_lot_id)
            if selected is None:
                raise BudgetProjectMatchRequired(
                    code="budget_project_match_required",
                    message="Selected project was not found. Add the Land OTP and Sale OTP before importing this budget.",
                    search_text=search_text,
                    candidates=projects,
                )
            self._validate_budget_project(selected=selected, search_text=search_text, candidates=projects)
            return selected

        exact_matches = [
            project for project in projects
            if self._normalize_match_text(project["address"] or "") in self._normalize_match_text(search_text)
        ]
        if len(exact_matches) == 1:
            self._validate_budget_project(selected=exact_matches[0], search_text=search_text, candidates=projects)
            return exact_matches[0]

        raise BudgetProjectMatchRequired(
            code="budget_project_match_required",
            message=(
                "Budget import needs a matching Project. If the Project is missing, import and approve "
                "the Land OTP and Sale OTP first."
            ),
            search_text=search_text,
            candidates=projects,
        )

    def _validate_budget_project(
        self,
        *,
        selected: dict[str, str | None],
        search_text: str,
        candidates: list[dict[str, str | None]],
    ) -> None:
        if not selected.get("land_agreement_id"):
            raise BudgetProjectMatchRequired(
                code="budget_land_otp_required",
                message="This lot is missing its Land OTP. Import and approve the Land OTP before adding the budget.",
                search_text=search_text,
                candidates=candidates,
            )
        if not selected.get("sale_agreement_id"):
            raise BudgetProjectMatchRequired(
                code="budget_sale_otp_required",
                message="This lot is missing its Sale OTP. Import and approve the Sale OTP before adding the budget.",
                search_text=search_text,
                candidates=candidates,
            )

    async def _fetch_budget_project_candidates(
        self,
        *,
        org_id: UUID,
        search_text: str,
    ) -> list[dict[str, str | None]]:
        rows = (
            await self._db.execute(
                text("""
                    SELECT
                        l.id::text AS id,
                        COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
                        l.lot_number::text AS lot_number,
                        COALESCE(d.name, d.municipality, 'Unknown Community') AS community,
                        lt.agreement_id::text AS land_agreement_id,
                        sa.id::text AS sale_agreement_id
                    FROM core.lots l
                    JOIN core.developments d ON d.id = l.development_id
                    LEFT JOIN LATERAL (
                        SELECT agreement_id
                        FROM land.lot_terms
                        WHERE lot_id = l.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) lt ON true
                    LEFT JOIN LATERAL (
                        SELECT id
                        FROM sales.agreements
                        WHERE lot_id = l.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) sa ON true
                    WHERE d.org_id = :org_id
                    ORDER BY l.created_at DESC
                    LIMIT 250
                """),
                {"org_id": str(org_id)},
            )
        ).mappings().all()

        normalized_search = self._normalize_match_text(search_text)
        scored: list[tuple[int, dict[str, str | None]]] = []
        for row in rows:
            candidate = {
                "id": row["id"],
                "address": row["address"],
                "lot_number": row["lot_number"],
                "community": row["community"],
                "land_agreement_id": row["land_agreement_id"],
                "sale_agreement_id": row["sale_agreement_id"],
            }
            score = self._project_match_score(candidate=candidate, normalized_search=normalized_search)
            if score > 0:
                scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in scored[:8]]

    async def _fetch_budget_project_by_lot_id(
        self,
        *,
        org_id: UUID,
        lot_id: UUID,
    ) -> dict[str, str | None] | None:
        row = (
            await self._db.execute(
                text("""
                    SELECT
                        l.id::text AS id,
                        COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
                        l.lot_number::text AS lot_number,
                        COALESCE(d.name, d.municipality, 'Unknown Community') AS community,
                        lt.agreement_id::text AS land_agreement_id,
                        sa.id::text AS sale_agreement_id
                    FROM core.lots l
                    JOIN core.developments d ON d.id = l.development_id
                    LEFT JOIN LATERAL (
                        SELECT agreement_id
                        FROM land.lot_terms
                        WHERE lot_id = l.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) lt ON true
                    LEFT JOIN LATERAL (
                        SELECT id
                        FROM sales.agreements
                        WHERE lot_id = l.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) sa ON true
                    WHERE d.org_id = :org_id
                      AND l.id = :lot_id
                """),
                {"org_id": str(org_id), "lot_id": str(lot_id)},
            )
        ).mappings().first()
        if row is None:
            return None
        return {
            "id": row["id"],
            "address": row["address"],
            "lot_number": row["lot_number"],
            "community": row["community"],
            "land_agreement_id": row["land_agreement_id"],
            "sale_agreement_id": row["sale_agreement_id"],
        }

    def _budget_project_search_text(self, *, filename: str, rows: list[list[str]]) -> str:
        first_rows = " ".join(" ".join(row) for row in rows[:12])
        return f"{Path(filename).stem} {first_rows}"

    def _project_match_score(self, *, candidate: dict[str, str | None], normalized_search: str) -> int:
        score = 0
        address = self._normalize_match_text(candidate["address"] or "")
        lot_number = self._normalize_match_text(candidate["lot_number"] or "")
        community = self._normalize_match_text(candidate["community"] or "")
        if address and address in normalized_search:
            score += 100
        if lot_number and f" {lot_number} " in f" {normalized_search} ":
            score += 25
        if community and community in normalized_search:
            score += 10
        if score > 0 and candidate.get("sale_agreement_id"):
            score += 5
        if score > 0 and candidate.get("land_agreement_id"):
            score += 5
        return score

    def _normalize_match_text(self, value: str) -> str:
        return " ".join(
            "".join(character.lower() if character.isalnum() else " " for character in value).split()
        )

    def _parse_budget_rows(self, *, file_bytes: bytes, suffix: str) -> list[list[str]]:
        if suffix == ".csv":
            text = file_bytes.decode("utf-8-sig")
            return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text)) if any(row)]
        if suffix == ".xlsx":
            return self._parse_xlsx_rows(file_bytes)
        raise ValueError("Budget imports must be .csv or .xlsx files")

    def _parse_xlsx_rows(self, file_bytes: bytes) -> list[list[str]]:
        with ZipFile(io.BytesIO(file_bytes)) as workbook:
            shared_strings = self._read_xlsx_shared_strings(workbook)
            sheet_name = self._first_xlsx_sheet_name(workbook)
            sheet_xml = workbook.read(sheet_name)

        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ET.fromstring(sheet_xml)
        rows: list[list[str]] = []
        for row_node in root.findall(".//x:sheetData/x:row", namespace):
            row: list[str] = []
            for cell in row_node.findall("x:c", namespace):
                value = self._xlsx_cell_value(cell, shared_strings, namespace)
                row.append(value.strip())
            if any(row):
                rows.append(row)
        return rows

    def _read_xlsx_shared_strings(self, workbook: ZipFile) -> list[str]:
        try:
            shared_xml = workbook.read("xl/sharedStrings.xml")
        except KeyError:
            return []
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ET.fromstring(shared_xml)
        strings: list[str] = []
        for item in root.findall("x:si", namespace):
            parts = [node.text or "" for node in item.findall(".//x:t", namespace)]
            strings.append("".join(parts))
        return strings

    def _first_xlsx_sheet_name(self, workbook: ZipFile) -> str:
        sheet_names = sorted(
            name for name in workbook.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheet_names:
            raise ValueError("XLSX file does not contain a worksheet")
        return sheet_names[0]

    def _xlsx_cell_value(
        self,
        cell: ET.Element,
        shared_strings: list[str],
        namespace: dict[str, str],
    ) -> str:
        value_node = cell.find("x:v", namespace)
        if value_node is None or value_node.text is None:
            inline_text = cell.find(".//x:t", namespace)
            return inline_text.text if inline_text is not None and inline_text.text else ""
        if cell.get("t") == "s":
            try:
                return shared_strings[int(value_node.text)]
            except (ValueError, IndexError):
                return ""
        return value_node.text

    def _extract_budget_amounts(self, rows: list[list[str]]) -> dict[str, Decimal]:
        amounts: dict[str, Decimal] = {}
        for row in rows:
            code = next((cell.strip() for cell in row if cell.strip().isdigit() and len(cell.strip()) == 4), "")
            if not code:
                continue
            amount = None
            for cell in reversed(row):
                parsed_amount = self._parse_money(cell)
                if parsed_amount is not None:
                    amount = parsed_amount
                    break
            if amount is not None:
                amounts[code] = amount
        return amounts

    def _parse_money(self, value: str) -> Decimal | None:
        cleaned = value.replace("$", "").replace(",", "").strip()
        if not cleaned:
            return None
        try:
            return Decimal(cleaned).quantize(Decimal("0.01"))
        except Exception:
            return None

    def _budget_rows_text(self, rows: list[list[str]]) -> str:
        return "\n".join(",".join(row) for row in rows)

    def _content_type_for_suffix(self, suffix: str) -> str:
        if suffix == ".csv":
            return "text/csv"
        if suffix == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/octet-stream"

    def _infer_doc_type(self, *, filename: str, ocr_text: str) -> DocType:
        filename_searchable = filename.lower()
        searchable = f"{filename}\n{ocr_text}".lower()
        first_pages = "\n".join(ocr_text.split("--- PAGE ")[:4]).lower()

        if self._contains_sale_otp_label(filename_searchable):
            return DocType.SALE_OTP
        if self._contains_land_otp_label(filename_searchable):
            return DocType.LAND_OTP
        if (
            "standard offer to purchase" in first_pages
            and "seller/builder" in first_pages
            and "estimated occupancy" in first_pages
        ):
            return DocType.SALE_OTP

        sale_signals = [
            "otp sale",
            "otp (sale",
            "otp (sale)",
            "offer to purchase",
            "offer to purchase and sale",
            "standard offer to purchase",
            "seller/builder",
            "estimated occupancy",
            "possession date",
            "purchase price total",
            "builder agreement",
            "standard specifications",
            "schedule c",
            "schedule d",
            "new home",
            "buyer",
            "purchaser",
            "house plan",
        ]
        land_signals = [
            "otp land",
            "otp (land",
            "otp (land)",
            "option to purchase land",
            "land purchase",
            "vendor take-back",
            "development lands",
            "lot schedule",
        ]

        sale_score = sum(1 for signal in sale_signals if signal in searchable)
        land_score = sum(1 for signal in land_signals if signal in searchable)
        return DocType.SALE_OTP if sale_score > land_score else DocType.LAND_OTP

    def _contains_sale_otp_label(self, text: str) -> bool:
        return any(
            label in text
            for label in (
                "otp sale",
                "otp (sale",
                "otp-sale",
                "otp_sale",
                "otp(sale",
            )
        )

    def _contains_land_otp_label(self, text: str) -> bool:
        return any(
            label in text
            for label in (
                "otp land",
                "otp (land",
                "otp-land",
                "otp_land",
                "otp(land",
            )
        )

    def _normalize_ocr_method(self, method: str) -> str:
        if method in {"pdfplumber", "tesseract", "manual"}:
            return method
        if method == "mixed":
            return "tesseract"
        raise ValueError(f"Unsupported OCR method for documents.ingestions: {method}")

    def _normalize_confidence(self, value: float) -> Decimal:
        return Decimal(f"{value:.3f}")

    def _build_summary(self, *, doc_type: DocType, payload: dict[str, Any]) -> str:
        if doc_type == DocType.LAND_OTP:
            agreement = payload.get("agreement") if isinstance(payload.get("agreement"), dict) else {}
            return self._join_summary_parts(
                agreement.get("development_name") or payload.get("development_name"),
                agreement.get("municipality") or payload.get("municipality"),
            )

        if doc_type == DocType.SALE_OTP:
            agreement = payload.get("agreement") if isinstance(payload.get("agreement"), dict) else {}
            return self._join_summary_parts(
                agreement.get("civic_address"),
                self._format_money(agreement.get("purchase_price_total")),
                agreement.get("estimated_occupancy_date"),
            )

        return str(payload.get("document_title") or "Document received")

    def _join_summary_parts(self, *parts: Any) -> str:
        summary_parts = [str(part) for part in parts if part not in (None, "")]
        return " · ".join(summary_parts) if summary_parts else "Document received"

    def _format_money(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        try:
            amount = Decimal(str(value))
        except Exception:
            return str(value)
        return f"${amount:,.0f}"
