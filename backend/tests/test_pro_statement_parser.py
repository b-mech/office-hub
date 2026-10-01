from __future__ import annotations

from datetime import date
from decimal import Decimal
import unittest

from app.financing.parsers.pro_statement import parse_statement_text


class ProStatementParserTest(unittest.TestCase):
    def test_capitalization_only_row_is_not_a_draw(self) -> None:
        text = """
        Connection Homes Inc - 150 Rosybloom Lane, Ile des Chenes, MB
        AMOUNT BORROWED $100,000.00 06/01/2026
        ANNUAL INTEREST RATE 12.00%
        06/30/2026 29 1 $0.00 12.00% $953.42 -$953.42 $100,953.42 $0.00 $953.42
        """

        statements = parse_statement_text(text)

        self.assertEqual([], statements[0].draws)
        self.assertEqual([], statements[0].validation_errors)

    def test_negative_prepay_column_is_a_draw_with_reference(self) -> None:
        text = """
        Connection Homes Inc - 150 Rosybloom Lane, Ile des Chenes, MB
        AMOUNT BORROWED $100,000.00 06/01/2026
        ANNUAL INTEREST RATE 12.00%
        06/30/2026 29 1 $0.00 12.00% $953.42 -$953.42 $105,953.42 -$5,000.00 $953.42 Chq#06
        """

        statements = parse_statement_text(text)

        self.assertEqual(1, len(statements[0].draws))
        self.assertEqual(date(2026, 6, 30), statements[0].draws[0].txn_date)
        self.assertEqual(Decimal("5000.00"), statements[0].draws[0].amount)
        self.assertEqual("Chq#06", statements[0].draws[0].reference)
        self.assertEqual([], statements[0].validation_errors)

    def test_balance_identity_failure_is_reported(self) -> None:
        text = """
        Connection Homes Inc - 150 Rosybloom Lane, Ile des Chenes, MB
        AMOUNT BORROWED $100,000.00 06/01/2026
        ANNUAL INTEREST RATE 12.00%
        06/30/2026 29 1 $0.00 12.00% $953.42 -$953.42 $100,900.00 $0.00 $953.42
        """

        statements = parse_statement_text(text)

        self.assertEqual(1, len(statements[0].validation_errors))

    def test_ocr_row_without_currency_or_percent_symbols_is_parsed(self) -> None:
        text = """
        Connection Homes Inc - 2 Cardinal Way, Landmark, MB
        AMOUNT BORROWED: $86,900.00 advanced on 11/26/2025
        ANNUAL INTEREST RATE: 11.00% (Monthly compounding)
        12/26/2025 30 1 -00 11.0000 796.58 -796.58 87,696.58 00 796.58
        1/19/2026 24 2 -00 11.0000 622.36 -100,622.36 188,318.94 -100,000.00 1,418.94 Chq#47521
        """

        statements = parse_statement_text(text)

        self.assertEqual(date(2026, 1, 19), statements[0].period_end_date)
        self.assertEqual(Decimal("188318.94"), statements[0].period_end_balance)
        self.assertEqual(Decimal("100000.00"), statements[0].draws[0].amount)

    def test_ocr_row_with_detached_accumulated_interest_is_parsed(self) -> None:
        text = """
        Connection Homes - 64 Woodland Way, West St Paul, MB
        AMOUNT BORROWED: $165,000.00 advanced on 3/12/2026
        ANNUAL INTEREST RATE: 11.00% (Monthly compounding)
        3/30/2026 18 1 00 11.0000 878.23 -100,878.23 265,878.23 -100,000.00
        """

        statements = parse_statement_text(text)

        self.assertEqual(date(2026, 3, 30), statements[0].period_end_date)
        self.assertEqual(Decimal("100000.00"), statements[0].draws[0].amount)

    def test_statement_totals_drive_reported_principal_despite_ocr_noise(self) -> None:
        text = """
        Connection Homes - 64 Woodland Way, West St Paul, MB
        AMOUNT BORROWED: $165,000.00 advanced on 3/12/2026
        ANNUAL INTEREST RATE: 11.00% (Monthly compounding) (360)
        3/30/2026 18 1 .00 11.0000 878.23 -100,878.23 265,878.23 -100,000.60 878.23 PAP Chq#4675
        5/27/2026 15 4 .00 11.0000 1,194.68 -101,194.68 370,541.56 -100,000.00 5,541.56 chq#47610
        7/27/2026 15 7 .00 11.0000 1,666.44 -121,666.44 497,373.80 -120,000.00 12,373.80 chq#47661
        8/42/2026 16 8 .00 11.0000 2,353.17 -2,353.17 499,726.97 .00 14,726.97
        Totals for schedule .00 14,726.97 -334,726.97 -320,000.00
        """

        statement = parse_statement_text(text, period="2026-08")[0]

        self.assertEqual(date(2026, 8, 12), statement.period_end_date)
        self.assertEqual(Decimal("320000.00"), statement.total_drawn)
        self.assertEqual(Decimal("485000.00"), statement.reported_principal_drawn)
        self.assertEqual(Decimal("14726.97"), statement.reported_accrued_interest)
        self.assertEqual(Decimal("100000.00"), statement.draws[0].amount)

    def test_invalid_ocr_draw_date_is_repaired_from_common_zero_substitution(self) -> None:
        text = """
        Connection Homes Inc - 153 Ramona Gallos Way, Winnipeg, MB
        AMOUNT BORROWED: $140,000.00 advanced on 2/25/2026
        ANNUAL INTEREST RATE: 11.00% (Monthly compounding) (360)
        3/25/2026 28 1 .00 11.0000 1,283.33 -1,283.33 141,283.33 .00 1,283.33
        3/36/2026 5 2 .00 11.0000 208.89 -62,708.89 203,992.22 -62,500.00 1,492.22 chq#47571
        5/27/2026 2 5 .00 11.0000 122.68 -100,122.68 307,567.54 -100,000.00 5,067.54 chq#47615
        8/25/2026 31 8 .00 11.0000 2,869.61 -2,869.61 315,918.17 .00 13,418.17
        Totals for schedule .00 13,418.17 -175,918.17 -162,500.00
        """

        statement = parse_statement_text(text, period="2026-08")[0]

        self.assertEqual(date(2026, 3, 30), statement.draws[0].txn_date)
        self.assertEqual(Decimal("162500.00"), statement.total_drawn)
        self.assertEqual(Decimal("302500.00"), statement.reported_principal_drawn)


if __name__ == "__main__":
    unittest.main()
