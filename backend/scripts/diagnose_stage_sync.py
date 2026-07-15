from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import text

from app.core.addresses import normalize_address
from app.core.database import AsyncSessionLocal
from app.services.financing import get_dashboard
from app.services.sheets_sync import _fetch_rows
from app.services.sheets_sync import _parse_stage_rows
from app.services.sheets_sync import _value
from app.services.sheets_sync import sync_from_sheet


EXAMPLES = ("675 Community Row", "104 Lyne Lane")
SEARCH_TERMS = ("104", "LYNE", "LINE", "LANE", "675", "COMMUNITY")


def _row_address(row: dict[str, str]) -> str:
    return _value(row, "Address", "address", "address_raw", "address_key") or ""


def _row_stage(row: dict[str, str]) -> str:
    return _value(row, "stage_clean", "Stage Clean", "Stage") or ""


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = await _fetch_rows()
        sync_result = await sync_from_sheet(db)

        db_rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        css.id,
                        css.property_id,
                        css.address_raw,
                        css.stage_clean,
                        css.sold_or_spec,
                        css.lender_type,
                        css.last_synced_at,
                        p.address AS property_address,
                        p.canonical_address_key AS property_key
                    FROM documents.construction_stage_sync css
                    LEFT JOIN core.properties p ON p.id = css.property_id
                    ORDER BY css.address_raw
                    """
                )
            )
        ).mappings().all()

        properties = (
            await db.execute(
                text(
                    """
                    SELECT id, address, canonical_address_key
                    FROM core.properties
                    ORDER BY address
                    """
                )
            )
        ).mappings().all()

        dashboard = await get_dashboard(db)

    parsed_rows = _parse_stage_rows(rows)
    parsed_by_row = {row["row_number"]: row for row in parsed_rows}
    sheet_report = []
    raw_search_hits = []
    for index, row in enumerate(rows, start=2):
        row_text = " ".join(str(value) for value in row.values()).upper()
        if any(term in row_text for term in SEARCH_TERMS):
            raw_search_hits.append({"row_number": index, "row": row})
        parsed = parsed_by_row.get(index)
        address = parsed["address_raw"] if parsed else _row_address(row)
        if not address:
            continue
        key = parsed["canonical_key"] if parsed else normalize_address(address).canonical_key
        sheet_report.append(
            {
                "row_number": index,
                "address": address,
                "stage": parsed["stage_clean"] if parsed else _row_stage(row),
                "sold_or_spec": parsed["sold_or_spec"] if parsed else _value(row, "Sold or Spec", "sold_or_spec"),
                "canonical_key": key,
            }
        )

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sheet_report:
        by_key[item["canonical_key"]].append(item)

    property_key_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    property_id_index: dict[str, dict[str, Any]] = {}
    for prop in properties:
        property_id_index[str(prop["id"])] = dict(prop)
        if prop["canonical_address_key"]:
            property_key_index[prop["canonical_address_key"]].append(dict(prop))

    db_by_address = defaultdict(list)
    for row in db_rows:
        db_by_address[normalize_address(row["address_raw"]).canonical_key].append(dict(row))

    dashboard_by_key = defaultdict(list)
    for item in dashboard.properties:
        db_property = property_id_index.get(str(item.property_id), {})
        key = db_property.get("canonical_address_key") or normalize_address(item.address).canonical_key
        dashboard_by_key[key].append(item.model_dump(mode="json"))

    unmatched = []
    for key, sheet_items in by_key.items():
        if key.startswith("DEV:"):
            continue
        if key not in property_key_index:
            unmatched.append({"canonical_key": key, "sheet_rows": sheet_items})

    duplicate_conflicts = []
    for key, items in by_key.items():
        stages = {item["stage"] for item in items if item["stage"]}
        if len(items) > 1 and len(stages) > 1:
            duplicate_conflicts.append({"canonical_key": key, "sheet_rows": items})

    examples = []
    for example in EXAMPLES:
        example_key = normalize_address(example).canonical_key
        matching_sheet = [
            item
            for item in sheet_report
            if example.lower() in item["address"].lower()
            or item["canonical_key"] == example_key
        ]
        property_rows = property_key_index.get(example_key, [])
        examples.append(
            {
                "example": example,
                "expected_key": example_key,
                "sheet_rows": matching_sheet,
                "sync_rows_for_key": db_by_address.get(example_key, []),
                "property_rows_for_key": property_rows,
                "dashboard_rows_for_key": dashboard_by_key.get(example_key, []),
            }
        )

    print(
        json.dumps(
            {
                "sync_result": sync_result,
                "examples": examples,
                "raw_search_hits": raw_search_hits,
                "unmatched_sheet_stage_rows": unmatched,
                "duplicate_stage_conflicts": duplicate_conflicts,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
