from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

from app.services import financing
from app.services.sheets_sync import CANONICAL_LENDER_IDS
from app.services.sheets_sync import DUPLICATE_PRO_AUTO_LENDER_ID
from app.services.sheets_sync import SYNC_CONFLICT
from app.services.sheets_sync import _conflicting_stage_keys
from app.services.sheets_sync import _parse_date
from app.services.sheets_sync import _parse_stage_rows
from app.services.sheets_sync import _parse_stage_table
from app.services.sheets_sync import _stage_value
from app.services.sheets_sync import canonical_lender_id
from app.services.sheets_sync import classify_sheet_lender
from app.services.sheets_sync import is_plausible_street_address
from app.services.sheets_sync import plan_facility_lender_updates
from app.services.sheets_sync import resolve_lender_fields
from app.services.sheets_sync import resolve_sheet_sync_options
from app.services.sheets_sync import sync_from_sheet


# Real tracker layout: A address_key, B Address, C Build Start, D Client Possession,
# E Banker (Robert), F Banker (Nicholas — source of truth), G Sold or Spec.
TRACKER_HEADERS = [
    "address_key",
    "Address",
    "Build Start",
    "Client Possession",
    "Banker ",
    "Banker ",
    "Sold or Spec",
    "LAST UPDATE JULY 8TH",
]


def _tracker_row(
    address: str,
    *,
    address_key: str = "",
    build: str = "2026-06-22",
    possession: str = "2027-04-01",
    banker_e: str = "",
    banker_f: str = "",
    sold: str = "SPEC",
    stage: str = "FRAME",
) -> list[str]:
    return [
        address_key or address,
        address,
        build,
        possession,
        banker_e,
        banker_f,
        sold,
        stage,
    ]


def _sheet(*data_rows: list[str], headers: list[str] | None = None) -> list[list[str]]:
    return [
        ["", "", "", "", "Robert ONLY", "NICHOLAS ONLY", "", ""],
        list(headers or TRACKER_HEADERS),
        *data_rows,
    ]


class _Result:
    def __init__(self, value: object = None) -> None:
        self.value = value
        rows = value if isinstance(value, list) else ([] if value is None else [value])
        self.rowcount = len(rows) if isinstance(value, list) else (0 if value is None else 1)

    def mappings(self) -> "_Result":
        return self

    def one_or_none(self) -> object:
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value

    def scalar_one_or_none(self) -> object:
        value = self.one_or_none()
        if isinstance(value, dict):
            return next(iter(value.values()))
        return value

    def all(self) -> object:
        if self.value is None:
            return []
        if isinstance(self.value, list):
            return self.value
        return [self.value]


class _AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> bool:
        return False


