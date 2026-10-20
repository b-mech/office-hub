"""Lawyer funds intake staging and review records."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _id() -> Mapped[UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True,
                         server_default=text("gen_random_uuid()"))


class FundsNotice(Base):
    __tablename__ = "funds_notices"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = _id()
    property_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.properties.id"))
    lot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.lots.id"))
    email_message_id: Mapped[str | None] = mapped_column(Text)
    email_from: Mapped[str | None] = mapped_column(Text)
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_body_text: Mapped[str | None] = mapped_column(Text)
    capture_source: Mapped[str] = mapped_column(Text, server_default="gmail_extension")
    status: Mapped[str] = mapped_column(Text, server_default="pending_extraction")
    funds_type: Mapped[str | None] = mapped_column(Text)
    law_firm: Mapped[str | None] = mapped_column(Text)
    trust_statement_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    funds_release_date: Mapped[date | None] = mapped_column(Date)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    review_flags: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundsAttachment(Base):
    __tablename__ = "funds_attachments"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = _id()
    notice_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.funds_notices.id"))
    file_sha256: Mapped[str] = mapped_column(Text, unique=True)
    file_key: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text, server_default="application/pdf")
    box_file_id: Mapped[str | None] = mapped_column(Text)
    box_file_url: Mapped[str | None] = mapped_column(Text)
    box_filing_status: Mapped[str] = mapped_column(Text, server_default="pending")
    extraction_status: Mapped[str] = mapped_column(Text, server_default="pending")
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    extraction_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundsEntry(Base):
    __tablename__ = "funds_entries"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = _id()
    notice_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.funds_notices.id"))
    attachment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.funds_attachments.id"))
    property_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.properties.id"))
    lot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.lots.id"))
    facility_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.lender_facilities.id"))
    funds_type: Mapped[str] = mapped_column(Text)
    deposit_ordinal: Mapped[int | None]
    property_address: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cheque_number: Mapped[str | None] = mapped_column(Text)
    txn_date: Mapped[date | None] = mapped_column(Date)
    payee: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)
    closing: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending_review")
    review_flags: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    matched_statement_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.lender_statements.id"))
    matched_snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.facility_statement_snapshots.id"))
    posted_transaction_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.facility_transactions.id"))
    posting_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confirmed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundsTask(Base):
    __tablename__ = "funds_tasks"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = _id()
    task_key: Mapped[str] = mapped_column(Text, unique=True)
    notice_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.funds_notices.id"))
    lot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.lots.id"))
    task_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    status: Mapped[str] = mapped_column(Text, server_default="open")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FundsBoxWatch(Base):
    __tablename__ = "funds_box_watches"
    __table_args__ = {"schema": "documents"}

    id: Mapped[UUID] = _id()
    lot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.lots.id"), unique=True)
    folder_id: Mapped[str | None] = mapped_column(Text)
    possession_date: Mapped[date] = mapped_column(Date)
    escalate_after_days: Mapped[int] = mapped_column(server_default="45")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="watching")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
