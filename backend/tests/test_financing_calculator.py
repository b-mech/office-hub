from __future__ import annotations

from decimal import Decimal
import unittest

from app.services.financing_calculator import calculate_draw


class FinancingCalculatorTest(unittest.TestCase):
    def test_pro_lockup_draw_is_flat_one_hundred_thousand(self) -> None:
        result = calculate_draw(
            lender_type="PRO",
            stage="LOCKUP",
            total_facility=Decimal("554000.00"),
            opening_balance=None,
            already_drawn=Decimal("289000.00"),
        )

        self.assertEqual(Decimal("389000.00"), result.cumulative_entitled)
        self.assertEqual(Decimal("100000.00"), result.draw_eligible)
        self.assertIsNone(result.flag)
        self.assertIn("flat draw", result.formula)

    def test_pro_lockup_draw_is_capped_at_remaining_facility(self) -> None:
        result = calculate_draw(
            lender_type="PRO",
            stage="LOCKUP",
            total_facility=Decimal("350000.00"),
            opening_balance=None,
            already_drawn=Decimal("300000.00"),
        )

        self.assertEqual(Decimal("350000.00"), result.cumulative_entitled)
        self.assertEqual(Decimal("50000.00"), result.draw_eligible)

    def test_pro_drywall_draw_is_half_of_actual_remaining_after_lockup(self) -> None:
        result = calculate_draw(
            lender_type="PRO",
            stage="DRYWALL",
            total_facility=Decimal("309000.00"),
            opening_balance=None,
            already_drawn=Decimal("229900.00"),
        )

        self.assertEqual(Decimal("269450.00"), result.cumulative_entitled)
        self.assertEqual(Decimal("39550.00"), result.draw_eligible)
        self.assertIsNone(result.flag)
        self.assertIn("50% x remaining after LOCKUP", result.formula)

    def test_pro_drywall_draw_is_zero_when_facility_is_fully_drawn(self) -> None:
        result = calculate_draw(
            lender_type="PRO",
            stage="DRYWALL",
            total_facility=Decimal("485000.00"),
            opening_balance=None,
            already_drawn=Decimal("485000.00"),
        )

        self.assertEqual(Decimal("485000.00"), result.cumulative_entitled)
        self.assertEqual(Decimal("0.00"), result.draw_eligible)


if __name__ == "__main__":
    unittest.main()
