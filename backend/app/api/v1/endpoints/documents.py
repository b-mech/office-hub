from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Literal
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.documents import DocType
from app.models.documents import Document
from app.models.documents import DocumentStatus
from app.models.documents import Extraction
from app.models.documents import Ingestion
from app.models.documents import Review
from app.services.promotion import PromotionService


router = APIRouter(prefix="/documents", tags=["documents"])


class ReviewCreateRequest(BaseModel):
    reviewed_payload: dict[str, Any]
    edited_fields: list[str] = Field(default_factory=list)
    decision: Literal["approved", "rejected", "deferred"]
    rejection_reason: str | None = None


@router.get("")
async def list_documents(
    status: str | None = None,
    doc_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(Document)

    if status is not None:
        try:
            query = query.where(Document.status == DocumentStatus(status))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid document status") from exc

    if doc_type is not None:
        try:
            query = query.where(Document.doc_type == DocType(doc_type))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid document type") from exc

    query = query.order_by(Document.received_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    documents = result.scalars().all()

    return [
        {
            "id": document.id,
            "doc_type": document.doc_type.value,
            "status": document.status.value,
            "original_filename": document.original_filename,
            "received_at": document.received_at,
            "received_from_email": document.received_from_email,
        }
        for document in documents
    ]


@router.get("/{document_id}")
async def get_document_detail(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    latest_ingestion = await db.scalar(
        select(Ingestion)
        .where(Ingestion.document_id == document_id)
        .order_by(Ingestion.completed_at.desc().nullslast(), Ingestion.started_at.desc().nullslast())
        .limit(1)
    )

    latest_extraction = await db.scalar(
        select(Extraction)
        .join(Ingestion, Extraction.ingestion_id == Ingestion.id)
        .where(Ingestion.document_id == document_id)
        .order_by(Extraction.created_at.desc())
        .limit(1)
    )

    return {
        "document": {
            "id": document.id,
            "org_id": document.org_id,
            "doc_type": document.doc_type.value,
            "status": document.status.value,
            "original_filename": document.original_filename,
            "minio_bucket": document.minio_bucket,
            "minio_key": document.minio_key,
            "file_size_bytes": document.file_size_bytes,
            "checksum_sha256": document.checksum_sha256,
            "received_at": document.received_at,
            "received_from_email": document.received_from_email,
        },
        "ingestion": None
        if latest_ingestion is None
        else {
            "id": latest_ingestion.id,
            "ocr_method": latest_ingestion.ocr_method,
            "ocr_confidence": latest_ingestion.ocr_confidence,
        },
        "extraction": None
        if latest_extraction is None
        else {
            "id": latest_extraction.id,
            "extracted_payload": latest_extraction.extracted_payload,
            "field_confidences": latest_extraction.field_confidences,
            "low_confidence_fields": latest_extraction.low_confidence_fields,
        },
    }


@router.get("/{document_id}/pdf")
async def get_document_pdf(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.minio_url,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

    try:
        response = s3_client.get_object(Bucket=document.minio_bucket, Key=document.minio_key)
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(status_code=404, detail="PDF file not found") from exc

    body = response["Body"]

    def stream_file():
        try:
            while chunk := body.read(8192):
                yield chunk
        finally:
            body.close()

    return StreamingResponse(
        stream_file(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="{document.original_filename or f"{document_id}.pdf"}"'
            )
        },
    )


@router.post("/{document_id}/review")
async def create_document_review(
    document_id: UUID,
    review_request: ReviewCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    latest_extraction = await db.scalar(
        select(Extraction)
        .join(Ingestion, Extraction.ingestion_id == Ingestion.id)
        .where(Ingestion.document_id == document_id)
        .order_by(Extraction.created_at.desc())
        .limit(1)
    )
    if latest_extraction is None:
        raise HTTPException(status_code=404, detail="No extraction found for document")

    review = Review(
        extraction_id=latest_extraction.id,
        reviewed_payload=review_request.reviewed_payload,
        edited_fields=review_request.edited_fields,
        decision=review_request.decision,
        rejection_reason=review_request.rejection_reason,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(review)
    await db.flush()

    if review_request.decision == "approved":
        try:
            promotion_result = await PromotionService(db).promote(review.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": review.id,
            "decision": review_request.decision,
            "promotion": {
                "agreement_id": promotion_result.agreement_id,
                "lots_created": promotion_result.lots_created,
                "lots_matched": promotion_result.lots_matched,
                "promoted_at": promotion_result.promoted_at,
            },
        }

    if review_request.decision == "rejected":
        document.status = DocumentStatus.REJECTED
    else:
        document.status = DocumentStatus.IN_REVIEW

    await db.commit()
    return {"id": review.id, "decision": review_request.decision}