class FakeDB:
    def __init__(
        self,
        existing_rows: list[dict[str, Any]] | None = None,
        missing: list[Any] | None = None,
        facilities: list[dict[str, Any]] | None = None,
    ):
        self.existing_rows = existing_rows or []
        self.missing = missing or []
        self.facilities = facilities or []
        self.calls: list[tuple[str, Any]] = []
        self.writes: list[tuple[str, Any]] = []

    def begin(self) -> _AsyncContext:
        return _AsyncContext()

    def begin_nested(self) -> _AsyncContext:
        return _AsyncContext()

    async def execute(self, stmt: Any, params: Any = None) -> _Result:
        sql = str(getattr(stmt, "text", stmt))
        self.calls.append((sql, params))
        upper = sql.upper()
        if any(keyword in upper for keyword in ("INSERT", "UPDATE", "DELETE")):
            self.writes.append((sql, params))
        if "FROM documents.construction_stage_sync" in sql and "DELETE" not in upper:
            if "NOT IN" in upper:
                missing_rows = [
                    item if isinstance(item, (list, tuple)) else (item,)
                    for item in self.missing
                ]
                # _missing_sync_addresses reads row[0]
                return _Result([(item[0] if isinstance(item, (list, tuple)) else item,) if not isinstance(item, dict) else item for item in self.missing])
            return _Result(self.existing_rows)
        if "FROM core.lender_facilities" in sql and "DELETE" not in upper and "UPDATE" not in upper:
            property_id = None
            if isinstance(params, dict):
                property_id = params.get("property_id")
            rows = [
                row
                for row in self.facilities
                if property_id is None or str(row.get("property_id")) == str(property_id)
            ]
            return _Result(rows)
        if "UPDATE core.lender_facilities" in sql:
            if isinstance(params, dict):
                for row in self.facilities:
                    if str(row.get("id")) == str(params.get("id")) and row.get("lender_id") is None:
                        row["lender_id"] = params.get("lender_id")
            return _Result([])
        if "DELETE" in upper and "RETURNING" in upper:
            return _Result([(address,) for address in self.missing])
        return _Result([])


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

    def test_locked_tracker_possession_date_is_read_without_marking_possession_taken(self) -> None:
        rows = _parse_stage_rows([{
            "Address": "52 Ash Cove - SPEC",
            "Client Possession": "**30-Oct-2026**",
            "Sold or Spec": "SOLD",
        }])
        self.assertEqual("2026-10-30", rows[0]["possession_date"].isoformat())
        self.assertTrue(rows[0]["possession_date_locked"])

    def test_conflicting_duplicate_canonical_stage_rows_are_flagged(self) -> None:
        rows = _parse_stage_rows(
            [
                {"Address": "104 Lynne Lane", "LAST UPDATE JULY 8TH": "DRYWALL"},
                {"Address": "104 Lyne Lane", "LAST UPDATE JULY 8TH": "LOCKUP"},
            ]
        )

        self.assertEqual({"104 LYNNE LANE"}, _conflicting_stage_keys(rows))
        self.assertEqual(SYNC_CONFLICT, "SYNC_CONFLICT")

    def test_duplicate_banker_headers_read_column_f_not_e(self) -> None:
        values = _sheet(
            _tracker_row("10 Oak Street", banker_e="SCU", banker_f="Pro Auto"),
        )
        rows, warnings = _parse_stage_table(values)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["banker_raw"], "Pro Auto")
        self.assertFalse(warnings)

    def test_renamed_f_header_still_reads_f(self) -> None:
        headers = list(TRACKER_HEADERS)
        headers[5] = "NICHOLAS ONLY"
        values = _sheet(
            _tracker_row("10 Oak Street", banker_e="Robert bank", banker_f="Stride"),
            headers=headers,
        )
        rows, warnings = _parse_stage_table(values)
        self.assertEqual(rows[0]["banker_raw"], "Stride")
        self.assertFalse(warnings)

    def test_renamed_f_header_warns_when_it_does_not_look_like_bank(self) -> None:
        headers = list(TRACKER_HEADERS)
        headers[5] = "Misc Notes"
        values = _sheet(
            _tracker_row("10 Oak Street", banker_e="SCU", banker_f="ProAuto"),
            headers=headers,
        )
        rows, warnings = _parse_stage_table(values)
        self.assertEqual(rows[0]["banker_raw"], "ProAuto")
        self.assertEqual(len(warnings), 1)
        self.assertIn("column F", warnings[0])
        self.assertIn("Misc Notes", warnings[0])

    def test_never_falls_back_to_column_e_when_f_is_blank(self) -> None:
        values = _sheet(
            _tracker_row("10 Oak Street", banker_e="SCU", banker_f=""),
            ["11 Oak Street", "11 Oak Street", "2026-06-22", "2027-04-01", "PRO"],
        )
        rows, _warnings = _parse_stage_table(values)
        by_address = {row["address_raw"]: row for row in rows}
        self.assertEqual(by_address["10 Oak Street"]["banker_raw"], "")
        self.assertEqual(by_address["11 Oak Street"]["banker_raw"], "")


