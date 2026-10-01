from __future__ import annotations

import re
from typing import Any

from app.core.config import settings
from app.services.extraction.base import BaseProvider
from app.services.extraction.base import ExtractionResponse
from app.services.extraction.claude_provider import ClaudeProvider
from app.services.extraction.openai_provider import OpenAIProvider


VERSION = "v8"


_LEGAL_LOT_LINE = re.compile(
    r"^\s*LOTS?\s+(?P<lot_number>.+?)\s+BLOCK\s+(?P<block>\S+)\s+"
    r"PLAN\s+(?P<plan>.+?)(?=\s+IN\s+|\s*\(|\s*$)",
    re.IGNORECASE,
)


def extract_legal_description_lots(ocr_text: str) -> list[dict[str, Any]]:
    """Recover grouped lot descriptions when a model omits a clear legal lot list."""
    lots: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_line in ocr_text.splitlines():
        line = " ".join(source_line.split())
        match = _LEGAL_LOT_LINE.match(line)
        if match is None:
            continue

        lot_number = re.sub(r"\s*-\s*", "-", match.group("lot_number").strip())
        lot_number = re.sub(r"\s*,\s*", ", ", lot_number)
        block = match.group("block").strip()
        plan = match.group("plan").strip()
        identity = (lot_number.casefold(), block.casefold(), plan.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        lots.append(
            {
                "block": block,
                "lot_number": lot_number,
                "plan": plan,
                "civic_address": None,
                "street_number": None,
                "street_name": None,
                "frontage_metres": None,
                "frontage_feet": None,
                "lot_notes": line,
                "purchase_price": None,
                "deposit_1_amount": None,
                "deposit_2_amount": None,
                "deposit_2_due_date": None,
            }
        )
    return lots


def remove_land_lot_confidences(response: ExtractionResponse) -> None:
    """Remove uncalibrated lot-field confidence values from Land OTP output."""
    response.field_confidences = {
        path: confidence
        for path, confidence in response.field_confidences.items()
        if not path.startswith("lots.")
    }
    response.low_confidence_fields = [
        path for path in response.low_confidence_fields if not path.startswith("lots.")
    ]


def validate_land_source_selection(response: ExtractionResponse) -> None:
    """Reject Land OTP output that cannot explain its operative source chain."""
    payload = response.extracted_payload
    source_documents = payload.get("source_documents")
    operative_selection = payload.get("operative_selection")
    field_provenance = payload.get("field_provenance")
    if not isinstance(source_documents, list) or not source_documents:
        raise ValueError("Land OTP extraction must inventory source_documents")
    if not isinstance(operative_selection, dict):
        raise ValueError("Land OTP extraction must include operative_selection")
    rationale = operative_selection.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Land OTP extraction must explain operative_selection.rationale")
    if not isinstance(field_provenance, dict):
        raise ValueError("Land OTP extraction must include field_provenance")


class ExtractionService:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def extract(self, document_type: str, ocr_text: str) -> ExtractionResponse:
        response = self.provider.extract(
            document_type=document_type,
            ocr_text=ocr_text,
            prompt_version=VERSION,
        )
        if document_type == "land_otp" and not response.extracted_payload.get("lots"):
            recovered_lots = extract_legal_description_lots(ocr_text)
            if recovered_lots:
                response.extracted_payload["lots"] = recovered_lots
        if document_type == "land_otp":
            remove_land_lot_confidences(response)
            validate_land_source_selection(response)
        return response


def get_extraction_service() -> ExtractionService:
    provider = settings.active_model_provider
    if provider == "claude":
        return ExtractionService(ClaudeProvider())
    if provider == "openai":
        return ExtractionService(OpenAIProvider())
    raise ValueError(f"Unsupported model provider: {provider}")
