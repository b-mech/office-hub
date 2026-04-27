from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint
from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import Numeric
from sqlalchemy import Text
from sqlalchemy import BigInteger
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.core.database import Base


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=func.gen_random_uuid(),
        server_default=func.gen_random_uuid(),
    )


class DocType(str, Enum):
    LAND_OTP = "land_otp"
    SALE_OTP = "sale_otp"
    INVOICE = "invoice"
    LEGAL = "legal"
    OTHER = "other"


class DocumentStatus(str, Enum):
    RECEIVED = "received"
    CLASSIFYING = "classifying"
    EXTRACTING = "extracting"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = _uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.orgs.id"),
        nullable=False,
    )
    doc_type: Mapped[DocType] = mapped_column(
        SqlEnum(
            DocType,
            name="doc_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SqlEnum(
            DocumentStatus,
            name="document_status",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=DocumentStatus.RECEIVED,
        server_default=text("'received'"),
    )
    original_filename: Mapped[str | None] = mapped_column(Text)
    minio_bucket: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="documents",
        server_default=text("'documents'"),
    )
    minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(Text, unique=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    received_from_email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_documents_documents_status_doc_type", "status", "doc_type"),
        {"schema": "documents"},
    )


class Ingestion(Base):
    __tablename__ = "ingestions"

    id: Mapped[UUID] = _uuid_pk()
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.documents.id"),
        nullable=False,
    )
    ocr_method: Mapped[str] = mapped_column(Text, nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    page_count: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("ocr_method IN ('pdfplumber', 'tesseract', 'manual')"),
        Index("idx_documents_ingestions_document_id", "document_id"),
        {"schema": "documents"},
    )


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[UUID] = _uuid_pk()
    ingestion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.ingestions.id"),
        nullable=False,
    )
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    field_confidences: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    low_confidence_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_documents_extractions_ingestion_id", "ingestion_id"),
        {"schema": "documents"},
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[UUID] = _uuid_pk()
    extraction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.extractions.id"),
        nullable=False,
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.users.id"),
    )
    reviewed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    edited_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    decision: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected', 'deferred')"),
        Index("idx_documents_reviews_extraction_decision", "extraction_id", "decision"),
        {"schema": "documents"},
    )


__all__ = [
    "DocType",
    "Document",
    "DocumentStatus",
    "Extraction",
    "Ingestion",
    "Review",
]
