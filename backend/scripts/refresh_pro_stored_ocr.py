"""Refresh the three stored PRO reports from their existing OCR extraction.

The default run rolls back. Pass --apply after reviewing its row changes and
verifying a database backup. This does not approve proposed transactions.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.financing.parsers.pro_statement import parse_statement_text
from app.services.financing import (
    _refresh_statement_status,
    _sync_statement_discrepancies,
    _upsert_statement_snapshot,
)


PERIODS = ("2026-06", "2026-08", "2026-09")


async def refresh(*, apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        statements = (
            await db.execute(
                text("""
                    SELECT id, period, parse_payload
                    FROM documents.lender_statements
                    WHERE lender='PRO' AND period IN ('2026-06','2026-08','2026-09')
                    ORDER BY period
                    FOR UPDATE
                """)
            )
        ).mappings().all()
        if tuple(row["period"] for row in statements) != PERIODS:
            raise RuntimeError("Expected exactly one stored PRO statement in each audited period")

        before = {
            (row["statement_id"], row["matched_property_name"]):
                (row["reconciliation_status"], row["reported_period_end_balance"], row["computed_balance"])
            for row in (
                await db.execute(text("""
                    SELECT statement_id, matched_property_name, reconciliation_status,
                           reported_period_end_balance, computed_balance
                    FROM documents.facility_statement_snapshots
                    WHERE statement_id = ANY(:ids)
                """), {"ids": [row["id"] for row in statements]})
            ).mappings()
        }
        for stored in statements:
            extraction = (stored["parse_payload"] or {}).get("extraction")
            if not extraction or not extraction.get("text"):
                raise RuntimeError(f"Missing stored OCR for {stored['period']}")
            parsed = parse_statement_text(extraction["text"], period=stored["period"])
            if any(item.validation_errors for item in parsed):
                failures = [(item.property_name, item.validation_errors) for item in parsed if item.validation_errors]
                raise RuntimeError(f"Parse errors in {stored['period']}: {failures}")
            snapshots = [
                await _upsert_statement_snapshot(db, stored["id"], item, index, extraction)
                for index, item in enumerate(parsed, start=1)
            ]
            await db.execute(text("""
                UPDATE documents.lender_statements
                SET status='parsed', parsed_at=now(), parse_payload=CAST(:payload AS jsonb)
                WHERE id=:id
            """), {
                "id": stored["id"],
                "payload": json.dumps({"pages": len(parsed), "snapshots": snapshots, "extraction": extraction}, default=str),
            })
            await _sync_statement_discrepancies(db, stored["id"])
            await _refresh_statement_status(db, stored["id"])
            print(f"{stored['period']}: {len(parsed)} pages, zero parse errors")

        after_rows = (
            await db.execute(text("""
                SELECT statement_id, matched_property_name, reconciliation_status,
                       reported_period_end_balance, computed_balance
                FROM documents.facility_statement_snapshots
                WHERE statement_id = ANY(:ids)
                ORDER BY matched_property_name
            """), {"ids": [row["id"] for row in statements]})
        ).mappings().all()
        for row in after_rows:
            old = before.get((row["statement_id"], row["matched_property_name"]))
            new = (row["reconciliation_status"], row["reported_period_end_balance"], row["computed_balance"])
            if old != new:
                print(f"{row['matched_property_name']}: {old} -> {new}")
        if apply:
            await db.commit()
            print("Committed refreshed snapshots. No transactions were approved.")
        else:
            await db.rollback()
            print("Dry run rolled back.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(refresh(apply=parser.parse_args().apply))