class LenderClassificationTests(unittest.TestCase):
    def test_question_marks_are_uncertain_and_not_classified_as_scu(self) -> None:
        raw, lender_type, kind = classify_sheet_lender("??STRIDE??  SCU??")
        self.assertEqual(raw, "??STRIDE??  SCU??")
        self.assertIsNone(lender_type)
        self.assertEqual(kind, "uncertain")

    def test_pro_auto_spellings_normalize_to_pro(self) -> None:
        for value in ("Pro Auto", "ProAuto", "pro auto", "PRO"):
            _raw, lender_type, kind = classify_sheet_lender(value)
            self.assertEqual(kind, "confirmed", value)
            self.assertEqual(lender_type, "PRO", value)

    def test_blank_f_does_not_overwrite_existing_lender(self) -> None:
        resolved = resolve_lender_fields("", existing_raw="ProAuto", existing_type="PRO")
        self.assertEqual(resolved["resolution"], "preserved")
        self.assertEqual(resolved["banker_raw"], "ProAuto")
        self.assertEqual(resolved["lender_type"], "PRO")
        self.assertFalse(resolved["changed"])

    def test_uncertain_f_does_not_overwrite_existing_lender(self) -> None:
        resolved = resolve_lender_fields(
            "??STRIDE??  SCU??",
            existing_raw="SCU",
            existing_type="SCU",
        )
        self.assertEqual(resolved["resolution"], "preserved")
        self.assertEqual(resolved["banker_raw"], "SCU")
        self.assertEqual(resolved["lender_type"], "SCU")
        self.assertFalse(resolved["changed"])

    def test_uncertain_f_on_new_row_is_lender_to_confirm(self) -> None:
        resolved = resolve_lender_fields("--> STRIDE?", existing_raw=None, existing_type=None)
        self.assertEqual(resolved["resolution"], "lender_to_confirm")
        self.assertEqual(resolved["banker_raw"], "--> STRIDE?")
        self.assertIsNone(resolved["lender_type"])
        self.assertTrue(resolved["changed"])

    def test_confirmed_f_records_a_change(self) -> None:
        resolved = resolve_lender_fields("Pro Auto", existing_raw="SCU", existing_type="SCU")
        self.assertEqual(resolved["resolution"], "updated")
        self.assertEqual(resolved["banker_raw"], "Pro Auto")
        self.assertEqual(resolved["lender_type"], "PRO")
        self.assertTrue(resolved["changed"])


