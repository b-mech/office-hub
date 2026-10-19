from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from app.financing.engines.pro import ProFacility
from app.financing.engines.pro import ProTransaction
from app.financing.engines.pro import compute_ledger
from app.financing.engines.pro import balance_on


SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "pro_seed_2026-06.json"


class ProEngineTest(unittest.TestCase):
    def test_off_cycle_september_cheques_match_printed_balances(self) -> None:
        cases = [
            (
                ProFacility("deer", "Deer Meadow", "", Decimal("0.11"), date(2026, 7, 6), Decimal("104900.00")),
                [
                    ProTransaction(date(2026, 7, 27), "draw", Decimal("125000.00")),
                    ProTransaction(date(2026, 9, 3), "draw", Decimal("79100.00")),
                ],
                date(2026, 9, 6), Decimal("312533.88"),
            ),
            (
                ProFacility("templeton", "Templeton", "", Decimal("0.115"), date(2025, 5, 29), Decimal("473750.00")),
                [ProTransaction(date(2026, 9, 22), "repayment", Decimal("11394.86"))],
                date(2026, 9, 29), Decimal("540481.88"),
            ),
        ]
        for facility, transactions, as_of, printed in cases:
            with self.subTest(facility=facility.facility_key):
                self.assertEqual(printed, balance_on(facility, transactions, as_of))

    def test_june_statement_balances_match_to_the_penny(self) -> None:
        data = json.loads(SEED_PATH.read_text(), parse_float=Decimal)
        failures: list[str] = []

        for item in data["facilities"]:
            facility = ProFacility(
                facility_key=item["facility_key"],
                property_name=item["property_name"],
                borrower=item["borrower"],
                annual_rate=item["annual_rate"],
                original_advance_date=date.fromisoformat(item["original_advance"]["date"]),
                original_advance_amount=Decimal(item["original_advance"]["amount"]),
            )
            transactions = [
                ProTransaction(
                    txn_date=date.fromisoformat(draw["date"]),
                    txn_type="draw",
                    amount=Decimal(draw["amount"]),
                    reference=draw.get("reference"),
                )
                for draw in item.get("draws", [])
            ]

            for reported in item["reported_balances"]:
                event_date = date.fromisoformat(reported["date"])
                expected = Decimal(reported["balance"]).quantize(Decimal("0.01"))
                actual = compute_ledger(facility, transactions, event_date).balance_as_of
                if actual != expected:
                    failures.append(
                        f"{item['facility_key']} {event_date.isoformat()}: expected {expected}, got {actual}"
                    )

        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
