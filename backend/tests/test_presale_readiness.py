from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("MINIO_URL", "http://localhost:9000")
os.environ.setdefault("MINIO_ROOT_USER", "minio")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "minio123")
os.environ.setdefault("IMAP_HOST", "localhost")
os.environ.setdefault("IMAP_USER", "test")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IMAP_FOLDER", "INBOX")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ACTIVE_MODEL_PROVIDER", "claude")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("OFFICE_HUB_API_KEY", "test")
os.environ.setdefault("DEFAULT_ORG_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.presales import (
    PartnerRuleData,
    ReadinessInputs,
    evaluate_partner_rules,
    normalize_extracted_payload,
)


def rules() -> list[PartnerRuleData]:
    return [
        PartnerRuleData(
            partner_code="SCU",
            display_name="Steinbach Credit Union",
            priority=1,
            required_docs=["approval_letter", "appraisal", "otp_land", "otp_sale", "stamped_plans", "prelim_budget"],
            required_fields=[],
            disqualifying_conditions=["sale_of_existing_home"],
            min_quality_score=6,
            formula=None,
            package_recipient=None,
            package_docs=[],
        ),
        PartnerRuleData(
            partner_code="PROAUTO",
            display_name="PROAuto",
            priority=2,
            required_docs=["approval_letter", "otp_land", "otp_sale", "prelim_budget"],
            required_fields=["otp_sale.sale_price", "lot.building_type", "prelim_budget.total", "otp_land.lot_cost"],
            disqualifying_conditions=[],
            min_quality_score=None,
            formula={"type": "pct_of_sum", "pct": 0.90, "inputs": ["otp_land.lot_cost", "prelim_budget.total"]},
            package_recipient=None,
            package_docs=[],
        ),
    ]


def full_inputs(**overrides: object) -> ReadinessInputs:
    values = {
        "available_docs": {"approval_letter", "appraisal", "otp_land", "otp_sale", "stamped_plans", "prelim_budget"},
        "fields": {
            "otp_sale.sale_price": Decimal("489900"),
            "lot.building_type": "bungalow",
            "prelim_budget.total": Decimal("400000"),
            "otp_land.lot_cost": Decimal("58333.33"),
            "approval_letter.approved_amount": Decimal("450000"),
        },
        "conditions": [],
        "quality_score": 8,
        "lender_contacted_at": None,
        "scu_capacity_ok": True,
    }
    values.update(overrides)
    return ReadinessInputs(**values)  # type: ignore[arg-type]


def test_complete_preferred_package_suggests_scu() -> None:
    result = evaluate_partner_rules(rules(), full_inputs(), computed_at=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert result["suggested"] == "SCU"
    assert result["partners"]["SCU"]["state"] == "ready"


def test_sale_of_existing_home_disqualifies_scu_and_suggests_proauto() -> None:
    result = evaluate_partner_rules(
        rules(),
        full_inputs(conditions=[{"category": "sale_of_existing_home", "text": "Subject to sale of existing home"}]),
    )
    assert result["partners"]["SCU"]["state"] == "disqualified"
    assert result["partners"]["SCU"]["disqualified_by"][0]["text"] == "Subject to sale of existing home"
    assert result["suggested"] == "PROAUTO"
    assert result["partners"]["PROAUTO"]["advance"] == 412500
    assert result["partners"]["PROAUTO"]["equity_gap"] == 77400


def test_low_quality_blocks_scu_until_lender_contacted() -> None:
    blocked = evaluate_partner_rules(rules(), full_inputs(quality_score=5))
    assert blocked["partners"]["SCU"]["state"] == "blocked_by_quality"
    contacted = evaluate_partner_rules(
        rules(),
        full_inputs(quality_score=5, lender_contacted_at=datetime(2026, 9, 8, tzinfo=timezone.utc)),
    )
    assert contacted["partners"]["SCU"]["state"] == "ready"
    assert contacted["suggested"] == "SCU"


def test_missing_items_are_reported_per_partner() -> None:
    result = evaluate_partner_rules(
        rules(),
        full_inputs(
            available_docs={"approval_letter", "otp_land", "otp_sale"},
            fields={"otp_sale.sale_price": Decimal("489900"), "otp_land.lot_cost": Decimal("58333.33")},
        ),
    )
    assert {"appraisal", "stamped_plans", "prelim_budget"}.issubset(result["partners"]["SCU"]["missing"])
    assert {"prelim_budget", "lot.building_type", "prelim_budget.total"}.issubset(result["partners"]["PROAUTO"]["missing"])


def test_extraction_normalization_recategorizes_unknown_conditions_as_other() -> None:
    result = normalize_extracted_payload(
        {
            "document_type": "pre_approval",
            "approved_amount": "$450,000",
            "conditions": [{"text": "Call lender", "category": "made_up"}],
            "signed": 1,
        }
    )
    assert result["approved_amount"] == "450000.00"
    assert result["conditions"] == [{"text": "Call lender", "category": "other", "deadline": None}]
