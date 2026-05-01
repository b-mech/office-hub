from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID
from uuid import uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core import Org
from app.models.documents import DocType
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion
from app.services.extraction.service import get_extraction_service
from app.services.ocr.extractor import PDFExtractor


DOCUMENTS_BUCKET = "documents"


@dataclass(slots=True)
class IngestResult:
    document_id: UUID
    status: DocumentStatus
    extraction_summary: str


class IngestService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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

    def _upload_pdf(self, *, temp_path: Path, minio_key: str) -> None:
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.minio_url,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        try:
            s3_client.head_bucket(Bucket=DOCUMENTS_BUCKET)
        except ClientError:
            s3_client.create_bucket(Bucket=DOCUMENTS_BUCKET)

        try:
            s3_client.upload_file(
                str(temp_path),
                DOCUMENTS_BUCKET,
                minio_key,
                ExtraArgs={"ContentType": "application/pdf"},
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError("Failed to upload PDF to MinIO") from exc

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

    def _infer_doc_type(self, *, filename: str, ocr_text: str) -> DocType:
        searchable = f"{filename}\n{ocr_text}".lower()
        sale_signals = [
            "estimated occupancy",
            "purchase price total",
            "standard specifications",
            "buyer",
            "house plan",
        ]
        land_signals = [
            "option to purchase land",
            "land purchase",
            "vendor take-back",
            "development lands",
            "lot schedule",
        ]

        sale_score = sum(1 for signal in sale_signals if signal in searchable)
        land_score = sum(1 for signal in land_signals if signal in searchable)
        return DocType.SALE_OTP if sale_score > land_score else DocType.LAND_OTP

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
