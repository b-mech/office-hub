from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any

import anthropic
import fitz

from app.core.config import settings
from app.services.extraction.base import ExtractionResponse


PROMPT_VERSION = "presale-approval-letter-v1"
CONDITION_CATEGORIES = (
    "sale_of_existing_home",
    "subject_to_appraisal",
    "income_verification",
    "down_payment_verification",
    "credit_review",
    "insurer_approval",
    "builder_docs",
    "rate_hold_expiry",
    "other",
)

APPROVAL_LETTER_PROMPT = """
You extract purchaser mortgage approval letters for a Canadian residential builder.
Read every supplied page image. Return only valid JSON with exactly these top-level keys:
{
  "document_type": "pre_approval | firm_commitment | other",
  "lender_name": "",
  "broker_name": "",
  "broker_email": "",
  "purchaser_names": [],
  "property_address": "",
  "approved_amount": "0.00",
  "purchase_price": "0.00",
  "down_payment": "0.00",
  "ltv": 0.0,
  "rate": 0.0,
  "term_months": 0,
  "amortization_years": 0,
  "insurer": "CMHC | Sagen | Canada Guaranty | none | unknown",
  "conditions": [{"text": "verbatim condition", "category": "category", "deadline": "YYYY-MM-DD|null"}],
  "expiry_date": "YYYY-MM-DD|null",
  "signed": true,
  "field_confidences": {}
}

Use a decimal string for every money field. Do not infer missing values. Use null for a
missing scalar and [] for no stated conditions. field_confidences maps dotted field paths
to numbers from 0 to 1 and must include document_type, approved_amount, expiry_date,
conditions, and every field you populate.

Assign each condition exactly one of these categories:
- sale_of_existing_home: approval depends on selling an existing property
- subject_to_appraisal: lender appraisal must support value
- income_verification: employment, income, pay stubs, or tax documents outstanding
- down_payment_verification: proof of funds or gift letter outstanding
- credit_review: updated credit bureau or debt payout
- insurer_approval: mortgage insurer approval pending
- builder_docs: builder agreement, plans, warranty, or other builder documents
- rate_hold_expiry: rate hold or commitment expiry language
- other: anything else

Preserve the condition wording verbatim. Do not classify a routine property appraisal as
sale_of_existing_home. Return an empty conditions array only when the letter states no
conditions or none are present.
""".strip()


async def extract_approval_letter(content: bytes) -> ExtractionResponse:
    images = await asyncio.to_thread(_render_pdf, content)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    blocks: list[dict[str, Any]] = []
    for image in images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(image).decode("ascii"),
                },
            }
        )
    blocks.append({"type": "text", "text": APPROVAL_LETTER_PROMPT})
    response = await asyncio.wait_for(
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            messages=[{"role": "user", "content": blocks}],
        ),
        timeout=240,
    )
    raw = "\n".join(getattr(block, "text", "") for block in response.content).strip()
    parsed = _parse_json(raw)
    confidence_source = parsed.pop("field_confidences", {})
    confidences = {
        str(key): min(max(float(value), 0.0), 1.0)
        for key, value in confidence_source.items()
        if isinstance(confidence_source, dict)
        if _is_number(value)
    }
    return ExtractionResponse(
        extracted_payload=parsed,
        field_confidences=confidences,
        low_confidence_fields=sorted(key for key, value in confidences.items() if value < 0.75),
        model_provider="claude",
        model_version="claude-sonnet-4-6",
        prompt_version=PROMPT_VERSION,
        raw_response=raw,
    )


def _render_pdf(content: bytes) -> list[bytes]:
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("Approval letter is not a readable PDF") from exc
    try:
        if document.page_count == 0:
            raise ValueError("Approval letter PDF has no pages")
        pages: list[bytes] = []
        matrix = fitz.Matrix(1.5, 1.5)
        for page_number in range(min(document.page_count, 12)):
            pixmap = document.load_page(page_number).get_pixmap(matrix=matrix, alpha=False)
            pages.append(pixmap.tobytes("png"))
        return pages
    finally:
        document.close()


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("Claude returned invalid approval-letter JSON")
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Claude approval-letter response must be a JSON object")
    return parsed


def _is_number(value: object) -> bool:
    try:
        float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True
