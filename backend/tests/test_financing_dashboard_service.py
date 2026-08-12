from __future__ import annotations

from decimal import Decimal
from uuid import uuid4
import unittest

from app.schemas.financing import FinancingPropertyOut
from app.services.financing import _assert_no_duplicate_pro_properties
from app.services.financing import _dedupe_dashboard_properties
from app.services.financing import _summary


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


if __name__ == "__main__":
    unittest.main()
