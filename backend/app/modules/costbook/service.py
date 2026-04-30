"""
costbook/service.py
Business logic for budgets, purchase orders, vendors, and invoices.

PO number format: YYNN-CCCC-SS
  YY   = 2-digit fiscal year end (Sept 1 – Aug 31, so Oct 2025 → 26)
  NN   = 2-digit project number, incremental within fiscal year
  CCCC = 4-digit cost code (e.g. 3130)
  SS   = 2-digit sequence within that cost code + project + fiscal year

Example: 2601-3130-01
  FY2026 · Project 01 · Framing Labor · First PO
"""
import logging
from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.costbook.models import (
    Budget, BudgetLine, CostCategory, Invoice, PurchaseOrder, Vendor,
)
from app.modules.costbook.schemas import (
    BudgetCreate, BudgetLineUpdate, BudgetUpdate,
    InvoiceApprove, InvoiceExtractionResult, InvoiceReject,
    PurchaseOrderCreate,
    VendorCreate,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Fiscal year helpers
# ─────────────────────────────────────────────

def current_fiscal_year(at: Optional[date] = None) -> int:
    """
    Return the 2-digit fiscal year end for a given date.
    Fiscal year runs Sept 1 – Aug 31.
    Sept 1 2025 – Aug 31 2026 = FY26 → returns 26.
    """
    d = at or date.today()
    full_year = d.year + 1 if d.month >= 9 else d.year
    return full_year % 100


async def _next_project_number(db: AsyncSession, org_id: UUID, fiscal_year: int) -> int:
    """
    Return the next available project number for this org + fiscal year.
    Increments from 1.
    """
    result = await db.execute(
        select(func.max(Budget.project_number))
        .where(
            Budget.org_id == org_id,
            Budget.fiscal_year == fiscal_year,
        )
    )
    current_max = result.scalar_one_or_none()
    return (current_max or 0) + 1


def _format_po_number(fiscal_year: int, project_number: int, cost_code: str, sequence: int) -> str:
    """
    Format: YYNN-CCCC-SS
    e.g. 2601-3130-01
    """
    return f"{fiscal_year:02d}{project_number:02d}-{cost_code}-{sequence:02d}"


async def _next_po_sequence(
    db: AsyncSession,
    fiscal_year: int,
    project_number: int,
    cost_code: str,
) -> int:
    """Return next sequence for FY + project + cost code."""
    prefix = f"{fiscal_year:02d}{project_number:02d}-{cost_code}-"
    result = await db.execute(
        select(PurchaseOrder.po_number)
        .where(PurchaseOrder.po_number.like(f"{prefix}%"))
        .order_by(PurchaseOrder.po_number.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    if last:
        try:
            return int(last.split("-")[-1]) + 1
        except (ValueError, IndexError):
            pass
    return 1


# ─────────────────────────────────────────────
# Cost Categories
# ─────────────────────────────────────────────

async def list_cost_categories(db: AsyncSession) -> List[CostCategory]:
    result = await db.execute(
        select(CostCategory)
        .where(CostCategory.is_active == True)
        .order_by(CostCategory.sort_order)
    )
    return result.scalars().all()


# ─────────────────────────────────────────────
# Budgets
# ─────────────────────────────────────────────

async def create_budget(
    db: AsyncSession,
    org_id: UUID,
    data: BudgetCreate,
) -> Budget:
    """
    Create a budget and auto-populate all active cost category lines.
    Assigns fiscal year and incremental project number automatically.
    """
    fy = current_fiscal_year()
    proj_num = await _next_project_number(db, org_id, fy)

    budget = Budget(
        org_id=org_id,
        lot_agreement_id=data.lot_agreement_id,
        label=data.label,
        fiscal_year=fy,
        project_number=proj_num,
        sqft_main_floor=data.sqft_main_floor,
        sqft_basement=data.sqft_basement,
        sqft_garage=data.sqft_garage,
        notes=data.notes,
    )
    db.add(budget)
    await db.flush()

    categories = await list_cost_categories(db)
    for cat in categories:
        line = BudgetLine(
            budget_id=budget.id,
            cost_category_id=cat.id,
            estimate=0,
            actual=0,
        )
        db.add(line)

    await db.commit()
    await db.refresh(budget)
    return budget


async def get_budget(db: AsyncSession, budget_id: UUID) -> Optional[Budget]:
    result = await db.execute(
        select(Budget)
        .where(Budget.id == budget_id)
        .options(
            selectinload(Budget.lines).selectinload(BudgetLine.cost_category)
        )
    )
    return result.scalar_one_or_none()


async def list_budgets(db: AsyncSession, org_id: UUID) -> List[Budget]:
    result = await db.execute(
        select(Budget)
        .where(Budget.org_id == org_id)
        .order_by(Budget.fiscal_year.desc(), Budget.project_number.asc())
    )
    return result.scalars().all()


async def update_budget(
    db: AsyncSession,
    budget: Budget,
    data: BudgetUpdate,
) -> Budget:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(budget, field, value)
    await db.commit()
    await db.refresh(budget)
    return budget


async def update_budget_line(
    db: AsyncSession,
    budget_id: UUID,
    line_id: UUID,
    data: BudgetLineUpdate,
) -> Optional[BudgetLine]:
    result = await db.execute(
        select(BudgetLine).where(
            BudgetLine.id == line_id,
            BudgetLine.budget_id == budget_id,
        )
    )
    line = result.scalar_one_or_none()
    if not line:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(line, field, value)

    await db.commit()
    await db.refresh(line)
    return line


# ─────────────────────────────────────────────
# Vendors
# ─────────────────────────────────────────────

async def create_vendor(db: AsyncSession, org_id: UUID, data: VendorCreate) -> Vendor:
    vendor = Vendor(org_id=org_id, **data.model_dump())
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)
    return vendor


async def list_vendors(
    db: AsyncSession,
    org_id: UUID,
    trade_category: Optional[str] = None,
) -> List[Vendor]:
    q = select(Vendor).where(Vendor.org_id == org_id, Vendor.is_active == True)
    if trade_category:
        q = q.where(Vendor.trade_category == trade_category)
    result = await db.execute(q.order_by(Vendor.name))
    return result.scalars().all()


async def get_vendor(db: AsyncSession, vendor_id: UUID) -> Optional[Vendor]:
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    return result.scalar_one_or_none()


# ─────────────────────────────────────────────
# Purchase Orders
# ─────────────────────────────────────────────

async def create_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    budget_id: UUID,
    data: PurchaseOrderCreate,
) -> PurchaseOrder:
    # Load budget for fiscal year + project number
    budget_result = await db.execute(select(Budget).where(Budget.id == budget_id))
    budget = budget_result.scalar_one_or_none()
    if not budget:
        raise ValueError(f"Budget {budget_id} not found")
    if not budget.fiscal_year or not budget.project_number:
        raise ValueError("Budget is missing fiscal year or project number")

    # Load budget line for cost code
    line_result = await db.execute(
        select(BudgetLine)
        .where(BudgetLine.id == data.budget_line_id)
        .options(selectinload(BudgetLine.cost_category))
    )
    line = line_result.scalar_one_or_none()
    if not line:
        raise ValueError(f"Budget line {data.budget_line_id} not found")

    cost_code = line.cost_category.po_number

    # Generate PO number
    seq = await _next_po_sequence(
        db,
        fiscal_year=budget.fiscal_year,
        project_number=budget.project_number,
        cost_code=cost_code,
    )
    po_number = _format_po_number(
        fiscal_year=budget.fiscal_year,
        project_number=budget.project_number,
        cost_code=cost_code,
        sequence=seq,
    )

    # Auto-save ad-hoc vendor
    vendor_id = data.vendor_id
    if not vendor_id and data.vendor_name_adhoc:
        existing = await db.execute(
            select(Vendor).where(
                Vendor.org_id == org_id,
                Vendor.name == data.vendor_name_adhoc,
            )
        )
        existing_vendor = existing.scalar_one_or_none()
        if existing_vendor:
            vendor_id = existing_vendor.id
        else:
            new_vendor = Vendor(
                org_id=org_id,
                name=data.vendor_name_adhoc,
                trade_category=line.cost_category.section,
            )
            db.add(new_vendor)
            await db.flush()
            vendor_id = new_vendor.id

    po = PurchaseOrder(
        org_id=org_id,
        po_number=po_number,
        budget_id=budget_id,
        budget_line_id=data.budget_line_id,
        vendor_id=vendor_id,
        vendor_name_adhoc=data.vendor_name_adhoc if not vendor_id else None,
        description=data.description,
        amount=data.amount,
        notes=data.notes,
    )
    db.add(po)
    await db.commit()
    await db.refresh(po)
    return po


async def update_po_status(db: AsyncSession, po: PurchaseOrder, status: str) -> PurchaseOrder:
    po.status = status
    if status == "issued" and not po.issued_at:
        po.issued_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(po)
    return po


async def list_purchase_orders(
    db: AsyncSession,
    org_id: UUID,
    budget_id: Optional[UUID] = None,
) -> List[PurchaseOrder]:
    q = select(PurchaseOrder).where(PurchaseOrder.org_id == org_id)
    if budget_id:
        q = q.where(PurchaseOrder.budget_id == budget_id)
    result = await db.execute(q.order_by(PurchaseOrder.po_number))
    return result.scalars().all()


async def get_purchase_order(db: AsyncSession, po_id: UUID) -> Optional[PurchaseOrder]:
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    return result.scalar_one_or_none()


# ─────────────────────────────────────────────
# Invoices
# ─────────────────────────────────────────────

async def create_invoice_from_extraction(
    db: AsyncSession,
    org_id: UUID,
    extraction: InvoiceExtractionResult,
    document_id: Optional[UUID] = None,
    budget_id: Optional[UUID] = None,
    purchase_order_id: Optional[UUID] = None,
) -> Invoice:
    invoice_date = None
    if extraction.invoice_date:
        try:
            invoice_date = date.fromisoformat(extraction.invoice_date)
        except ValueError:
            pass

    invoice = Invoice(
        org_id=org_id,
        budget_id=budget_id,
        purchase_order_id=purchase_order_id,
        document_id=document_id,
        vendor_name=extraction.vendor_name,
        invoice_number=extraction.invoice_number,
        invoice_date=invoice_date,
        amount_claimed=extraction.amount_total,
        line_items=[item.model_dump() for item in extraction.line_items],
        suggested_po_number=extraction.suggested_po_number,
        extraction_confidence=extraction.confidence,
        status="pending_review",
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def approve_invoice(
    db: AsyncSession,
    invoice: Invoice,
    data: InvoiceApprove,
    approved_by: UUID,
) -> Invoice:
    line_result = await db.execute(
        select(BudgetLine).where(BudgetLine.id == data.budget_line_id)
    )
    line = line_result.scalar_one_or_none()
    if not line:
        raise ValueError(f"Budget line {data.budget_line_id} not found")

    line.actual = float(line.actual or 0) + float(invoice.amount_claimed or 0)
    invoice.status = "approved"
    invoice.approved_by = approved_by
    invoice.approved_at = datetime.now(timezone.utc)
    invoice.notes = data.notes

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def reject_invoice(db: AsyncSession, invoice: Invoice, data: InvoiceReject) -> Invoice:
    invoice.status = "rejected"
    invoice.rejection_reason = data.rejection_reason
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def list_invoices(
    db: AsyncSession,
    org_id: UUID,
    status: Optional[str] = None,
    budget_id: Optional[UUID] = None,
) -> List[Invoice]:
    q = select(Invoice).where(Invoice.org_id == org_id)
    if status:
        q = q.where(Invoice.status == status)
    if budget_id:
        q = q.where(Invoice.budget_id == budget_id)
    result = await db.execute(q.order_by(Invoice.created_at.desc()))
    return result.scalars().all()


async def get_invoice(db: AsyncSession, invoice_id: UUID) -> Optional[Invoice]:
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    return result.scalar_one_or_none()
