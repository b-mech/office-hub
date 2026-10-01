#!/usr/bin/env python3
"""Audit or backfill financing-property keys with the current normalizer."""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

from sqlalchemy import select

from app.core.addresses import normalize_address
from app.core.database import AsyncSessionLocal
from app.models.financing import Property


async def run(*, execute: bool) -> None:
    async with AsyncSessionLocal() as db:
        properties = list((await db.scalars(select(Property).order_by(Property.address))).all())
        changes: list[tuple[Property, str]] = []
        groups: dict[str, list[Property]] = defaultdict(list)
        for property_row in properties:
            canonical_key = normalize_address(property_row.address).canonical_key
            groups[canonical_key].append(property_row)
            if property_row.canonical_address_key != canonical_key:
                changes.append((property_row, canonical_key))

        collisions = {
            key: rows for key, rows in groups.items() if key and len(rows) > 1
        }
        print(f"properties={len(properties)} changes={len(changes)} collisions={len(collisions)}")
        for property_row, canonical_key in changes:
            print(
                f"CHANGE {property_row.id} | {property_row.address} | "
                f"{property_row.canonical_address_key} -> {canonical_key}"
            )
        for key, rows in sorted(collisions.items()):
            print(
                f"COLLISION {key} | "
                + " | ".join(f"{row.id}:{row.address}" for row in rows)
            )

        if not execute:
            await db.rollback()
            return
        for property_row, canonical_key in changes:
            property_row.canonical_address_key = canonical_key
        await db.commit()
        print(f"committed={len(changes)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(execute=args.execute))


if __name__ == "__main__":
    main()
