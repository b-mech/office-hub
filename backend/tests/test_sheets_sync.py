from __future__ import annotations

import unittest

from app.services.sheets_sync import SYNC_CONFLICT
from app.services.sheets_sync import _conflicting_stage_keys
from app.services.sheets_sync import _parse_stage_rows
from app.services.sheets_sync import _stage_value


class SheetsSyncTest(unittest.TestCase):
    def test_stage_reads_latest_update_header_by_name(self) -> None:
        row = {
            "Address": "104 Lynne Lane",
            "LAST UPDATE JULY 8TH": "DRYWALL",
            "stage_clean": "",
        }

        self.assertEqual("DRYWALL", _stage_value(row))

    def test_stage_prefers_explicit_stage_clean_when_present(self) -> None:
        row = {
            "Address": "675 Community Row",
            "LAST UPDATE JULY 8TH": "NA",
            "stage_clean": "FOUNDATION",
        }

        self.assertEqual("FOUNDATION", _stage_value(row))

    def test_parse_stage_rows_uses_exact_known_sheet_strings(self) -> None:
        rows = [
            {
                "Address": "104 Lynne Lane",
                "LAST UPDATE JULY 8TH": "DRYWALL",
                "Banker": "CLIENT",
                "Sold or Spec": "SOLD",
            },
            {
                "Address": "675 Community Row",
                "LAST UPDATE JULY 8TH": "NA",
                "Banker": "CLIENT",
                "Sold or Spec": "SOLD",
            },
        ]

        parsed = _parse_stage_rows(rows)

        self.assertEqual("104 LYNNE LANE", parsed[0]["canonical_key"])
        self.assertEqual("DRYWALL", parsed[0]["stage_clean"])
        self.assertEqual("675 COMMUNITY ROW", parsed[1]["canonical_key"])
        self.assertEqual("NA", parsed[1]["stage_clean"])

    def test_conflicting_duplicate_canonical_stage_rows_are_flagged(self) -> None:
        rows = _parse_stage_rows(
            [
                {"Address": "104 Lynne Lane", "LAST UPDATE JULY 8TH": "DRYWALL"},
                {"Address": "104 Lyne Lane", "LAST UPDATE JULY 8TH": "LOCKUP"},
            ]
        )

        self.assertEqual({"104 LYNNE LANE"}, _conflicting_stage_keys(rows))
        self.assertEqual(SYNC_CONFLICT, "SYNC_CONFLICT")


if __name__ == "__main__":
    unittest.main()
