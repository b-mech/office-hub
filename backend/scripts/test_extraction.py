from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv


PDF_PATH = Path("/Users/nicholastenszen/Documents/1D - OTP (Land) - 185 Woodland Way.pdf")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

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
    parser.add_argument("document_id", type=UUID)
    return parser.parse_args()


def normalize_confidence(value: float) -> Decimal:
    return Decimal(f"{value:.3f}")


def normalize_ocr_method(method: str) -> str:
    if method in {"pdfplumber", "tesseract", "manual"}:
        return method
    raise ValueError(f"Unsupported OCR method for documents.ingestions: {method}")


async def run(document_id: UUID) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            document_type = await fetch_document_type(conn, document_id, for_update=True)

            ocr_started_at = datetime.now(timezone.utc)
            ocr_result = await asyncio.to_thread(PDFExtractor().extract, PDF_PATH)
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


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.document_id))


if __name__ == "__main__":
    main()
