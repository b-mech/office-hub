from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.core.addresses import normalize_address
from app.services.promotion import PromotionService


class PromotionDryRunTest(unittest.TestCase):
    def test_property_alias_and_annotation_normalize_to_same_key(self) -> None:
        self.assertEqual(
            normalize_address("14 Grove Crescent").canonical_key,
            normalize_address("14 Grove Cresent ( Fall 2027)").canonical_key,
        )

    def test_malformed_lot_is_reported_as_warning(self) -> None:
        service = PromotionService(AsyncMock())
        payload = {
            "agreement": {
                "vendor_name": "Vendor",
                "development_name": "Development",
                "municipality": "Municipality",
                "agreement_date": "2026-01-01",
                "total_purchase_price": "100000.00",
            },
            "security_deposit": {
                "rate_per_lot": "3000.00",
                "maximum_amount": "30000.00",
            },
            "lots": [
                {
                    "block": "1",
                    "lot_number": "",
                    "plan": "12345",
                    "purchase_price": "100000.00",
                    "deposit_1_amount": "15000.00",
                    "deposit_2_amount": "10000.00",
                }
            ],
        }
        service._preview = service._new_preview("land_otp", payload)

        service._collect_land_input_warnings(payload)

        self.assertIn(
            "incomplete_legal_description",
            {warning["code"] for warning in service._preview["warnings"]},
        )
        self.assertTrue(
            any("lot_number" in warning["message"] for warning in service._preview["warnings"])
        )

    def test_explicit_legal_description_allows_missing_block(self) -> None:
        service = PromotionService(AsyncMock())

        self.assertEqual(
            service._build_legal_description(
                {"legal_description_normalized": "  title 341829/1  "}
            ),
            "TITLE 341829/1",
        )
        self.assertEqual(
            service._build_legal_description({"lot_number": "3", "plan": "72890"}),
            "LT 3 PLAN 72890",
        )

    def test_dynamic_deposit_schedule_preserves_three_triggers(self) -> None:
        service = PromotionService(AsyncMock())
        schedule = [
            {"deposit_number": 1, "amount": "5000", "trigger_type": "on_signing"},
            {"deposit_number": 2, "amount": "10000", "trigger_type": "milestone"},
            {"deposit_number": 3, "amount": "10000", "trigger_type": "milestone"},
        ]

        self.assertEqual(service._deposit_specs({"deposit_schedule": schedule}), schedule)

    def test_unallocated_purchase_price_is_not_a_missing_field_warning(self) -> None:
        service = PromotionService(AsyncMock())
        payload = {
            "agreement": {
                "vendor_name": "Vendor",
                "development_name": "Development",
                "municipality": "Municipality",
                "agreement_date": "2026-01-01",
                "total_purchase_price": "184000.00",
            },
            "security_deposit": {},
            "lots": [
                {
                    "lot_number": "1",
                    "plan": "12345",
                    "metadata": {"price_allocation": "agreement_total_unallocated"},
                    "deposit_schedule": [],
                }
            ],
        }
        service._preview = service._new_preview("land_otp", payload)

        service._collect_land_input_warnings(payload)

        self.assertFalse(
            any(
                warning["code"] == "missing_required_field"
                and "purchase_price" in warning["message"]
                for warning in service._preview["warnings"]
            )
        )


if __name__ == "__main__":
    unittest.main()
