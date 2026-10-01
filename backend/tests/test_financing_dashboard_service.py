from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from uuid import uuid4
import unittest

from app.schemas.financing import FinancingPropertyOut
from app.services.financing import _assert_no_duplicate_pro_properties
from app.services.financing import _dedupe_dashboard_properties
from app.services.financing import _summary
from app.services.financing import _statement_names_match
from app.services.financing import _property_from_row


def row(
    property_id,
    lender_type: str,
    *,
    facility_id=None,
    stage: str | None = None,
    already_drawn: Decimal = Decimal("0"),
    draw_eligible: Decimal | None = None,
    flag: str | None = None,
) -> FinancingPropertyOut:
    return FinancingPropertyOut(
        property_id=property_id,
        address="Test",
        lender_type=lender_type,
        stage=stage,
        stage_is_estimate=False,
        already_drawn=already_drawn,
        draw_eligible=draw_eligible,
        flag=flag,
        formula="test",
        facility_id=facility_id,
    )


class FinancingDashboardServiceTest(unittest.TestCase):
    def test_statement_name_matching_handles_portfolio_headers(self) -> None:
        self.assertTrue(_statement_names_match("114 FROESE", "114 FROESE CRESCENT"))
        self.assertTrue(
            _statement_names_match(
                "WATERSIDE DEV PARKVIEW POINTE WEST ST PAUL",
                "WATERSIDE DEV PARKVIEW POINTE WEST ST PAUL MB",
            )
        )
        self.assertTrue(
            _statement_names_match(
                "PROMISSORY NOTE TEMPLETON DEV DEPOSIT",
                "TEMPLETON DEV DEPOSIT PROMISSORY NOTE",
            )
        )

    def test_statement_name_matching_rejects_different_addresses(self) -> None:
        self.assertFalse(_statement_names_match("149 RAMONA GALLOS WAY", "153 RAMONA GALLOS WAY"))

    def test_no_property_may_contribute_two_pro_rows(self) -> None:
        property_id = uuid4()
        with self.assertRaises(AssertionError):
            _assert_no_duplicate_pro_properties([row(property_id, "PRO"), row(property_id, "PRO")])

    def test_duplicate_non_pro_rows_do_not_trip_pro_assertion(self) -> None:
        property_id = uuid4()
        _assert_no_duplicate_pro_properties([row(property_id, "SCU"), row(property_id, "SCU")])

    def test_dashboard_dedupe_prefers_facility_row_over_placeholder(self) -> None:
        property_id = uuid4()
        facility_id = uuid4()
        result = _dedupe_dashboard_properties(
            [
                row(property_id, "OTHER"),
                row(property_id, "PRO", facility_id=facility_id, already_drawn=Decimal("100.00")),
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].lender_type, "PRO")
        self.assertEqual(result[0].facility_id, facility_id)

    def test_dashboard_dedupe_prefers_non_other_sheet_row(self) -> None:
        property_id = uuid4()
        result = _dedupe_dashboard_properties(
            [
                row(property_id, "OTHER"),
                row(property_id, "SCU", stage="FOUNDATION"),
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].lender_type, "SCU")

    def test_lender_card_total_is_sum_of_draw_now_column(self) -> None:
        result = _summary(
            [
                row(
                    uuid4(),
                    "PRO",
                    already_drawn=Decimal("365000.00"),
                    draw_eligible=Decimal("55000.00"),
                ),
                row(
                    uuid4(),
                    "PRO",
                    already_drawn=Decimal("0"),
                    draw_eligible=Decimal("125000.00"),
                    flag="NO_STATEMENT",
                ),
            ]
        )

        self.assertEqual(result.PRO.total_drawable, Decimal("180000.00"))

    def test_missing_from_latest_statement_blocks_pro_draw(self) -> None:
        property_id = uuid4()
        facility_id = uuid4()
        source = defaultdict(
            lambda: None,
            {
                "property_id": property_id,
                "facility_id": facility_id,
                "address": "217 Woodland Way",
                "lender_type": "PRO",
                "stage_clean": "LOCKUP",
                "total_facility": Decimal("400000.00"),
                "already_drawn": Decimal("0"),
                "draw_eligible_override": None,
                "status": "active",
            },
        )

        result = _property_from_row(
            source,
            pro_statement_status="missing_from_statement",
        )

        self.assertEqual(result.flag, "MISSING_FROM_STATEMENT")
        self.assertIsNone(result.draw_eligible)
        self.assertIn("missing from the latest PRO statement", result.formula)

    def test_manual_override_unblocks_facility_missing_from_statement(self) -> None:
        property_id = uuid4()
        facility_id = uuid4()
        source = defaultdict(
            lambda: None,
            {
                "property_id": property_id,
                "facility_id": facility_id,
                "address": "76-100 Grande Pointe Meadows Blvd – SPEC",
                "lender_type": "PRO",
                "stage_clean": "FOUNDATION",
                "total_facility": Decimal("390000.00"),
                "already_drawn": Decimal("0"),
                "draw_eligible_override": Decimal("125000.00"),
                "status": "active",
            },
        )

        result = _property_from_row(
            source,
            pro_statement_status="missing_from_statement",
        )

        self.assertEqual(result.draw_eligible, Decimal("125000.00"))
        self.assertEqual(result.cumulative_entitled, Decimal("125000.00"))
        self.assertEqual(result.draw_eligible_override, Decimal("125000.00"))
        self.assertEqual(result.flag, "STATEMENT_OVERRIDE")
        self.assertIn("Manual PRO Draw Now override", result.formula)


if __name__ == "__main__":
    unittest.main()
