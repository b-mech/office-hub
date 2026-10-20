"""Extract lawyer trust notices. All output remains staging data until reviewed."""
from __future__ import annotations

import asyncio
import base64
from typing import Any

import anthropic

from app.core.config import settings
from app.services.extraction.approval_letters import _parse_json, _render_pdf

FUNDS_TYPES = {"lot_deposit", "pro_draw", "client_funded_draw", "statement_of_adjustments", "other"}

PROMPT = """Read every page of this lawyer funds PDF. Return one JSON object, no markdown:
{
  "funds_type": "lot_deposit | pro_draw | client_funded_draw | statement_of_adjustments | other",
  "classification_reason": "brief reason, especially for other",
  "deposit_ordinal": "1st | 2nd | 3rd | null",
  "entries": [{"property_address": "", "amount": "0.00", "cheque_number": null,
               "date": "YYYY-MM-DD|null", "payee": "", "memo": "",
               "closing": null}],
  "law_firm": "", "trust_statement_total": "0.00|null",
  "funds_release_date": "YYYY-MM-DD|null"
}
For a statement of adjustments, put its closing object on the relevant entry:
{"closing_type":"sale|refinance","closing_date":"YYYY-MM-DD", "sale_price":"0.00|null",
 "adjustments":[{"label":"","amount":"0.00","direction":"credit_vendor|credit_purchaser"}],
 "discharges":[{"lender":"","facility_reference":"","payout_amount":"0.00","payout_date":"YYYY-MM-DD"}],
 "net_proceeds":"0.00|null","new_lender":""}.
Produce one entry per property/address. Preserve cheque numbers exactly. Use null for anything
not printed. Do not infer amounts, dates, cheque numbers, lenders, or confidence scores.
If the document is ambiguous, unrelated, or its type is uncertain, classify other and explain.
""".strip()


async def extract_funds_pdf(content: bytes) -> dict[str, Any]:
    pages = await asyncio.to_thread(_render_pdf, content)
    blocks: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.b64encode(page).decode("ascii")}}
        for page in pages
    ]
    blocks.append({"type": "text", "text": PROMPT})
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await asyncio.wait_for(client.messages.create(
        model="claude-sonnet-4-6", max_tokens=8000,
        messages=[{"role": "user", "content": blocks}],
    ), timeout=240)
    payload = _parse_json("\n".join(getattr(block, "text", "") for block in response.content))
    if payload.get("funds_type") not in FUNDS_TYPES:
        payload["funds_type"] = "other"
        payload["classification_reason"] = "Document type was not established by extraction"
    if not isinstance(payload.get("entries"), list):
        payload["entries"] = []
    return payload