class SheetSyncOptionTests(unittest.TestCase):
    def test_api_defaults_dry_run_true_and_deletes_off(self) -> None:
        options = resolve_sheet_sync_options()
        self.assertTrue(options["dry_run"])
        self.assertFalse(options["delete_missing"])
        self.assertIsNone(options["address_keys"])
        self.assertEqual(options["bank_column"], "F")

    def test_query_overrides_body(self) -> None:
        options = resolve_sheet_sync_options(
            query_dry_run=False,
            body={"dry_run": True, "delete_missing": True, "address_keys": ["10 Oak Street"]},
        )
        self.assertFalse(options["dry_run"])
        self.assertTrue(options["delete_missing"])
        self.assertIn("10 Oak Street", options["address_keys"] or [])

    def test_body_can_set_dry_run_false_when_query_omitted(self) -> None:
        options = resolve_sheet_sync_options(body={"dry_run": False})
        self.assertFalse(options["dry_run"])


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
            patch.object(financing, "activate_from_construction_stage", AsyncMock()) as activate,
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
        activate.assert_awaited_once_with(
            db,
            property_id=None,
            address=row["address_raw"],
            sold_or_spec="SPEC",
        )

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
        values = _sheet(
            _tracker_row("1 Test Way", banker_f="PRO", stage="FOUNDATION"),
            _tracker_row("2 Test Way", banker_f="SCU", stage="LOCKUP"),
            _tracker_row("3 Test Way", banker_f="CLIENT", stage="DRYWALL"),
        )
        db = FakeDB()

        with (
            patch("app.services.sheets_sync._fetch_sheet_values", AsyncMock(return_value=values)),
            patch(
                "app.services.sheets_sync.upsert_stage_row",
                AsyncMock(side_effect=[(True, False), ValueError("bad grouped row"), (False, False)]),
            ),
        ):
            result = await sync_from_sheet(db, dry_run=False)  # type: ignore[arg-type]

        self.assertEqual(2, result["synced"])
        self.assertEqual(1, result["created_properties"])
        self.assertEqual(["Row 4: bad grouped row"], result["errors"])
        self.assertFalse(result["dry_run"])

    async def test_dry_run_writes_nothing_and_returns_manifest(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="Pro Auto", sold="SPEC"))
        db = FakeDB()
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(side_effect=AssertionError("upsert during dry_run"))),
            patch("app.services.sheets_sync.get_or_create_stage_target", new=AsyncMock(return_value=(None, None, True))),
            patch("app.services.sheets_sync.activate_from_construction_stage", new=AsyncMock(return_value=True)),
        ):
            result = await sync_from_sheet(db)  # default dry_run=True

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["created_properties"], 1)
        self.assertEqual(result["stale_deleted"], 0)
        # A brand-new property has no id yet, so activation is not previewed here.
        self.assertEqual([item["kind"] for item in result["manifest"]], ["insert", "create_property"])
        self.assertEqual(db.writes, [])
        self.assertTrue(all("DELETE" not in sql.upper() for sql, _params in db.calls))

    async def test_dry_run_includes_activation_when_property_already_exists(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="Pro Auto", sold="SPEC"))
        db = FakeDB()
        property_id = uuid4()
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(side_effect=AssertionError("upsert during dry_run"))),
            patch("app.services.sheets_sync.get_or_create_stage_target", new=AsyncMock(return_value=(property_id, None, False))),
            patch("app.services.sheets_sync.activate_from_construction_stage", new=AsyncMock(return_value=True)),
        ):
            result = await sync_from_sheet(db, dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual([item["kind"] for item in result["manifest"]], ["insert", "activate"])
        self.assertEqual(db.writes, [])

    async def test_allowlist_limits_rows(self) -> None:

        values = _sheet(
            _tracker_row("10 Oak Street", banker_f="Pro Auto"),
            _tracker_row("20 Pine Avenue", banker_f="SCU"),
        )
        upsert = AsyncMock(return_value=(False, False))
        db = FakeDB()
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=upsert),
        ):
            result = await sync_from_sheet(db, dry_run=False, address_keys=["10 Oak Street"])

        self.assertEqual(result["synced"], 1)
        upsert.assert_awaited_once()
        self.assertEqual(upsert.await_args.args[1]["address_raw"], "10 Oak Street")
        self.assertEqual({item["address_raw"] for item in result["manifest"]}, {"10 Oak Street"})

    async def test_deletes_are_disabled_by_default(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="Pro Auto"))
        db = FakeDB(
            existing_rows=[{"address_raw": "99 Missing Road", "banker_raw": "SCU", "lender_type": "SCU"}],
            missing=["99 Missing Road"],
        )
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(return_value=(False, False))),
        ):
            result = await sync_from_sheet(db, dry_run=False)

        self.assertFalse(result["delete_missing"])
        self.assertEqual(result["stale_deleted"], 0)
        self.assertTrue(all("DELETE" not in sql.upper() for sql, _params in db.writes))
        self.assertTrue(all(item["kind"] != "delete" for item in result["manifest"]))

    async def test_delete_missing_only_when_requested(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="Pro Auto"))
        db = FakeDB(missing=["99 Missing Road"])
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(return_value=(False, False))),
        ):
            result = await sync_from_sheet(db, dry_run=False, delete_missing=True)

        self.assertTrue(result["delete_missing"])
        self.assertEqual(result["stale_deleted"], 1)
        self.assertTrue(any("DELETE" in sql.upper() for sql, _params in db.writes))
        self.assertTrue(any(item["kind"] == "delete" and item["address_raw"] == "99 Missing Road" for item in result["manifest"]))

    async def test_allowlist_skips_deletes_even_when_requested(self) -> None:
        values = _sheet(
            _tracker_row("10 Oak Street", banker_f="Pro Auto"),
            _tracker_row("20 Pine Avenue", banker_f="SCU"),
        )
        db = FakeDB(missing=["99 Missing Road"])
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(return_value=(False, False))),
        ):
            result = await sync_from_sheet(
                db,
                dry_run=False,
                delete_missing=True,
                address_keys=["10 Oak Street"],
            )

        self.assertFalse(result["delete_missing"])
        self.assertEqual(result["stale_deleted"], 0)
        self.assertTrue(any("allowlist" in warning for warning in result["warnings"]))
        self.assertTrue(all("DELETE" not in sql.upper() for sql, _params in db.writes))

    async def test_apply_preserves_existing_lender_when_f_is_blank(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f=""))
        existing = {
            "address_raw": "10 Oak Street",
            "banker_raw": "ProAuto",
            "lender_type": "PRO",
            "property_id": None,
            "build_group_id": None,
        }
        db = FakeDB(existing_rows=[existing])
        upsert = AsyncMock(return_value=(False, False))
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=upsert),
        ):
            await sync_from_sheet(db, dry_run=False)

        payload = upsert.await_args.args[1]
        self.assertEqual(payload["banker_raw"], "ProAuto")
        self.assertEqual(payload["lender_type"], "PRO")

    async def test_dry_run_uncertain_f_manifest_marks_lender_preserved(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="??  SCU??"))
        existing = {
            "address_raw": "10 Oak Street",
            "banker_raw": "Steinbach Credit Union",
            "lender_type": "SCU",
        }
        db = FakeDB(existing_rows=[existing])
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(side_effect=AssertionError("upsert"))),
            patch("app.services.sheets_sync.get_or_create_stage_target", new=AsyncMock(return_value=(None, None, False))),
            patch("app.services.sheets_sync.activate_from_construction_stage", new=AsyncMock(return_value=False)),
        ):
            result = await sync_from_sheet(db, dry_run=True)

        update = next(item for item in result["manifest"] if item["kind"] == "update")
        self.assertEqual(update["lender_resolution"], "preserved")
        self.assertEqual(update["banker_raw"], "Steinbach Credit Union")
        self.assertEqual(update["lender_type"], "SCU")
        self.assertEqual(db.writes, [])


