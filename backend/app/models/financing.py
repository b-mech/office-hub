from __future__ import annotations

import uuid
from datetime import date
from datetime import datetime

from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


LENDER_TYPES = ("SCU", "PRO", "STRIDE", "RSU", "CLIENT", "OTHER")


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = {"schema": "core"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address = Column(String(255), nullable=False)
    address_normalized = Column(String(255), nullable=False, unique=True)
    canonical_address_key = Column(String(255), index=True)
    property_type = Column(String(30), nullable=False, server_default="lot")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class LenderFacility(Base):
    __tablename__ = "lender_facilities"
    __table_args__ = (
        CheckConstraint(
            "lender_type IN ('SCU','PRO','STRIDE','RSU','CLIENT','OTHER')",
            name="ck_lender_facilities_lender_type",
        ),
        {"schema": "core"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=True)
    lender_id = Column(UUID(as_uuid=True), ForeignKey("core.lenders.id", ondelete="RESTRICT"), nullable=True)
    lender_type = Column(String(20), nullable=False)
    lender = Column(String(20))
    facility_key = Column(String(100), unique=True)
    property_name = Column(String(255))
    canonical_address_key = Column(String(255), index=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="SET NULL"))
    facility_scope = Column(String(20), nullable=False, server_default="lot")
    instrument = Column(String(100))
    borrower = Column(String(255))
    annual_rate = Column(Numeric(6, 5))
    original_advance_date = Column(Date)
    original_advance_amount = Column(Numeric(14, 2))
    status = Column(String(20), nullable=False, server_default="active")
    lender_name = Column(String(100))
    total_facility = Column(Numeric(12, 2))
    opening_balance = Column(Numeric(12, 2))
    rate = Column(Numeric(7, 4))
    already_drawn = Column(Numeric(12, 2), nullable=False, default=0)
    draw_eligible_override = Column(Numeric(12, 2))
    requested_draw_amount = Column(Numeric(15, 2))
    requested_draw_as_of = Column(Date)
    commitment_source = Column(Text)
    commitment_confirmed_at = Column(DateTime(timezone=True))
    last_draw_date = Column(Date)
    last_draw_amount = Column(Numeric(12, 2))
    account_number = Column(String(50))
    account_title = Column(String(100))
    account_type = Column(String(50))
    current_balance = Column(Numeric(12, 2))
    outstanding_balance = Column(Numeric(12, 2))
    account_currency = Column(String(3))
    maturity_date = Column(Date)
    member_number = Column(String(50))
    next_interest_payment_date = Column(Date)
    next_payment_date = Column(Date)
    account_nickname = Column(String(255))
    open_date = Column(Date)
    original_loan_amount = Column(Numeric(12, 2))
    payment_schedule = Column(String(50))
    term_length_days = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class FacilityTransaction(Base):
    __tablename__ = "facility_transactions"
    __table_args__ = (
        UniqueConstraint("facility_id", "txn_date", "amount", "reference", name="uq_facility_transactions_identity"),
        {"schema": "core"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("core.lender_facilities.id", ondelete="CASCADE"), nullable=False)
    txn_date = Column(Date, nullable=False)
    txn_type = Column(String(20), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    reference = Column(Text)
    source = Column(String(20), nullable=False)
    statement_id = Column(UUID(as_uuid=True), ForeignKey("documents.lender_statements.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FacilityAlias(Base):
    __tablename__ = "facility_aliases"
    __table_args__ = {"schema": "core"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("core.lender_facilities.id", ondelete="CASCADE"), nullable=False)
    alias = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConstructionStageSync(Base):
    __tablename__ = "construction_stage_sync"
    __table_args__ = {"schema": "documents"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("core.properties.id", ondelete="SET NULL"))
    address_raw = Column(String(255), nullable=False, unique=True)
    banker_raw = Column(String(255))
    lender_type = Column(String(20))
    sold_or_spec = Column(String(10))
    stage_clean = Column(String(50))
    client_name = Column(String(255))
    build_start = Column(Date)
    possession_date = Column(Date)
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConstructionStageHistory(Base):
    __tablename__ = "construction_stage_history"
    __table_args__ = {"schema": "documents"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("core.properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_stage = Column(Text)
    new_stage = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConstructionStageMilestone(Base):
    __tablename__ = "construction_stage_milestones"
    __table_args__ = (
        UniqueConstraint(
            "property_id",
            "stage",
            "achieved_at",
            name="uq_construction_stage_milestones_event",
        ),
        {"schema": "documents"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("core.properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage = Column(String(50), nullable=False)
    achieved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source = Column(String(30), nullable=False, server_default="sheet_sync")
    confirmed_at = Column(DateTime(timezone=True))
    confirmation_note = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConstructionStageMilestoneRevision(Base):
    __tablename__ = "construction_stage_milestone_revisions"
    __table_args__ = {"schema": "documents"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    milestone_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.construction_stage_milestones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_achieved_at = Column(DateTime(timezone=True), nullable=False)
    achieved_at = Column(DateTime(timezone=True), nullable=False)
    action = Column(String(30), nullable=False)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LenderFacilityDocument(Base):
    __tablename__ = "lender_facility_documents"
    __table_args__ = {"schema": "documents"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("core.lender_facilities.id", ondelete="CASCADE"), nullable=True)
    lender_type = Column(String(20), nullable=False)
    document_type = Column(String(50), nullable=False)
    minio_bucket = Column(String(100), nullable=False)
    minio_key = Column(String(500), nullable=False)
    original_filename = Column(String(255))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    extracted_values = Column(JSONB)
    confirmed_at = Column(DateTime(timezone=True))
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    notes = Column(Text)


class LenderStatement(Base):
    __tablename__ = "lender_statements"
    __table_args__ = (
        UniqueConstraint("lender", "period", "minio_object_key", name="uq_lender_statements_object"),
        {"schema": "documents"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lender = Column(String(20), nullable=False)
    period = Column(String(7), nullable=False)
    minio_object_key = Column(Text, nullable=False)
    original_filename = Column(String(255))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    parsed_at = Column(DateTime(timezone=True))
    parse_payload = Column(JSONB)
    status = Column(String(20), nullable=False, server_default="uploaded")


class FacilityStatementSnapshot(Base):
    __tablename__ = "facility_statement_snapshots"
    __table_args__ = (
        UniqueConstraint("statement_id", "matched_property_name", name="uq_statement_snapshot_property"),
        {"schema": "documents"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    statement_id = Column(UUID(as_uuid=True), ForeignKey("documents.lender_statements.id", ondelete="CASCADE"), nullable=False)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("core.lender_facilities.id", ondelete="SET NULL"))
    matched_property_name = Column(Text, nullable=False)
    reported_period_end_date = Column(Date, nullable=False)
    reported_period_end_balance = Column(Numeric(14, 2), nullable=False)
    computed_balance = Column(Numeric(14, 2))
    delta = Column(Numeric(14, 2))
    reconciliation_status = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ClientDrawSchedule(Base):
    __tablename__ = "client_draw_schedules"
    __table_args__ = {"schema": "documents"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.documents.id", ondelete="CASCADE"), nullable=False)
    minio_object_key = Column(Text, nullable=False)
    original_filename = Column(String(255))
    purchase_price = Column(Numeric(14, 2))
    client_name = Column(Text)
    otp_date = Column(Date)
    schedule = Column(JSONB, nullable=False, default=list)
    deposits = Column(JSONB, nullable=False, default=list)
    extraction_confidence = Column(String(20), nullable=False, server_default="needs_review")
    extraction_status = Column(String(30), nullable=False, server_default="uploaded")
    extraction_notes = Column(Text)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    reviewed_at = Column(DateTime(timezone=True))
    superseded_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ClientDrawRequest(Base):
    __tablename__ = "client_draw_requests"
    __table_args__ = {"schema": "documents"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("documents.client_draw_schedules.id", ondelete="RESTRICT"), nullable=False)
    draw_items = Column(JSONB, nullable=False, default=list)
    amount = Column(Numeric(14, 2), nullable=False)
    stage_at_prep = Column(Text)
    prepared_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    prepared_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    status = Column(String(30), nullable=False, server_default="prepared")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class StageLabelAlias(Base):
    __tablename__ = "stage_label_aliases"
    __table_args__ = (
        UniqueConstraint("label_normalized", name="uq_stage_label_aliases_label_normalized"),
        {"schema": "documents"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label_raw = Column(Text, nullable=False)
    label_normalized = Column(Text, nullable=False)
    stage_key = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
