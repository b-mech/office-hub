from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch
from uuid import uuid4

from app.services import financing
from app.services.sheets_sync import SYNC_CONFLICT
from app.services.sheets_sync import _conflicting_stage_keys
from app.services.sheets_sync import _parse_stage_rows
from app.services.sheets_sync import _stage_value
from app.services.sheets_sync import sync_from_sheet


class _Result:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value

    def all(self) -> object:
        return self.value


class _AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> bool:
        return False


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


class SheetsSyncAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_group_stage_row_preserves_build_group_target(self) -> None:
        group_id = uuid4()
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result({"property_id": None, "build_group_id": group_id}),
                    _Result("DRYWALL"),
                    _Result(),
                ]
            )
        )
        row = {
            "address_raw": "22/24 Oak Meadow Drive – SPEC",
            "banker_raw": "RSU",
            "lender_type": "RSU",
            "sold_or_spec": "SPEC",
            "stage_clean": "DRYWALL",
            "client_name": None,
            "build_start": None,
            "possession_date": None,
        }

        with (
            patch.object(financing, "get_or_create_property", AsyncMock()) as get_property,
            patch.object(financing, "record_stage_change", AsyncMock()) as record_change,
        ):
            created = await financing.upsert_stage_row(db, row)  # type: ignore[arg-type]

        self.assertFalse(created)
        get_property.assert_not_awaited()
        record_change.assert_awaited_once_with(
            db,
            property_id=None,
            build_group_id=group_id,
            incoming_stage="DRYWALL",
            synced_at=record_change.await_args.kwargs["synced_at"],
        )
        upsert_params = db.execute.await_args_list[2].args[1]
        self.assertIsNone(upsert_params["property_id"])
        self.assertEqual(group_id, upsert_params["build_group_id"])

    async def test_group_target_survives_a_source_address_format_change(self) -> None:
        group_id = uuid4()
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _Result(None),
                    _Result([{"id": group_id, "display_name": "22/24 Oak Meadow Drive"}]),
                ]
            )
        )

        with patch.object(financing, "get_or_create_property", AsyncMock()) as get_property:
            target = await financing.get_or_create_stage_target(  # type: ignore[arg-type]
                db,
                "22-24 Oak Meadow Drive – SPEC",
            )

        self.assertEqual((None, group_id, False), target)
        get_property.assert_not_awaited()

    async def test_failed_row_uses_savepoint_and_does_not_cancel_later_rows(self) -> None:
        rows = [
            {"Address": "1 Test Way", "Stage": "FOUNDATION"},
            {"Address": "2 Test Way", "Stage": "LOCKUP"},
            {"Address": "3 Test Way", "Stage": "DRYWALL"},
        ]
        db = SimpleNamespace(
            begin=lambda: _AsyncContext(),
            begin_nested=lambda: _AsyncContext(),
            execute=AsyncMock(return_value=SimpleNamespace(rowcount=0)),
        )

        with (
            patch("app.services.sheets_sync._fetch_rows", AsyncMock(return_value=rows)),
            patch(
                "app.services.sheets_sync.upsert_stage_row",
                AsyncMock(side_effect=[True, ValueError("bad grouped row"), False]),
            ),
        ):
            result = await sync_from_sheet(db)  # type: ignore[arg-type]

        self.assertEqual(2, result["synced"])
        self.assertEqual(1, result["created_properties"])
        self.assertEqual(["Row 3: bad grouped row"], result["errors"])


if __name__ == "__main__":
    unittest.main()