class DateParsingTests(unittest.TestCase):
    def test_markdown_asterisks_and_missing_comma_space(self) -> None:
        expected = __import__("datetime").date(2026, 2, 18)
        for raw in (
            "**February 18,2026**",
            "**February 18, 2026**",
            "February 18,2026",
            "*February 18, 2026*",
            "  **February  18,2026**  ",
        ):
            self.assertEqual(expected, _parse_date(raw), raw)

    def test_existing_date_formats_still_parse(self) -> None:
        from datetime import date

        self.assertEqual(date(2026, 11, 13), _parse_date("13-Nov-2026"))
        self.assertEqual(date(2027, 5, 1), _parse_date("2027-05-01"))
        self.assertEqual(date(2027, 8, 1), _parse_date("1-Aug-2027"))
        self.assertEqual(date(2026, 10, 8), _parse_date("October 8, 2026"))


class AddressJunkTests(unittest.TestCase):
    def test_junk_address_rows_are_rejected(self) -> None:
        junk = [
            "#REF!",
            "LEGEND - Column C status options:",
            "LEGEND - Column E Banker",
            "1.",
            "2.",
            "3.",
            "1 - Fully Confirmed",
            "2 - Nicholas Suggestion - Add 2 ??",
            "3 - Robert Agreed - Add 1 ?",
            "Nicholas Robert Bryce",
            "PreProduction Planning",
        ]
        for address in junk:
            self.assertFalse(is_plausible_street_address(address), address)

        values = _sheet(*[_tracker_row(address, banker_f="SCU") for address in junk])
        parsed, warnings = _parse_stage_table(values, bank_column="F")
        self.assertEqual([], parsed)
        self.assertEqual([], warnings)

    def test_real_addresses_with_notes_are_kept(self) -> None:
        keep = [
            "87 Grove Crescent – SHOWHOME",
            "48 Ash Cove. client doesnt want early possession??",
            "14 Grove Cresent ( Fall 2027)",
            "24-100 Grande Pointe Meadows",
            "141/145 Ramona Gallos – SPEC",
            "10 Oak Street",
        ]
        for address in keep:
            self.assertTrue(is_plausible_street_address(address), address)


