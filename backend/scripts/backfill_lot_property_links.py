"""Audit/backfill core.lots.property_id from canonical address matches.

Dry-run is the default. Pass --apply only after the preflight report has been reviewed.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from app.core.addresses import normalize_address
from app.core.database import AsyncSessionLocal


@dataclass(frozen=True)
class AddressRow:
    id: UUID
    address: str
    property_id: UUID | None = None


async def run(*, apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        lot_rows = (
            await db.execute(
                text(
                    """
                    SELECT id, COALESCE(civic_address, legal_description_normalized, '') AS address, property_id
                    FROM core.lots
                    ORDER BY id
                    """
                )
            )
        ).mappings().all()
        property_rows = (
            await db.execute(text("SELECT id, address FROM core.properties ORDER BY id"))
        ).mappings().all()

        lots = [AddressRow(id=row["id"], address=row["address"], property_id=row["property_id"]) for row in lot_rows]
        properties = [AddressRow(id=row["id"], address=row["address"]) for row in property_rows]
        properties_by_key: dict[str, list[AddressRow]] = defaultdict(list)
        for property_row in properties:
            properties_by_key[normalize_address(property_row.address).canonical_key].append(property_row)

        matches: list[tuple[AddressRow, AddressRow, str]] = []
        ambiguous: list[tuple[AddressRow, list[AddressRow], str]] = []
        unmatched: list[tuple[AddressRow, str]] = []
        for lot in lots:
            key = normalize_address(lot.address).canonical_key
            candidates = properties_by_key.get(key, [])
            if len(candidates) == 1:
                matches.append((lot, candidates[0], key))
            elif len(candidates) > 1:
                ambiguous.append((lot, candidates, key))
            else:
                unmatched.append((lot, key))

        print(
            f"LOTS={len(lots)} PROPERTIES={len(properties)} "
            f"LINKED={sum(lot.property_id is not None for lot in lots)} "
            f"UNLINKED={sum(lot.property_id is None for lot in lots)} "
            f"CONFIDENT_UNIQUE={len(matches)} AMBIGUOUS={len(ambiguous)} UNMATCHED={len(unmatched)}"
        )
        print("MATCHED_REPORT")
        for lot, property_row, key in matches:
            print(
                f"{lot.id}\t{lot.address}\tcanonical={key}\t"
                f"property={property_row.id}:{property_row.address}"
            )
        print("AMBIGUOUS_REPORT")
        for lot, candidates, key in ambiguous:
            candidate_text = " | ".join(f"{item.id}:{item.address}" for item in candidates)
            print(f"{lot.id}\t{lot.address}\tcanonical={key}\tcandidates={candidate_text}")
        print("UNMATCHED_REPORT")
        for lot, key in unmatched:
            print(f"{lot.id}\t{lot.address}\tcanonical={key}\treason=no canonical-key match")

        if apply:
            applied = 0
            for lot, property_row, _key in matches:
                if lot.property_id is not None:
                    continue
                result = await db.execute(
                    text(
                        """
                        UPDATE core.lots
                        SET property_id = :property_id, updated_at = now()
                        WHERE id = :lot_id AND property_id IS NULL
                        """
                    ),
                    {"lot_id": lot.id, "property_id": property_row.id},
                )
                applied += result.rowcount
            await db.commit()
            print(f"APPLIED={applied}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
