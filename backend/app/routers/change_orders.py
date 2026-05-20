from __future__ import annotations

import asyncio
from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Any
from typing import Annotated
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from pydantic import Field

from app.core.config import settings
from app.core.database import get_db
from app.models.sales import ChangeOrder as ChangeOrderModel
from app.models.sales import ChangeOrderLineItem as ChangeOrderLineItemModel
from app.services.change_orders.pdf import render_change_order_pdf
from app.services.extraction.claude_provider import ClaudeProvider


def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    if x_api_key != settings.office_hub_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


router = APIRouter(
    prefix="/change-orders",
    tags=["change-orders"],
    dependencies=[Depends(verify_api_key)],
)


class ChangeOrderExtractRequest(BaseModel):
    email_body: str = Field(min_length=1)


class ChangeOrderLineItem(BaseModel):
    description: str = ""
    amount: Decimal = Decimal("0")
    is_credit: bool = False


class ChangeOrderDraft(BaseModel):
    lot_id: UUID | None = None
    address: str = ""
    client_name: str = ""
    co_number: str = ""
    date: str = ""
    line_items: list[ChangeOrderLineItem] = Field(default_factory=list)
    payment_method: Literal["add_to_mortgage", "due_upon_receipt"] = "due_upon_receipt"
    notes: str = ""


class ChangeOrderDraftResponse(BaseModel):
    id: str


class ChangeOrderOut(ChangeOrderDraft):
    id: UUID
    status: str = "draft"
    subtotal: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    docusign_envelope_id: str | None = None
    box_file_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ChangeOrderSignatureResponse(BaseModel):
    id: UUID
    status: str
    docusign_envelope_id: str | None = None
    message: str


@router.post("/extract", response_model=ChangeOrderDraft)
async def extract_change_order(request: ChangeOrderExtractRequest) -> ChangeOrderDraft:
    provider = ClaudeProvider()
    raw_response = await asyncio.to_thread(_request_change_order_extract, provider, request.email_body)
    parsed = provider._parse_json_response(raw_response)
    return _normalize_change_order_draft(parsed)


