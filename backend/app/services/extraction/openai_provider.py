from __future__ import annotations

from app.core.config import settings
from app.services.extraction.base import BaseProvider
from app.services.extraction.base import ExtractionResponse
from app.services.extraction.prompts import get_system_prompt

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional until dependency is added
    OpenAI = None


class OpenAIProvider(BaseProvider):
    def __init__(self) -> None:
        self.api_key = settings.openai_api_key
        self.active_model_provider = settings.active_model_provider
        self.model_provider = "openai"
        self.model_version = "gpt-4o"
        self.client = OpenAI(api_key=self.api_key) if OpenAI is not None else None

    def extract(
        self,
        document_type: str,
        ocr_text: str,
        prompt_version: str,
    ) -> ExtractionResponse:
        system_prompt = get_system_prompt(document_type)

        if self.client is None:
            raise RuntimeError(
                "openai SDK is not installed. Add the dependency before using OpenAIProvider."
            )

        response = self.client.responses.create(
            model=self.model_version,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Document type: {document_type}\nOCR text begins below.\n\n{ocr_text}",
                        }
                    ],
                },
            ],
        )

        raw_response = getattr(response, "output_text", "")

        return ExtractionResponse(
            extracted_payload={},
            field_confidences={},
            low_confidence_fields=[],
            model_provider=self.model_provider,
            model_version=self.model_version,
            prompt_version=prompt_version,
            raw_response=raw_response,
        )