class CanonicalLenderIdTests(unittest.TestCase):
    def test_pro_auto_and_scu_map_to_canonical_lender_ids(self) -> None:
        self.assertEqual(CANONICAL_LENDER_IDS["PRO"], UUID("52642c0d-3af6-4d23-a3bd-734e84585ea1"))
        self.assertEqual(CANONICAL_LENDER_IDS["SCU"], UUID("18c6d406-231c-41d9-8541-ef0044cba2d3"))
        for raw in ("Pro Auto", "ProAuto", "PRO"):
            resolved = resolve_lender_fields(raw)
            self.assertEqual("PRO", resolved["lender_type"])
            self.assertEqual(CANONICAL_LENDER_IDS["PRO"], resolved["lender_id"])
        resolved = resolve_lender_fields("SCU")
        self.assertEqual("SCU", resolved["lender_type"])
        self.assertEqual(CANONICAL_LENDER_IDS["SCU"], resolved["lender_id"])
        self.assertIsNone(canonical_lender_id("OTHER"))
        self.assertIsNone(canonical_lender_id("CLIENT"))

    def test_duplicate_pro_auto_facility_is_not_retargeted(self) -> None:
        facility_id = uuid4()
        property_id = uuid4()
        planned = plan_facility_lender_updates(
            [
                {
                    "id": facility_id,
                    "property_id": property_id,
                    "lender_id": DUPLICATE_PRO_AUTO_LENDER_ID,
                    "lender_type": "PRO",
                }
            ],
            "PRO",
        )
        self.assertEqual(
            [
                {
                    "kind": "lender_id_preserved_duplicate",
                    "facility_id": str(facility_id),
                    "property_id": str(property_id),
                    "lender_type": "PRO",
                    "existing_lender_id": str(DUPLICATE_PRO_AUTO_LENDER_ID),
                    "canonical_lender_id": str(CANONICAL_LENDER_IDS["PRO"]),
                }
            ],
            planned,
        )

    def test_null_matching_facility_is_assigned_canonical_id(self) -> None:
        facility_id = uuid4()
        property_id = uuid4()
        planned = plan_facility_lender_updates(
            [
                {
                    "id": facility_id,
                    "property_id": property_id,
                    "lender_id": None,
                    "lender_type": "SCU",
                }
            ],
            "SCU",
        )
        self.assertEqual("set_lender_id", planned[0]["kind"])
        self.assertEqual(str(CANONICAL_LENDER_IDS["SCU"]), planned[0]["lender_id"])
        self.assertIsNone(planned[0]["existing_lender_id"])


class SheetsSyncFollowupAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_lists_junk_existing_and_does_not_delete(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="SCU"))
        existing = [
            {"address_raw": "10 Oak Street", "banker_raw": "SCU", "lender_type": "SCU"},
            {"address_raw": "#REF!", "banker_raw": None, "lender_type": None},
            {
                "address_raw": "2 - Nicholas Suggestion - Add 2 ??",
                "banker_raw": None,
                "lender_type": None,
            },
            {
                "address_raw": "LEGEND - Column E Banker",
                "banker_raw": None,
                "lender_type": None,
            },
        ]
        db = FakeDB(existing_rows=existing, missing=["#REF!", "LEGEND - Column E Banker"])
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(side_effect=AssertionError("upsert"))),
            patch("app.services.sheets_sync.get_or_create_stage_target", new=AsyncMock(return_value=(None, None, False))),
            patch("app.services.sheets_sync.activate_from_construction_stage", new=AsyncMock(return_value=False)),
        ):
            result = await sync_from_sheet(db, dry_run=True, delete_missing=True)

        junk = [item for item in result["manifest"] if item["kind"] == "junk_existing"]
        deletes = [item for item in result["manifest"] if item["kind"] == "delete"]
        self.assertEqual(
            {
                "#REF!",
                "2 - Nicholas Suggestion - Add 2 ??",
                "LEGEND - Column E Banker",
            },
            {item["address_raw"] for item in junk},
        )
        self.assertEqual([], deletes)
        self.assertEqual(0, result["stale_deleted"])
        self.assertEqual([], db.writes)
        self.assertTrue(all("DELETE" not in sql.upper() for sql, _params in db.calls))

    async def test_dry_run_plans_canonical_facility_lender_id(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="ProAuto"))
        property_id = uuid4()
        facility_id = uuid4()
        existing = {
            "address_raw": "10 Oak Street",
            "banker_raw": "ProAuto",
            "lender_type": "PRO",
            "property_id": property_id,
        }
        db = FakeDB(
            existing_rows=[existing],
            facilities=[
                {
                    "id": facility_id,
                    "property_id": property_id,
                    "lender_id": None,
                    "lender_type": "PRO",
                }
            ],
        )
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=AsyncMock(side_effect=AssertionError("upsert"))),
            patch(
                "app.services.sheets_sync.get_or_create_stage_target",
                new=AsyncMock(return_value=(property_id, None, False)),
            ),
            patch("app.services.sheets_sync.activate_from_construction_stage", new=AsyncMock(return_value=False)),
        ):
            result = await sync_from_sheet(db, dry_run=True)

        update = next(item for item in result["manifest"] if item["kind"] == "update")
        self.assertEqual(str(CANONICAL_LENDER_IDS["PRO"]), update["lender_id"])
        assignment = next(item for item in result["manifest"] if item["kind"] == "set_lender_id")
        self.assertEqual(str(facility_id), assignment["facility_id"])
        self.assertEqual(str(CANONICAL_LENDER_IDS["PRO"]), assignment["lender_id"])
        self.assertEqual([], db.writes)

    async def test_apply_sets_null_facility_lender_id_to_canonical(self) -> None:
        values = _sheet(_tracker_row("10 Oak Street", banker_f="SCU"))
        property_id = uuid4()
        facility_id = uuid4()
        existing = {
            "address_raw": "10 Oak Street",
            "banker_raw": "SCU",
            "lender_type": "SCU",
            "property_id": property_id,
        }
        facilities = [
            {
                "id": facility_id,
                "property_id": property_id,
                "lender_id": None,
                "lender_type": "SCU",
            }
        ]
        db = FakeDB(existing_rows=[existing], facilities=facilities)
        upsert = AsyncMock(return_value=(False, False))
        with (
            patch("app.services.sheets_sync._fetch_sheet_values", new=AsyncMock(return_value=values)),
            patch("app.services.sheets_sync.upsert_stage_row", new=upsert),
        ):
            result = await sync_from_sheet(db, dry_run=False)

        self.assertEqual(str(CANONICAL_LENDER_IDS["SCU"]), facilities[0]["lender_id"])
        self.assertTrue(any("UPDATE core.lender_facilities" in sql for sql, _params in db.writes))
        assignment = next(item for item in result["manifest"] if item["kind"] == "set_lender_id")
        self.assertEqual(str(CANONICAL_LENDER_IDS["SCU"]), assignment["lender_id"])
        payload = upsert.await_args.args[1]
        self.assertEqual(CANONICAL_LENDER_IDS["SCU"], payload["lender_id"])


if __name__ == "__main__":
    unittest.main()