@router.post("/draft", response_model=ChangeOrderDraftResponse)
async def save_change_order_draft(
    draft: ChangeOrderDraft,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderDraftResponse:
    subtotal, gst, total = _calculate_totals(draft.line_items)
    change_order = ChangeOrderModel(
        lot_id=draft.lot_id,
        address=draft.address.strip(),
        client_name=draft.client_name.strip(),
        co_number=draft.co_number.strip() or None,
        date=_parse_date(draft.date),
        payment_method=draft.payment_method,
        notes=draft.notes.strip() or None,
        org_id=settings.default_org_id,
        subtotal=subtotal,
        gst=gst,
        total=total,
    )
    change_order.line_items = [
        ChangeOrderLineItemModel(
            description=item.description.strip(),
            amount=abs(item.amount),
            is_credit=item.is_credit,
            sort_order=index,
        )
        for index, item in enumerate(draft.line_items)
    ]

    async with db.begin():
        db.add(change_order)
        await db.flush()

    return ChangeOrderDraftResponse(id=str(change_order.id))


@router.get("", response_model=list[ChangeOrderOut])
async def list_change_orders(db: AsyncSession = Depends(get_db)) -> list[ChangeOrderOut]:
    result = await db.execute(
        select(ChangeOrderModel)
        .where(ChangeOrderModel.org_id == settings.default_org_id)
        .options(selectinload(ChangeOrderModel.line_items))
        .order_by(ChangeOrderModel.created_at.desc())
    )
    return [_change_order_out(change_order) for change_order in result.scalars()]


@router.get("/{change_order_id}", response_model=ChangeOrderOut)
async def get_change_order(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderOut:
    result = await db.execute(
        select(ChangeOrderModel)
        .where(
            ChangeOrderModel.id == change_order_id,
            ChangeOrderModel.org_id == settings.default_org_id,
        )
        .options(selectinload(ChangeOrderModel.line_items))
    )
    change_order = result.scalar_one_or_none()
    if not change_order:
        raise HTTPException(status_code=404, detail="Change order not found")
    return _change_order_out(change_order)


@router.get("/{change_order_id}/pdf")
async def get_change_order_pdf(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    pdf_bytes = render_change_order_pdf(change_order)
    filename = _change_order_filename(change_order)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{change_order_id}/send-signature", response_model=ChangeOrderSignatureResponse)
async def send_change_order_for_signature(
    change_order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChangeOrderSignatureResponse:
    change_order = await _get_change_order_model(change_order_id=change_order_id, db=db)
    render_change_order_pdf(change_order)
    raise HTTPException(
        status_code=501,
        detail=(
            "Change order PDF generation is ready, but DocuSign is not configured. "
            "Add the DocuSign account credentials and final PDF template before sending envelopes."
        ),
    )


async def _get_change_order_model(change_order_id: UUID, db: AsyncSession) -> ChangeOrderModel:
    result = await db.execute(
        select(ChangeOrderModel)
        .where(
            ChangeOrderModel.id == change_order_id,
            ChangeOrderModel.org_id == settings.default_org_id,
        )
        .options(selectinload(ChangeOrderModel.line_items))
    )
    change_order = result.scalar_one_or_none()
    if not change_order:
        raise HTTPException(status_code=404, detail="Change order not found")
    return change_order


def _request_change_order_extract(provider: ClaudeProvider, email_body: str) -> str:
    response = provider.client.messages.create(
        model=provider.model_version,
        max_tokens=2000,
        system=(
            "Return ONLY valid JSON. Extract a residential home-build change order draft "
            "from the email body. Use this exact schema: "
            '{"address": string, "client_name": string, '
            '"line_items": [{"description": string, "amount": number, "is_credit": boolean}], '
            '"payment_method": "add_to_mortgage" | "due_upon_receipt", "notes": string}. '
            "Amounts are positive numbers. Mark is_credit true for credits, deductions, "
            "allowances, or amounts that reduce the contract price. Treat Due on Receipt, "
            "Due upon Receipt, and Due upon receipt as due_upon_receipt. If a field is unknown, "
            "use an empty string, empty array, or due_upon_receipt."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Email body:\n\n{email_body}",
            }
        ],
    )
    return provider._extract_text_response(response)


def _normalize_change_order_draft(parsed: dict[str, Any]) -> ChangeOrderDraft:
    return ChangeOrderDraft(
        address=_as_text(parsed.get("address")),
        client_name=_as_text(parsed.get("client_name")),
        co_number=_as_text(parsed.get("co_number")),
        date=_as_text(parsed.get("date")),
        line_items=_normalize_line_items(parsed.get("line_items")),
        payment_method=_normalize_payment_method(parsed.get("payment_method")),
        notes=_as_text(parsed.get("notes")),
    )


def _change_order_out(change_order: ChangeOrderModel) -> ChangeOrderOut:
    return ChangeOrderOut(
        id=change_order.id,
        lot_id=change_order.lot_id,
        address=change_order.address,
        client_name=change_order.client_name,
        co_number=change_order.co_number or "",
        date=change_order.date.isoformat() if change_order.date else "",
        line_items=[
            ChangeOrderLineItem(
                description=item.description,
                amount=item.amount,
                is_credit=item.is_credit,
            )
            for item in change_order.line_items
        ],
        payment_method=_normalize_payment_method(change_order.payment_method),
        notes=change_order.notes or "",
        status=change_order.status,
        subtotal=change_order.subtotal,
        gst=change_order.gst,
        total=change_order.total,
        docusign_envelope_id=change_order.docusign_envelope_id,
        box_file_id=change_order.box_file_id,
        created_at=change_order.created_at,
        updated_at=change_order.updated_at,
    )


def _calculate_totals(line_items: list[ChangeOrderLineItem]) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = sum(
        (
            -abs(item.amount) if item.is_credit else abs(item.amount)
            for item in line_items
        ),
        Decimal("0"),
    )
    subtotal = subtotal.quantize(Decimal("0.01"))
    gst = (subtotal * Decimal("0.05")).quantize(Decimal("0.01"))
    total = (subtotal + gst).quantize(Decimal("0.01"))
    return subtotal, gst, total


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_line_items(value: object) -> list[ChangeOrderLineItem]:
    if not isinstance(value, list):
        return []

    line_items: list[ChangeOrderLineItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        line_items.append(
            ChangeOrderLineItem(
                description=_as_text(item.get("description")),
                amount=_as_decimal(item.get("amount")),
                is_credit=bool(item.get("is_credit")),
            )
        )
    return line_items


def _normalize_payment_method(value: object) -> Literal["add_to_mortgage", "due_upon_receipt"]:
    text = _as_text(value).lower().replace("-", " ").replace("_", " ")
    if "mortgage" in text:
        return "add_to_mortgage"
    return "due_upon_receipt"


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return Decimal("0")


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _change_order_filename(change_order: ChangeOrderModel) -> str:
    label = change_order.co_number or str(change_order.id)
    address = "".join(
        character if character.isalnum() or character in (" ", "-", "_") else "-"
        for character in change_order.address
    ).strip()
    return f"{address or 'change-order'}-{label}.pdf"
