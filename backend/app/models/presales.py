from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.core.database import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=func.gen_random_uuid(),
        server_default=func.gen_random_uuid(),
    )


class ApprovalLetterStatus(str, Enum):
    REQUESTED = "requested"
    PENDING_EXTRACTION = "pending_extraction"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PresaleApprovalLetter(Base):
    __tablename__ = "presale_approval_letters"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default=ApprovalLetterStatus.REQUESTED.value)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_from: Mapped[str | None] = mapped_column(Text)
    file_key: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    email_message_id: Mapped[str | None] = mapped_column(Text)
    email_from: Mapped[str | None] = mapped_column(Text)
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_body_text: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    extraction_confidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    low_confidence_fields: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    needs_manual_entry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    quality_score: Mapped[int | None] = mapped_column(Integer)
    lender_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lender_contact_notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','pending_extraction','pending_review','approved','rejected','superseded')",
            name="ck_presale_approval_letter_status",
        ),
        CheckConstraint("quality_score IS NULL OR quality_score BETWEEN 1 AND 10", name="ck_presale_quality_score"),
        Index("idx_presale_approval_letters_lot_status", "lot_id", "status"),
        Index("idx_presale_approval_letters_review", "status", "created_at"),
        Index(
            "uq_presale_letter_lot_sha",
            "lot_id",
            "file_sha256",
            unique=True,
            postgresql_where=text("lot_id IS NOT NULL AND file_sha256 IS NOT NULL"),
        ),
        Index(
            "uq_presale_letter_unmatched_sha",
            "file_sha256",
            unique=True,
            postgresql_where=text("lot_id IS NULL AND file_sha256 IS NOT NULL"),
        ),
        {"schema": "core"},
    )


class FundingPartnerRule(Base):
    __tablename__ = "funding_partner_rules"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_funding_partner_priority"),
        CheckConstraint(
            "min_quality_score IS NULL OR min_quality_score BETWEEN 1 AND 10",
            name="ck_funding_partner_min_quality",
        ),
        {"schema": "core"},
    )

    partner_code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    required_docs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    disqualifying_conditions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    min_quality_score: Mapped[int | None] = mapped_column(Integer)
    formula: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    max_advance_rule: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    package_recipient: Mapped[str | None] = mapped_column(Text)
    package_docs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PresalePackageItem(Base):
    __tablename__ = "presale_package_items"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.documents.id", ondelete="SET NULL")
    )
    file_key: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('appraisal','stamped_plans','otp_land','otp_sale','prelim_budget')",
            name="ck_presale_package_item_type",
        ),
        Index("uq_presale_package_item_lot_type", "lot_id", "item_type", unique=True),
        {"schema": "core"},
    )


class PresaleTask(Base):
    __tablename__ = "presale_tasks"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="CASCADE")
    )
    approval_letter_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.presale_approval_letters.id", ondelete="CASCADE")
    )
    task_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open", server_default=text("'open'"))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('open','completed','cancelled')", name="ck_presale_task_status"),
        Index("idx_presale_tasks_queue", "status", "created_at"),
        Index("idx_presale_tasks_lot", "lot_id", "status"),
        {"schema": "core"},
    )


class PresaleNotification(Base):
    __tablename__ = "presale_notifications"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="CASCADE")
    )
    recipient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_presale_notifications_unread", "recipient_id", "read_at", "created_at"),
        {"schema": "core"},
    )


__all__ = [
    "ApprovalLetterStatus",
    "FundingPartnerRule",
    "PresaleApprovalLetter",
    "PresaleNotification",
    "PresalePackageItem",
    "PresaleTask",
]
