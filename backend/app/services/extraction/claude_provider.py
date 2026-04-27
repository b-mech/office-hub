from __future__ import annotations

import json
from typing import Any

import anthropic

from app.core.config import settings
from app.services.extraction.base import BaseProvider
from app.services.extraction.base import ExtractionResponse
from app.services.extraction.prompts import get_system_prompt


class ClaudeProvider(BaseProvider):
    def __init__(self) -> None:
        self.api_key = settings.anthropic_api_key
        self.active_model_provider = settings.active_model_provider
        self.model_provider = "claude"
        self.model_version = "claude-sonnet-4-6"
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def extract(
        self,
        document_type: str,
        ocr_text: str,
        prompt_version: str,
    ) -> ExtractionResponse:
        system_prompt = get_system_prompt(document_type)
        user_prompt = self._build_user_prompt(document_type=document_type, ocr_text=ocr_text)

        response = self.client.messages.create(
            model=self.model_version,
            max_tokens=8000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        )

        raw_response = self._extract_text_response(response)
        parsed_response = self._parse_json_response(raw_response)
        field_confidences = self._normalize_field_confidences(
            parsed_response.get("field_confidences", {})
        )

        extracted_payload = {
            key: value
            for key, value in parsed_response.items()
            if key != "field_confidences"
        }

        return ExtractionResponse(
            extracted_payload=extracted_payload,
            field_confidences=field_confidences,
            low_confidence_fields=[
                field_name
                for field_name, confidence in field_confidences.items()
                if confidence < 0.7
            ],
            model_provider=self.model_provider,
            model_version=self.model_version,
            prompt_version=prompt_version,
            raw_response=raw_response,
        )

    def _build_user_prompt(self, document_type: str, ocr_text: str) -> str:
        return (
            f"Document type: {document_type}\n"
            f"OCR text begins below.\n\n{ocr_text}"
        )

    def _extract_text_response(self, response: anthropic.types.Message) -> str:
        text_blocks: list[str] = []
        for block in response.content:
            block_text = getattr(block, "text", None)
            if block_text:
                text_blocks.append(block_text)
        return "\n".join(text_blocks).strip()

    def _parse_json_response(self, raw_response: str) -> dict[str, Any]:
        cleaned_response = raw_response.strip()
        response_lines = cleaned_response.splitlines()

        if response_lines and response_lines[0].strip() in {"```json", "```"}:
            response_lines = response_lines[1:]

        if response_lines and response_lines[-1].strip() == "```":
            response_lines = response_lines[:-1]

        cleaned_response = "\n".join(response_lines).strip()

        try:
            parsed = json.loads(cleaned_response)
        except json.JSONDecodeError as exc:
            parsed = self._extract_json_object(cleaned_response)
            if parsed is None:
                raise ValueError("Claude returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Claude response JSON must be an object")

        return parsed

    def _extract_json_object(self, response_text: str) -> dict[str, Any] | None:
        start = response_text.find("{")
        end = response_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            parsed = json.loads(response_text[start : end + 1])
        except json.JSONDecodeError:
            return None

        return parsed if isinstance(parsed, dict) else None

    def _normalize_field_confidences(
        self,
        field_confidences: object,
    ) -> dict[str, float]:
        if not isinstance(field_confidences, dict):
            return {}

        normalized: dict[str, float] = {}
        for key, value in field_confidences.items():
            if not isinstance(key, str):
                continue
            try:
                confidence = float(value)
            except (TypeError, ValueError):
                confidence = 0.0

            normalized[key] = min(max(confidence, 0.0), 1.0)

        return normalized
