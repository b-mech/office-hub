from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from app.financing.parsers.pro_statement import parse_statement_text


class ProStatementParserTest(unittest.TestCase):
    def test_september_regression_pages_parse_clean_with_visible_repairs(self) -> None:
        text = (Path(__file__).parent / "fixtures" / "pro_2026_09_regression_pages.txt").read_text()

        statements = parse_statement_text(text, period="2026-09")

        self.assertEqual(7, len(statements))
        self.assertTrue(all(not statement.validation_errors for statement in statements))
        self.assertEqual(Decimal("22789.72"), sum((item.amount for statement in statements for item in statement.repayments), Decimal("0.00")))
        repairs = [repair for statement in statements for repair in statement.repairs]
        self.assertTrue(any(repair.field == "draw_amount" and repair.raw_ocr == "-700,000.00" and repair.inferred_value == "100000.00" for repair in repairs))
        self.assertTrue(any(repair.field == "repayment_amount" and repair.raw_ocr == "141,394.86" and repair.inferred_value == "11394.86" for repair in repairs))
        self.assertEqual([], [repair for repair in repairs if repair.field == "interest"])
        self.assertEqual(date(2026, 9, 22), statements[0].repayments[0].txn_date)
        self.assertEqual(date(2026, 9, 3), statements[3].draws[-1].txn_date)
        self.assertEqual(Decimal("431999.59"), statements[5].period_end_balance)

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

        self.assertTrue(statements[0].validation_errors)
        self.assertEqual(Decimal("100900.00"), statements[0].period_end_balance)

    def test_corrupt_totals_without_printed_support_remain_parse_error(self) -> None:
        text = """
        Connection Homes - 150 Rosybloom Lane
        AMOUNT BORROWED $150,000.00 03/12/2026
        ANNUAL INTEREST RATE 11.00%
        03/30/2026 18 1 .00 11.0000 798.39 -400,798.39 250,798.39 -700,000.00 798.39 Chq#4676
        Totals for schedule .00 798.39 -700,798.39 -700,000.00
        """
        statement = parse_statement_text(text)[0]
        self.assertEqual(Decimal("250798.39"), statement.period_end_balance)
        self.assertTrue(statement.validation_errors)

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

    def test_ocr_equals_separators_do_not_discard_only_schedule_row(self) -> None:
        text = """
        Connection Homes Inc - 5 Gray Place
        AMOUNT BORROWED: $169,900.00 advanced on 9/2/2026
        ANNUAL INTEREST RATE: = 11.00% (Monthly compounding) (360)
        9/21/2026 19 1 00 = 11.0000 986.36 = -100,986.36 270,886.36 -100,000.00 986.36 Chq#47701
        Totals for schedule 00 986.36 -100,986.36 -100,000.00
        """

        statement = parse_statement_text(text, period="2026-09")[0]

        self.assertEqual(Decimal("100000.00"), statement.draws[0].amount)
        self.assertEqual([], statement.validation_errors)

    def test_ocr_comma_in_rate_token_does_not_hide_draw(self) -> None:
        text = """
        PRIVI Holdings - 114 Froese
        AMOUNT BORROWED: $312,000.00 advanced on 7/3/2026
        ANNUAL INTEREST RATE: = 11.00% (Monthly compounding) (360)
        7/27/2026 24 1 .00 41,0000 645.81 -400,645.81 712,645.81 -400,000.00 645.81 chq#47660
        8/20/2026 24 2 .00 41.0000 5,057.49 -5,057.49 717,703.30 .00 5,703.30
        Totals for schedule .00 5,703.30 -405,703.30 -400,000.06
        """

        statement = parse_statement_text(text, period="2026-08")[0]

        self.assertEqual(Decimal("400000.00"), statement.draws[0].amount)
        self.assertEqual([], statement.validation_errors)

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

    def test_verified_august_page_repairs_are_visible(self) -> None:
        woodland = """
        Connection Homes - 64 Woodland Way, West St Paul, MB
        AMOUNT BORROWED: $165,000.00 advanced on 3/12/2026
        ANNUAL INTEREST RATE: 11.00% (Monthly compounding)
        3/30/2026 18 1 .00 11.0000 878.23 -100,878.23 265,878.23 -100,000.00 878.23 Chq#4675
        5/27/2026 15 4 .00 11.0000 1,194.68 -101,194.68 370,541.56 -100,000.00 5,541.56 Chq#47610
        7/27/2026 15 7 .00 11.0000 1,666.44 -121,666.44 497,373.80 -120,000.00 12,373.80 Chq#47661
        8/12/2026 16 8 .00 11.0000 2,353.17 -2,353.17 499,726.97 .00 14,726,597
        Totals for schedule .00 414,726.97 -334,726.97 -320,000.00
        """
        deer = """
        Connection Homes - 10 Deer Meadow Run
        AMOUNT BORROWED: $104,900.00 advanced on 7/6/2026
        ANNUAL INTEREST RATE: 11.00% (Monthly compounding)
        7/27/2026 21 1 .00 11.0000 651.40 -125,651.40 230,554.40 -125,060.00 651.40 Chq#47662
        8/6/2026 10 2 .00 11.0000 681.74 -681.74 234,233.14 .00 1,333.14
        Totals for schedule .00 1,333.14 -126,333.14 -125,000.00
        """
        woodland_row = parse_statement_text(woodland, period="2026-08")[0]
        deer_row = parse_statement_text(deer, period="2026-08")[0]
        self.assertEqual([], woodland_row.validation_errors)
        self.assertEqual([], deer_row.validation_errors)
        self.assertEqual(Decimal("499726.97"), woodland_row.period_end_balance)
        self.assertEqual(Decimal("231233.14"), deer_row.period_end_balance)
        self.assertTrue(any(r.raw_ocr == "414,726.97" and r.inferred_value == "14726.97" for r in woodland_row.repairs))
        self.assertTrue(any(r.raw_ocr == "234233.14" and r.inferred_value == "231233.14" for r in deer_row.repairs))

    def test_june_year_subtotal_is_not_a_transaction(self) -> None:
        text = """
        Connection Homes Inc. - Waterside Dev - Parkview Pointe West St Paul
        AMOUNT BORROWED: $405,300.00 advanced on 5/22/2025
        ANNUAL INTEREST RATE: 11.50% (Monthly compounding)
        12/22/2025 30 7 .00 11.5000 4,112.88 -4,112.88 433,283.16 .00 27,983.16
        Totatis for 2025 .00 27,983.16 -27,983.16 .00
        6/22/2026 31 13 .00 11.5000 4,355.11 -4,355.11 458,801.51 .00 53,501.51
        Totals for schedule .00 53,501.51 -53,501.51 .00
        """
        statement = parse_statement_text(text, period="2026-06")[0]
        self.assertEqual([], statement.validation_errors)
        self.assertEqual(Decimal("458801.51"), statement.period_end_balance)

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

    def test_adjacent_elapsed_days_repair_valid_but_wrong_draw_date(self) -> None:
        text = """
        Connection Homes - 150 Rosybloom Lane
        AMOUNT BORROWED $150,000.00 03/12/2026
        ANNUAL INTEREST RATE 11.00%
        5/12/2026 30 3 .00 11.0000 2,307.82 -2,307.82 254,070.30 .00 4,070.30
        6/27/2026 15 4 .00 11.0000 1,426.92 -101,426.92 355,197.22 -100,000.00 5,197.22 Cha#47616
        6/12/2026 16 5 .00 11.0000 1,680.50 -1,680.50 356,877.72 .00 6,877.72
        """
        statement = parse_statement_text(text)[0]
        self.assertEqual(date(2026, 5, 27), statement.draws[0].txn_date)
        self.assertTrue(any(
            repair.field == "transaction_date" and repair.raw_ocr == "6/27/2026"
            and repair.inferred_value == "2026-05-27"
            for repair in statement.repairs
        ))


if __name__ == "__main__":
    unittest.main()
