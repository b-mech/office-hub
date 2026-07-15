from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.addresses import normalize_address  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await _backfill_properties(db)
        await _backfill_facilities(db)
        await _ensure_development_properties(db)
        linked, ambiguous, unmatched = await _auto_link_pro(db)
        await db.commit()

    print(f"linked: {len(linked)}")
    for name in linked:
        print(f"  LINKED {name}")
    print(f"ambiguous: {len(ambiguous)}")
    for name, key, count in ambiguous:
        print(f"  AMBIGUOUS {name} [{key}] candidates={count}")
    print(f"unmatched: {len(unmatched)}")
    for name, key in unmatched:
        print(f"  UNMATCHED {name} [{key}]")


async def _backfill_properties(db) -> None:
    rows = (await db.execute(text("SELECT id, address FROM core.properties"))).mappings().all()
    for row in rows:
        normalized = normalize_address(row["address"])
        await db.execute(
            text(
                """
                UPDATE core.properties
                SET canonical_address_key = :key,
                    property_type = COALESCE(property_type, :property_type),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "key": normalized.canonical_key,
                "property_type": "development" if normalized.canonical_key.startswith("DEV:") else "lot",
            },
        )


async def _backfill_facilities(db) -> None:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, property_name
                FROM core.lender_facilities
                WHERE COALESCE(lender, lender_type) = 'PRO'
                  AND property_name IS NOT NULL
                """
            )
        )
    ).mappings().all()
    for row in rows:
        normalized = normalize_address(row["property_name"])
        await db.execute(
            text(
                """
                UPDATE core.lender_facilities
                SET canonical_address_key = :key,
                    facility_scope = CASE WHEN :is_development THEN 'development' ELSE facility_scope END,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": row["id"], "key": normalized.canonical_key, "is_development": normalized.canonical_key.startswith("DEV:")},
        )
        await db.execute(
            text(
                """
                INSERT INTO core.facility_aliases (facility_id, alias)
                VALUES (:facility_id, :alias)
                ON CONFLICT (alias) DO UPDATE SET facility_id = EXCLUDED.facility_id
                """
            ),
            {"facility_id": row["id"], "alias": row["property_name"]},
        )


async def _ensure_development_properties(db) -> None:
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT property_name, canonical_address_key
                FROM core.lender_facilities
                WHERE COALESCE(lender, lender_type) = 'PRO'
                  AND canonical_address_key LIKE 'DEV:%'
                """
            )
        )
    ).mappings().all()
    for row in rows:
        await db.execute(
            text(
                """
                INSERT INTO core.properties (address, address_normalized, canonical_address_key, property_type)
                VALUES (:address, :address_normalized, :canonical_address_key, 'development')
                ON CONFLICT (address_normalized) DO UPDATE SET
                    canonical_address_key = EXCLUDED.canonical_address_key,
                    property_type = 'development',
                    updated_at = now()
                """
            ),
            {
                "address": row["property_name"],
                "address_normalized": row["canonical_address_key"],
                "canonical_address_key": row["canonical_address_key"],
            },
        )


async def _auto_link_pro(db) -> tuple[list[str], list[tuple[str, str, int]], list[tuple[str, str]]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, property_name, canonical_address_key
                FROM core.lender_facilities
                WHERE COALESCE(lender, lender_type) = 'PRO'
                  AND property_id IS NULL
                  AND canonical_address_key IS NOT NULL
                ORDER BY property_name
                """
            )
        )
    ).mappings().all()
    linked: list[str] = []
    ambiguous: list[tuple[str, str, int]] = []
    unmatched: list[tuple[str, str]] = []
    for row in rows:
        candidates = (
            await db.execute(
                text("SELECT id FROM core.properties WHERE canonical_address_key = :key"),
                {"key": row["canonical_address_key"]},
            )
        ).scalars().all()
        if len(candidates) == 1:
            await db.execute(
                text("UPDATE core.lender_facilities SET property_id = :property_id, status = 'active', updated_at = now() WHERE id = :id"),
                {"property_id": candidates[0], "id": row["id"]},
            )
            linked.append(row["property_name"])
        elif len(candidates) > 1:
            ambiguous.append((row["property_name"], row["canonical_address_key"], len(candidates)))
        else:
            await db.execute(
                text("UPDATE core.lender_facilities SET status = 'needs_link', updated_at = now() WHERE id = :id"),
                {"id": row["id"]},
            )
            unmatched.append((row["property_name"], row["canonical_address_key"]))
    return linked, ambiguous, unmatched


if __name__ == "__main__":
    asyncio.run(main())
