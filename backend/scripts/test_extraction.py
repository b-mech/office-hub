from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from uuid import UUID

import asyncpg
from dotenv import load_dotenv


DEFAULT_PDF_PATH = Path("/Users/nicholastenszen/Documents/1D - OTP (Land) - 185 Woodland Way.pdf")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.extraction.service import get_extraction_service
from app.services.ocr.extractor import PDFExtractor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run OCR and extraction for a hardcoded PDF and persist the results "
            "against an existing documents.documents record."
        )
    )
    parser.add_argument("document_id", nargs="?", type=UUID)
    parser.add_argument(
        "--pdf-path",
        type=Path,
        default=DEFAULT_PDF_PATH,
        help="Local PDF path to OCR and extract.",
    )
    parser.add_argument(
        "--doc-type",
        choices=["land_otp", "sale_otp", "invoice", "legal", "other"],
        help="Document type to use when creating a new document record.",
    )
    parser.add_argument(
        "--org-id",
        type=UUID,
        help="Org ID to use when creating a new document record.",
    )
    parser.add_argument(
        "--original-filename",
        help="Optional original filename to store on a newly created document.",
    )
    return parser.parse_args()


def normalize_confidence(value: float) -> Decimal:
    return Decimal(f"{value:.3f}")


def normalize_ocr_method(method: str) -> str:
    if method in {"pdfplumber", "tesseract", "manual"}:
        return method
    if method == "mixed":
        return "tesseract"
    raise ValueError(f"Unsupported OCR method for documents.ingestions: {method}")


async def run(args: argparse.Namespace) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    database_url = normalize_database_url(database_url)

    pdf_path: Path = args.pdf_path.expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            document_id = args.document_id
            if document_id is None:
                document_id = await create_document(
                    conn=conn,
                    org_id=args.org_id,
                    doc_type=args.doc_type,
                    pdf_path=pdf_path,
                    original_filename=args.original_filename,
                )

            document_type = await fetch_document_type(conn, document_id, for_update=True)

            ocr_started_at = datetime.now(timezone.utc)
            ocr_result = await asyncio.to_thread(PDFExtractor().extract, pdf_path)
            ocr_completed_at = datetime.now(timezone.utc)

            extraction_service = get_extraction_service()
            extraction_result = await asyncio.to_thread(
                extraction_service.extract,
                document_type,
                ocr_result.raw_text,
            )

            ingestion_id = await conn.fetchval(
                """
                INSERT INTO documents.ingestions (
                    document_id,
                    ocr_method,
                    ocr_text,
                    ocr_confidence,
                    page_count,
                    started_at,
                    completed_at,
                    error_message
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                document_id,
                normalize_ocr_method(ocr_result.method_used),
                ocr_result.raw_text,
                normalize_confidence(ocr_result.overall_confidence),
                ocr_result.total_pages,
                ocr_started_at,
                ocr_completed_at,
                None,
            )

            extraction_id = await conn.fetchval(
                """
                INSERT INTO documents.extractions (
                    ingestion_id,
                    model_provider,
                    model_version,
                    prompt_version,
                    extracted_payload,
                    field_confidences,
                    low_confidence_fields
                )
                VALUES ($1, $2, $3, $4, $5::json, $6::json, $7::text[])
                RETURNING id
                """,
                ingestion_id,
                extraction_result.model_provider,
                extraction_result.model_version,
                extraction_result.prompt_version,
                json.dumps(extraction_result.extracted_payload),
                json.dumps(extraction_result.field_confidences),
                extraction_result.low_confidence_fields,
            )

            update_count = await conn.execute(
                """
                UPDATE documents.documents
                SET status = 'in_review'
                WHERE id = $1
                """,
                document_id,
            )

            if update_count != "UPDATE 1":
                raise RuntimeError(f"Document not found: {document_id}")
    finally:
        await conn.close()

    print(f"ingestion_id={ingestion_id}")
    print(f"extraction_id={extraction_id}")
    print(f"document_id={document_id}")


async def fetch_document_type(
    conn: asyncpg.Connection,
    document_id: UUID,
    *,
    for_update: bool = False,
) -> str:
    query = """
        SELECT doc_type
        FROM documents.documents
        WHERE id = $1
    """
    if for_update:
        query = f"{query} FOR UPDATE"

    row = await conn.fetchrow(query, document_id)
    if row is None:
        raise RuntimeError(f"Document not found: {document_id}")

    return str(row["doc_type"])


async def create_document(
    conn: asyncpg.Connection,
    *,
    org_id: UUID | None,
    doc_type: str | None,
    pdf_path: Path,
    original_filename: str | None,
) -> UUID:
    if org_id is None:
        raise RuntimeError("--org-id is required when document_id is omitted")
    if doc_type is None:
        raise RuntimeError("--doc-type is required when document_id is omitted")

    file_size = pdf_path.stat().st_size
    checksum = sha256_file(pdf_path)
    filename = original_filename or pdf_path.name
    minio_key = f"manual/{uuid4()}-{pdf_path.name}"

    try:
        document_id = await conn.fetchval(
            """
            INSERT INTO documents.documents (
                org_id,
                doc_type,
                status,
                original_filename,
                minio_bucket,
                minio_key,
                file_size_bytes,
                checksum_sha256
            )
            VALUES ($1, $2, 'received', $3, 'documents', $4, $5, $6)
            RETURNING id
            """,
            org_id,
            doc_type,
            filename,
            minio_key,
            file_size,
            checksum,
        )
    except asyncpg.UniqueViolationError:
        document_id = await conn.fetchval(
            """
            INSERT INTO documents.documents (
                org_id,
                doc_type,
                status,
                original_filename,
                minio_bucket,
                minio_key,
                file_size_bytes,
                checksum_sha256
            )
            VALUES ($1, $2, 'received', $3, 'documents', $4, $5, NULL)
            RETURNING id
            """,
            org_id,
            doc_type,
            filename,
            minio_key,
            file_size,
        )

    return document_id


def sha256_file(pdf_path: Path) -> str:
    digest = hashlib.sha256()
    with pdf_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return database_url


if __name__ == "__main__":
    main()
