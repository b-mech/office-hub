"""
API routes for the costbook module.
"""
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.costbook import extraction, service
from app.modules.costbook.models import Budget, BudgetLine, Invoice, PurchaseOrder
from app.modules.costbook.schemas import (
    BudgetCreate,
    BudgetLineOut,
    BudgetLineUpdate,
    BudgetOut,
    BudgetUpdate,
    CostCategoryOut,
    InvoiceApprove,
    InvoiceOut,
    InvoiceReject,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderStatusUpdate,
    VendorCreate,
    VendorOut,
)

router = APIRouter(prefix="/api/v1/costbook", tags=["costbook"])

DEFAULT_ORG_ID = UUID("ed83acdb-7a3a-4999-b5b0-4d41ee24a99d")
DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000000")


def _num(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _budget_line_out(line: BudgetLine) -> BudgetLineOut:
    category = line.cost_category
    estimate = _num(line.estimate)
    actual = _num(line.actual)
    return BudgetLineOut(
        id=line.id,
        cost_category_id=line.cost_category_id,
        po_number=category.po_number if category else "",
        section=category.section if category else "",
        description=category.description if category else "",
        estimate=estimate,
        actual=actual,
        variance=actual - estimate,
        origin_of_number=line.origin_of_number,
        notes=line.notes,
        formula_notes=category.formula_notes if category else None,
    )


def _budget_out(budget: Budget) -> BudgetOut:
    lines = [_budget_line_out(line) for line in budget.lines]
    total_estimate = sum(line.estimate for line in lines)
    total_actual = sum(line.actual for line in lines)
    return BudgetOut(
        id=budget.id,
        org_id=budget.org_id,
        lot_agreement_id=budget.lot_agreement_id,
        fiscal_year=budget.fiscal_year,
        project_number=budget.project_number,
        label=budget.label,
        status=budget.status,
        sqft_main_floor=budget.sqft_main_floor,
        sqft_basement=budget.sqft_basement,
        sqft_garage=budget.sqft_garage,
        notes=budget.notes,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
        lines=lines,
        total_estimate=total_estimate,
        total_actual=total_actual,
        total_variance=total_actual - total_estimate,
    )


def _purchase_order_out(po: PurchaseOrder) -> PurchaseOrderOut:
    return PurchaseOrderOut(
        id=po.id,
        org_id=po.org_id,
        po_number=po.po_number,
        budget_id=po.budget_id,
        budget_line_id=po.budget_line_id,
        vendor_id=po.vendor_id,
        vendor_name_adhoc=po.vendor_name_adhoc,
        vendor_name=po.vendor_name_adhoc,
        description=po.description,
        amount=po.amount,
        status=po.status,
        issued_at=po.issued_at,
        notes=po.notes,
        created_at=po.created_at,
        updated_at=po.updated_at,
    )


def _invoice_out(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut.model_validate(invoice)


@router.get("/cost-categories", response_model=List[CostCategoryOut])
async def list_cost_categories(db: AsyncSession = Depends(get_db)) -> List[CostCategoryOut]:
    return await service.list_cost_categories(db)


@router.get("/budgets", response_model=List[BudgetOut])
async def list_budgets(db: AsyncSession = Depends(get_db)) -> List[BudgetOut]:
    budgets = await service.list_budgets(db, DEFAULT_ORG_ID)
    return [_budget_out(budget) for budget in budgets]


@router.post("/budgets", response_model=BudgetOut)
async def create_budget(
    data: BudgetCreate,
    db: AsyncSession = Depends(get_db),
) -> BudgetOut:
    budget = await service.create_budget(db, DEFAULT_ORG_ID, data)
    reloaded = await service.get_budget(db, budget.id)
    if not reloaded:
        raise HTTPException(status_code=404, detail="Budget not found")
    return _budget_out(reloaded)


@router.get("/budgets/{budget_id}", response_model=BudgetOut)
async def get_budget(
    budget_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> BudgetOut:
    budget = await service.get_budget(db, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return _budget_out(budget)


@router.patch("/budgets/{budget_id}", response_model=BudgetOut)
async def update_budget(
    budget_id: UUID,
    data: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
) -> BudgetOut:
    budget = await service.get_budget(db, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    updated = await service.update_budget(db, budget, data)
    reloaded = await service.get_budget(db, updated.id)
    if not reloaded:
        raise HTTPException(status_code=404, detail="Budget not found")
    return _budget_out(reloaded)


@router.patch("/budgets/{budget_id}/lines/{line_id}", response_model=BudgetLineOut)
async def update_budget_line(
    budget_id: UUID,
    line_id: UUID,
    data: BudgetLineUpdate,
    db: AsyncSession = Depends(get_db),
) -> BudgetLineOut:
    line = await service.update_budget_line(db, budget_id, line_id, data)
    if not line:
        raise HTTPException(status_code=404, detail="Budget line not found")
    budget = await service.get_budget(db, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    reloaded = next((item for item in budget.lines if item.id == line_id), None)
    if not reloaded:
        raise HTTPException(status_code=404, detail="Budget line not found")
    return _budget_line_out(reloaded)


@router.get("/vendors", response_model=List[VendorOut])
async def list_vendors(
    trade_category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> List[VendorOut]:
    return await service.list_vendors(db, DEFAULT_ORG_ID, trade_category)


@router.post("/vendors", response_model=VendorOut)
async def create_vendor(
    data: VendorCreate,
    db: AsyncSession = Depends(get_db),
) -> VendorOut:
    return await service.create_vendor(db, DEFAULT_ORG_ID, data)


@router.get("/budgets/{budget_id}/purchase-orders", response_model=List[PurchaseOrderOut])
async def list_purchase_orders(
    budget_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> List[PurchaseOrderOut]:
    purchase_orders = await service.list_purchase_orders(db, DEFAULT_ORG_ID, budget_id)
    return [_purchase_order_out(po) for po in purchase_orders]


@router.post("/budgets/{budget_id}/purchase-orders", response_model=PurchaseOrderOut)
async def create_purchase_order(
    budget_id: UUID,
    data: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderOut:
    try:
        po = await service.create_purchase_order(db, DEFAULT_ORG_ID, budget_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _purchase_order_out(po)


@router.patch("/purchase-orders/{po_id}/status", response_model=PurchaseOrderOut)
async def update_purchase_order_status(
    po_id: UUID,
    data: PurchaseOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderOut:
    po = await service.get_purchase_order(db, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    updated = await service.update_po_status(db, po, data.status)
    return _purchase_order_out(updated)


@router.get("/invoices", response_model=List[InvoiceOut])
async def list_invoices(
    status: Optional[str] = None,
    budget_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
) -> List[InvoiceOut]:
    invoices = await service.list_invoices(db, DEFAULT_ORG_ID, status, budget_id)
    return [_invoice_out(invoice) for invoice in invoices]


@router.post("/invoices/ingest", response_model=InvoiceOut)
async def ingest_invoice(
    file: UploadFile = File(...),
    budget_id: Optional[UUID] = Form(default=None),
    purchase_order_id: Optional[UUID] = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> InvoiceOut:
    file_bytes = await file.read()
    try:
        extracted = await extraction.extract_invoice(file_bytes, file.filename or "invoice")
        invoice = await service.create_invoice_from_extraction(
            db,
            DEFAULT_ORG_ID,
            extracted,
            budget_id=budget_id,
            purchase_order_id=purchase_order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _invoice_out(invoice)


@router.post("/invoices/{invoice_id}/approve", response_model=InvoiceOut)
async def approve_invoice(
    invoice_id: UUID,
    data: InvoiceApprove,
    db: AsyncSession = Depends(get_db),
) -> InvoiceOut:
    invoice = await service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    try:
        approved = await service.approve_invoice(db, invoice, data, DEFAULT_USER_ID)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _invoice_out(approved)


@router.post("/invoices/{invoice_id}/reject", response_model=InvoiceOut)
async def reject_invoice(
    invoice_id: UUID,
    data: InvoiceReject,
    db: AsyncSession = Depends(get_db),
) -> InvoiceOut:
    invoice = await service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    rejected = await service.reject_invoice(db, invoice, data)
    return _invoice_out(rejected)
