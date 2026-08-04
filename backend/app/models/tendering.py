from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


contractor_category_links = Table(
    "contractor_category_links",
    Base.metadata,
    Column("contractor_id", UUID(as_uuid=True), ForeignKey("core.contractors.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", UUID(as_uuid=True), ForeignKey("core.contractor_categories.id", ondelete="CASCADE"), primary_key=True),
    schema="core",
)


class ContractorCategory(Base):
    __tablename__ = "contractor_categories"
    __table_args__ = {"schema": "core"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)
    slug = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Contractor(Base):
    __tablename__ = "contractors"
    __table_args__ = {"schema": "core"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    contact_name = Column(Text)
    email = Column(Text)
    phone = Column(String(50))
    address = Column(Text)
    notes = Column(Text)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    categories = relationship("ContractorCategory", secondary=contractor_category_links, lazy="selectin")


class TenderPackage(Base):
    __tablename__ = "tender_packages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','sent','bids_in','compared','awarded','cancelled')",
            name="ck_tender_packages_status",
        ),
        {"schema": "core"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("core.contractor_categories.id", ondelete="RESTRICT"), nullable=False)
    scope_description = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    due_date = Column(Date)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    category = relationship("ContractorCategory", lazy="joined")
    documents = relationship("TenderDocument", lazy="selectin", cascade="all, delete-orphan")
    bids = relationship("TenderBid", lazy="selectin", cascade="all, delete-orphan")
    award = relationship("TenderAward", lazy="selectin", uselist=False, cascade="all, delete-orphan")


class TenderDocument(Base):
    __tablename__ = "tender_documents"
    __table_args__ = (
        CheckConstraint("document_type IN ('plan','markup','spec')", name="ck_tender_documents_type"),
        UniqueConstraint("tender_package_id", "file_path", name="uq_tender_documents_package_path"),
        {"schema": "documents"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_package_id = Column(UUID(as_uuid=True), ForeignKey("core.tender_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(String(20), nullable=False)
    file_path = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TenderBid(Base):
    __tablename__ = "tender_bids"
    __table_args__ = (
        CheckConstraint("status IN ('invited','received','reviewed','cancelled')", name="ck_tender_bids_status"),
        UniqueConstraint("tender_package_id", "contractor_id", name="uq_tender_bids_package_contractor"),
        {"schema": "core"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_package_id = Column(UUID(as_uuid=True), ForeignKey("core.tender_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    contractor_id = Column(UUID(as_uuid=True), ForeignKey("core.contractors.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(20), nullable=False, default="invited", server_default="invited")
    quote_amount = Column(Numeric(15, 2))
    extracted_amount = Column(Numeric(15, 2))
    extracted_line_items = Column(JSONB)
    excluded_scope_notes = Column(Text)
    reviewer_notes = Column(Text)
    invited_at = Column(DateTime(timezone=True))
    received_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    contractor = relationship("Contractor", lazy="joined")
    documents = relationship("TenderBidDocument", lazy="selectin", cascade="all, delete-orphan")


class TenderBidDocument(Base):
    __tablename__ = "tender_bid_documents"
    __table_args__ = {"schema": "documents"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_bid_id = Column(UUID(as_uuid=True), ForeignKey("core.tender_bids.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TenderAward(Base):
    __tablename__ = "tender_awards"
    __table_args__ = (UniqueConstraint("tender_package_id", name="uq_tender_awards_package"), {"schema": "core"})
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tender_package_id = Column(UUID(as_uuid=True), ForeignKey("core.tender_packages.id", ondelete="CASCADE"), nullable=False)
    winning_bid_id = Column(UUID(as_uuid=True), ForeignKey("core.tender_bids.id", ondelete="RESTRICT"), nullable=False)
    po_id = Column(UUID(as_uuid=True), ForeignKey("costbook.purchase_orders.id", ondelete="RESTRICT"), nullable=False)
    award_instructions = Column(Text, nullable=False)
    project_start_date = Column(Date, nullable=False)
    contractor_start_date = Column(Date, nullable=False)
    awarded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    purchase_order = relationship("PurchaseOrder", lazy="joined")
