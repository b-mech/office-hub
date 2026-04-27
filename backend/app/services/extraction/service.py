from __future__ import annotations

from app.core.config import settings
from app.services.extraction.base import BaseProvider
from app.services.extraction.base import ExtractionResponse
from app.services.extraction.claude_provider import ClaudeProvider
from app.services.extraction.openai_provider import OpenAIProvider


VERSION = "v2"


class ExtractionService:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def extract(self, document_type: str, ocr_text: str) -> ExtractionResponse:
        return self.provider.extract(
            document_type=document_type,
            ocr_text=ocr_text,
            prompt_version=VERSION,
        )


def get_extraction_service() -> ExtractionService:
    provider = settings.active_model_provider
    if provider == "claude":
        return ExtractionService(ClaudeProvider())
    if provider == "openai":
        return ExtractionService(OpenAIProvider())
    raise ValueError(f"Unsupported model provider: {provider}")
