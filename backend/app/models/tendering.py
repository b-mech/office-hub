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
from sqlalchemy.dialects.postgresql import UUID
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
