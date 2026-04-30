"""
costbook/models.py
SQLAlchemy models for the costbook schema.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime,
    Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CostCategory(Base):
    __tablename__ = "cost_categories"
    __table_args__ = {"schema": "costbook"}

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_number     = Column(String(10), nullable=False, unique=True)
    section       = Column(String(100), nullable=False)
    description   = Column(Text, nullable=False)
    formula_notes = Column(Text)
    sort_order    = Column(Integer, nullable=False, default=0)
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    budget_lines  = relationship("BudgetLine", back_populates="cost_category")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = {"schema": "costbook"}

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id            = Column(UUID(as_uuid=True), nullable=False)
    lot_agreement_id  = Column(UUID(as_uuid=True))          # → land.agreements
    label             = Column(String(200), nullable=False)
    status            = Column(String(20), nullable=False, default="draft")
    fiscal_year       = Column(Integer)
    project_number    = Column(Integer)
    sqft_main_floor   = Column(Numeric(10, 2))
    sqft_basement     = Column(Numeric(10, 2))
    sqft_garage       = Column(Numeric(10, 2))
    notes             = Column(Text)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lines             = relationship("BudgetLine", back_populates="budget", cascade="all, delete-orphan")
    purchase_orders   = relationship("PurchaseOrder", back_populates="budget")
    invoices          = relationship("Invoice", back_populates="budget")


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    __table_args__ = (
        UniqueConstraint("budget_id", "cost_category_id", name="uq_budget_line"),
        {"schema": "costbook"},
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id         = Column(UUID(as_uuid=True), ForeignKey("costbook.budgets.id", ondelete="CASCADE"), nullable=False)
    cost_category_id  = Column(UUID(as_uuid=True), ForeignKey("costbook.cost_categories.id"), nullable=False)
    estimate          = Column(Numeric(12, 2), nullable=False, default=0)
    actual            = Column(Numeric(12, 2), nullable=False, default=0)
    # variance is a generated column in Postgres — read-only from ORM
    origin_of_number  = Column(Text)
    notes             = Column(Text)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    budget            = relationship("Budget", back_populates="lines")
    cost_category     = relationship("CostCategory", back_populates="budget_lines")
    purchase_orders   = relationship("PurchaseOrder", back_populates="budget_line")


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = {"schema": "costbook"}

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id          = Column(UUID(as_uuid=True), nullable=False)
    name            = Column(String(200), nullable=False)
    trade_category  = Column(String(100))
    contact_name    = Column(String(200))
    phone           = Column(String(50))
    email           = Column(String(200))
    notes           = Column(Text)
    is_active       = Column(Boolean, nullable=False, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    purchase_orders = relationship("PurchaseOrder", back_populates="vendor")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "vendor_id IS NOT NULL OR vendor_name_adhoc IS NOT NULL",
            name="ck_po_vendor_required",
        ),
        {"schema": "costbook"},
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id            = Column(UUID(as_uuid=True), nullable=False)
    po_number         = Column(String(20), nullable=False)       # e.g. "3130-001"
    budget_id         = Column(UUID(as_uuid=True), ForeignKey("costbook.budgets.id"), nullable=False)
    budget_line_id    = Column(UUID(as_uuid=True), ForeignKey("costbook.budget_lines.id"), nullable=False)
    vendor_id         = Column(UUID(as_uuid=True), ForeignKey("costbook.vendors.id"))
    vendor_name_adhoc = Column(String(200))
    description       = Column(Text, nullable=False)
    amount            = Column(Numeric(12, 2), nullable=False)
    status            = Column(String(20), nullable=False, default="draft")
    issued_at         = Column(DateTime(timezone=True))
    notes             = Column(Text)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    budget            = relationship("Budget", back_populates="purchase_orders")
    budget_line       = relationship("BudgetLine", back_populates="purchase_orders")
    vendor            = relationship("Vendor", back_populates="purchase_orders")
    invoices          = relationship("Invoice", back_populates="purchase_order")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = {"schema": "costbook"}

    id                      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id                  = Column(UUID(as_uuid=True), nullable=False)
    budget_id               = Column(UUID(as_uuid=True), ForeignKey("costbook.budgets.id"))
    purchase_order_id       = Column(UUID(as_uuid=True), ForeignKey("costbook.purchase_orders.id"))
    document_id             = Column(UUID(as_uuid=True))            # → documents.documents
    vendor_name             = Column(Text)
    invoice_number          = Column(Text)
    invoice_date            = Column(Date)
    amount_claimed          = Column(Numeric(12, 2))
    line_items              = Column(JSONB)
    suggested_po_number     = Column(String(10))
    extraction_confidence   = Column(Float)
    status                  = Column(String(30), nullable=False, default="pending_review")
    approved_by             = Column(UUID(as_uuid=True))
    approved_at             = Column(DateTime(timezone=True))
    rejection_reason        = Column(Text)
    notes                   = Column(Text)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    updated_at              = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    budget                  = relationship("Budget", back_populates="invoices")
    purchase_order          = relationship("PurchaseOrder", back_populates="invoices")
