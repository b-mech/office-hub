from __future__ import annotations

import base64
import json
import re
from typing import Any

import anthropic

from app.core.config import settings


PROMPTS = {
    "PRO": (
        "This is a ProAuto funding breakdown document. Extract for each property: "
        "Property address, total commitment amount, amount already funded/drawn, "
        "opening/available balance. Return JSON: "
        '{"items":[{"address":"","total_commitment":0,"already_drawn":0,"opening_balance":0,"confidence":"high"}]}.'
    ),
    "SCU": (
        "This is an SCU (Steinbach Credit Union) account balance screenshot. Extract: "
        "account name/address, current balance (already drawn), available balance "
        "(remaining to draw), total facility if visible. Return JSON: "
        '{"address":"","current_balance":0,"available_balance":0,"total_facility":0,"confidence":"high"}.'
    ),
    "CLIENT": (
        "This is a mortgage or construction loan account screenshot. Extract: property/account name, "
        "total loan amount, amount advanced to date, remaining available. Return JSON: "
        '{"address":"","total_facility":0,"already_drawn":0,"available_balance":0,"confidence":"high"}.'
    ),
}

CLIENT_OTP_PROMPT = """
You are extracting a signed sale Offer to Purchase for a residential home build.
Return only JSON with this shape:
{
  "purchase_price": "0.00 or null",
  "client_name": "Purchaser names or null",
  "otp_date": "YYYY-MM-DD or null",
  "deposits": [
    {"seq": 1, "label_raw": "verbatim wording", "amount": "0.00", "due_raw": "verbatim due wording", "source_page": 1}
  ],
  "schedule": [
    {
      "seq": 1,
      "label_raw": "verbatim milestone wording",
      "amount": "0.00 or null",
      "amount_type": "fixed or percent",
      "percent": "number or null",
      "conditions_raw": "verbatim conditions or null",
      "source_page": 1
    }
  ],
  "confidence": "high or needs_review",
  "notes": "short validation/ambiguity notes"
}
Rules:
- Extract only amounts and percentages explicitly present in the OTP.
- If an explicit percentage appears, include percent and amount_type="percent"; calculate amount only when purchase_price is explicit.
- Every amount or percentage must include source_page.
- Do not infer missing draw schedule items.
- If no progress-payment schedule exists, return schedule=[] and explain the finding in notes.
- Use strings for money values; do not use floating point.
"""


async def extract_financing_document(*, lender_type: str, content: bytes, content_type: str) -> dict[str, Any]:
    lender = lender_type.upper()
    if lender == "RSU":
        return {"confidence": "manual", "message": "RSU documents are reference-only; enter values manually."}

    prompt = PROMPTS.get(lender, PROMPTS["CLIENT"])
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    media_type = content_type or "application/octet-stream"
    block_type = "document" if media_type == "application/pdf" else "image"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": block_type,
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(content).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    raw = "\n".join(getattr(block, "text", "") for block in response.content).strip()
    return _parse_json(raw)


async def extract_client_otp_document(*, content: bytes, content_type: str) -> dict[str, Any]:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    media_type = content_type or "application/pdf"
    block_type = "document" if media_type == "application/pdf" else "image"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": block_type,
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(content).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": CLIENT_OTP_PROMPT},
                ],
            }
        ],
    )
    raw = "\n".join(getattr(block, "text", "") for block in response.content).strip()
    return _parse_json(raw)


def requires_review(extracted: dict[str, Any]) -> bool:
    confidence = str(extracted.get("confidence", "")).lower()
    if confidence and confidence != "high":
        return True
    items = extracted.get("items")
    if isinstance(items, list):
        return any(str(item.get("confidence", "")).lower() != "high" for item in items if isinstance(item, dict))
    return False


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1:
            return {"raw": raw, "confidence": "low"}
        parsed = json.loads(cleaned[start : end + 1])
    return parsed if isinstance(parsed, dict) else {"items": parsed}
