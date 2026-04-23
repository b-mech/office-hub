from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ExtractionResponse:
    extracted_payload: dict[str, Any]
    field_confidences: dict[str, float]
    low_confidence_fields: list[str]
    model_provider: str
    model_version: str
    prompt_version: str
    raw_response: str


class BaseProvider(ABC):
    @abstractmethod
    def extract(
        self,
        document_type: str,
        ocr_text: str,
        prompt_version: str,
    ) -> ExtractionResponse:
        raise NotImplementedError
