from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4
import unittest

from app.schemas.financing import ClientDrawRequestOut
from app.services.financing import _client_request_index
from app.services.financing import _client_schedule_validation_notes
from app.services.financing import _clean_stage_key


class ClientDrawsTest(unittest.TestCase):
    def test_request_index_only_counts_active_statuses(self) -> None:
        property_id = uuid4()
        schedule_id = uuid4()
        active = ClientDrawRequestOut(
            id=uuid4(),
            property_id=property_id,
            schedule_id=schedule_id,
            draw_items=[{"seq": 2}],
            amount=Decimal("1000.00"),
            prepared_at=datetime.now(),
            status="prepared",
        )
        cancelled = ClientDrawRequestOut(
            id=uuid4(),
            property_id=property_id,
            schedule_id=schedule_id,
            draw_items=[{"seq": 3}],
            amount=Decimal("1000.00"),
            prepared_at=datetime.now(),
            status="cancelled",
        )

        index = _client_request_index([active, cancelled])

        self.assertIn(2, index)
        self.assertNotIn(3, index)

    def test_validation_requires_source_pages_on_amounts(self) -> None:
        notes = _client_schedule_validation_notes(
            Decimal("100000.00"),
            [{"seq": 1, "amount": "100000.00", "source_page": None}],
            [],
        )

        self.assertIn("Missing source page", notes or "")

    def test_validation_flags_purchase_price_mismatch(self) -> None:
        notes = _client_schedule_validation_notes(
            Decimal("100000.00"),
            [{"seq": 1, "amount": "90000.00", "source_page": 3}],
            [],
        )

        self.assertIn("not purchase price", notes or "")

    def test_stage_key_cleaning_default_denies_unknown_values(self) -> None:
        self.assertEqual("DRYWALL", _clean_stage_key("drywall"))
        self.assertIsNone(_clean_stage_key("rough-ins"))


if __name__ == "__main__":
    unittest.main()
