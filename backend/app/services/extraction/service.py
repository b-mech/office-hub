from __future__ import annotations

import re
from typing import Any

from app.core.config import settings
from app.services.extraction.base import BaseProvider
from app.services.extraction.base import ExtractionResponse
from app.services.extraction.claude_provider import ClaudeProvider
from app.services.extraction.openai_provider import OpenAIProvider


VERSION = "v4"


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
        return response


def get_extraction_service() -> ExtractionService:
    provider = settings.active_model_provider
    if provider == "claude":
        return ExtractionService(ClaudeProvider())
    if provider == "openai":
        return ExtractionService(OpenAIProvider())
    raise ValueError(f"Unsupported model provider: {provider}")
