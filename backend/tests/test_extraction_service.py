from app.services.extraction.base import BaseProvider
from app.services.extraction.base import ExtractionResponse
from app.services.extraction.service import ExtractionService
from app.services.extraction.service import VERSION
from app.services.extraction.prompts import LAND_OTP_PROMPT


class StubProvider(BaseProvider):
    def __init__(self, response: ExtractionResponse) -> None:
        self.response = response

    def extract(
        self,
        document_type: str,
        ocr_text: str,
        prompt_version: str,
    ) -> ExtractionResponse:
        return self.response


def test_land_lot_confidences_are_removed() -> None:
    response = ExtractionResponse(
        extracted_payload={
            "source_documents": [{"source_id": "base", "execution_status": "signed"}],
            "operative_selection": {"rationale": "The signed base agreement controls."},
            "field_provenance": {"agreement.vendor_name": {"source_id": "base"}},
            "lots": [
                {
                    "block": "6",
                    "lot_number": "5",
                    "plan": "71499",
                    "civic_address": None,
                }
            ]
        },
        field_confidences={
            "agreement.vendor_name": 0.95,
            "lots.0.block": 0.95,
            "lots.0.plan": 0.69,
        },
        low_confidence_fields=["lots.0.plan"],
        model_provider="test",
        model_version="test",
        prompt_version="test",
        raw_response="{}",
    )

    result = ExtractionService(StubProvider(response)).extract("land_otp", "")

    assert result.field_confidences == {"agreement.vendor_name": 0.95}
    assert result.low_confidence_fields == []


def test_land_prompt_requires_complete_operative_chain_audit() -> None:
    assert VERSION == "v8"
    assert "Inventory every agreement, amendment, addendum, schedule" in LAND_OTP_PROMPT
    assert "express replacement/supersession wording" in LAND_OTP_PROMPT
    assert "changes only the fields within its stated scope" in LAND_OTP_PROMPT
    assert "Never treat a stale conflicting schedule as operative" in LAND_OTP_PROMPT
    assert "field_provenance" in LAND_OTP_PROMPT
    assert "operative_selection.rationale" in LAND_OTP_PROMPT


def test_land_extraction_without_selection_rationale_is_rejected() -> None:
    response = ExtractionResponse(
        extracted_payload={
            "source_documents": [{"source_id": "base"}],
            "operative_selection": {"rationale": ""},
            "field_provenance": {},
            "lots": [],
        },
        field_confidences={},
        low_confidence_fields=[],
        model_provider="test",
        model_version="test",
        prompt_version="test",
        raw_response="{}",
    )

    try:
        ExtractionService(StubProvider(response)).extract("land_otp", "")
    except ValueError as exc:
        assert "operative_selection.rationale" in str(exc)
    else:
        raise AssertionError("missing operative rationale was accepted")


def test_non_land_extraction_is_unchanged() -> None:
    response = ExtractionResponse(
        extracted_payload={"lots": [{"block": "6"}]},
        field_confidences={},
        low_confidence_fields=[],
        model_provider="test",
        model_version="test",
        prompt_version="test",
        raw_response="{}",
    )

    result = ExtractionService(StubProvider(response)).extract("sale_otp", "")

    assert result.field_confidences == {}
    assert result.low_confidence_fields == []
