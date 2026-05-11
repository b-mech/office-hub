from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic import Field

from app.services.extraction.claude_provider import ClaudeProvider


router = APIRouter(prefix="/change-orders", tags=["change-orders"])


class ChangeOrderExtractRequest(BaseModel):
    email_body: str = Field(min_length=1)


class ChangeOrderLineItem(BaseModel):
    description: str = ""
    amount: Decimal = Decimal("0")
    is_credit: bool = False


class ChangeOrderDraft(BaseModel):
    address: str = ""
    client_name: str = ""
    co_number: str = ""
    date: str = ""
    line_items: list[ChangeOrderLineItem] = Field(default_factory=list)
    payment_method: Literal["add_to_mortgage", "due_upon_receipt"] = "due_upon_receipt"
    notes: str = ""


class ChangeOrderDraftResponse(BaseModel):
    id: str


@router.post("/extract", response_model=ChangeOrderDraft)
async def extract_change_order(request: ChangeOrderExtractRequest) -> ChangeOrderDraft:
    provider = ClaudeProvider()
    raw_response = await asyncio.to_thread(_request_change_order_extract, provider, request.email_body)
    parsed = provider._parse_json_response(raw_response)
    return _normalize_change_order_draft(parsed)


@router.post("/draft", response_model=ChangeOrderDraftResponse)
async def save_change_order_draft(_draft: ChangeOrderDraft) -> ChangeOrderDraftResponse:
    return ChangeOrderDraftResponse(id="stub-001")


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
            "allowances, or amounts that reduce the contract price. If a field is unknown, "
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
    text = _as_text(value).lower()
    if text == "add_to_mortgage":
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
