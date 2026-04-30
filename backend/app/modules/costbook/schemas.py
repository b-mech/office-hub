"""
costbook/schemas.py
Pydantic request/response schemas for the costbook module.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Cost Categories
# ─────────────────────────────────────────────

class CostCategoryOut(BaseModel):
    id:            UUID
    po_number:     str
    section:       str
    description:   str
    formula_notes: Optional[str]
    sort_order:    int
    is_active:     bool

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# Budgets
# ─────────────────────────────────────────────

class BudgetCreate(BaseModel):
    label:             str
    lot_agreement_id:  Optional[UUID] = None
    sqft_main_floor:   Optional[float] = None
    sqft_basement:     Optional[float] = None
    sqft_garage:       Optional[float] = None
    notes:             Optional[str] = None


class BudgetUpdate(BaseModel):
    label:             Optional[str] = None
    lot_agreement_id:  Optional[UUID] = None
    sqft_main_floor:   Optional[float] = None
    sqft_basement:     Optional[float] = None
    sqft_garage:       Optional[float] = None
    status:            Optional[str] = None
    notes:             Optional[str] = None


class BudgetLineOut(BaseModel):
    id:                UUID
    cost_category_id:  UUID
    po_number:         str
    section:           str
    description:       str
    estimate:          float
    actual:            float
    variance:          Optional[float]   # generated column — may be None until Postgres returns it
    origin_of_number:  Optional[str]
    notes:             Optional[str]
    formula_notes:     Optional[str]

    class Config:
        from_attributes = True


class BudgetOut(BaseModel):
    id:               UUID
    org_id:           UUID
    lot_agreement_id: Optional[UUID]
    fiscal_year:      Optional[int]
    project_number:   Optional[int]
    label:            str
    status:           str
    sqft_main_floor:  Optional[float]
    sqft_basement:    Optional[float]
    sqft_garage:      Optional[float]
    notes:            Optional[str]
    created_at:       datetime
    updated_at:       datetime
    lines:            List[BudgetLineOut] = []

    # Computed totals
    total_estimate:   float = 0.0
    total_actual:     float = 0.0
    total_variance:   float = 0.0

    class Config:
        from_attributes = True


class BudgetLineUpdate(BaseModel):
    estimate:          Optional[float] = None
    actual:            Optional[float] = None
    origin_of_number:  Optional[str] = None
    notes:             Optional[str] = None


# ─────────────────────────────────────────────
# Vendors
# ─────────────────────────────────────────────

class VendorCreate(BaseModel):
    name:           str
    trade_category: Optional[str] = None
    contact_name:   Optional[str] = None
    phone:          Optional[str] = None
    email:          Optional[str] = None
    notes:          Optional[str] = None


class VendorOut(BaseModel):
    id:             UUID
    org_id:         UUID
    name:           str
    trade_category: Optional[str]
    contact_name:   Optional[str]
    phone:          Optional[str]
    email:          Optional[str]
    notes:          Optional[str]
    is_active:      bool
    created_at:     datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# Purchase Orders
# ─────────────────────────────────────────────

class PurchaseOrderCreate(BaseModel):
    budget_line_id:    UUID
    vendor_id:         Optional[UUID] = None
    vendor_name_adhoc: Optional[str] = None
    description:       str
    amount:            float
    notes:             Optional[str] = None


class PurchaseOrderStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(draft|issued|acknowledged|complete|cancelled)$")


class PurchaseOrderOut(BaseModel):
    id:                UUID
    org_id:            UUID
    po_number:         str
    budget_id:         UUID
    budget_line_id:    UUID
    vendor_id:         Optional[UUID]
    vendor_name_adhoc: Optional[str]
    vendor_name:       Optional[str]    # resolved display name
    description:       str
    amount:            float
    status:            str
    issued_at:         Optional[datetime]
    notes:             Optional[str]
    created_at:        datetime
    updated_at:        datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# Invoices
# ─────────────────────────────────────────────

class InvoiceLineItem(BaseModel):
    description: str
    quantity:    Optional[float] = None
    unit_price:  Optional[float] = None
    amount:      float


class InvoiceExtractionResult(BaseModel):
    """Returned by Claude extraction before admin review."""
    vendor_name:            Optional[str]
    invoice_number:         Optional[str]
    invoice_date:           Optional[str]
    amount_total:           Optional[float]
    line_items:             List[InvoiceLineItem] = []
    suggested_po_number:    Optional[str]
    confidence:             float


class InvoiceIngestRequest(BaseModel):
    budget_id:          Optional[UUID] = None
    purchase_order_id:  Optional[UUID] = None


class InvoiceApprove(BaseModel):
    budget_line_id: UUID        # which line to post the actual against
    notes:          Optional[str] = None


class InvoiceReject(BaseModel):
    rejection_reason: str


class InvoiceOut(BaseModel):
    id:                     UUID
    org_id:                 UUID
    budget_id:              Optional[UUID]
    purchase_order_id:      Optional[UUID]
    document_id:            Optional[UUID]
    vendor_name:            Optional[str]
    invoice_number:         Optional[str]
    invoice_date:           Optional[date]
    amount_claimed:         Optional[float]
    line_items:             Optional[List[Dict[str, Any]]]
    suggested_po_number:    Optional[str]
    extraction_confidence:  Optional[float]
    status:                 str
    approved_by:            Optional[UUID]
    approved_at:            Optional[datetime]
    rejection_reason:       Optional[str]
    notes:                  Optional[str]
    created_at:             datetime
    updated_at:             datetime

    class Config:
        from_attributes = True
