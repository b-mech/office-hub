from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from app.financing.engines.pro import ProFacility
from app.financing.engines.pro import ProTransaction
from app.financing.engines.pro import compute_ledger


SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "pro_seed_2026-06.json"


class ProEngineTest(unittest.TestCase):
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
