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


if __name__ == "__main__":
    unittest.main()
