"""Book the twelve explicitly approved PRO statement transactions atomically.

Run without --apply for a rollback-only rehearsal. The exact statement proposal,
date, amount, and cheque for every row must still match the live review queue.
"""

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import bindparam, text

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.financing import _reconcile_snapshot, _refresh_statement_status  # noqa: E402


BACKUP = Path("/home/officehub/backups/pro-reconciliation/officehub_pre_pro_12_approvals_20261020_185551_UTC.dump")
BACKUP_SHA256 = "931a77e8231cad80d28c06d7291ca3b1bd4d52db522b9eb4f6f17086f5e81dbf"
STATEMENTS = {
    "2026-06": UUID("7e1c7629-2fa7-4960-8224-e55ab55efbdf"),
    "2026-07": UUID("f9b2568b-e180-4eb7-9ed3-bbc2832aa6e3"),
    "2026-08": UUID("07be2a9c-7469-4a00-844b-40ec913cee5c"),
    "2026-09": UUID("dcab5d46-7a2f-4a3b-a98e-e87a8adda916"),
}
# snapshot, period, kind, date, amount, cheque
APPROVED = [
    ("b2634544-4068-4895-978b-64bb657dbe86", "2026-07", "draw", "2026-07-27", "70000.00", "47658"),
    ("818b2f34-8212-4cb1-8a92-591e6ec806e0", "2026-07", "draw", "2026-07-27", "55000.00", "47659"),
    ("d6c51e91-c0e4-4cc7-8307-8a27326abe45", "2026-08", "draw", "2026-07-27", "400000.00", "47660"),
    ("109255a9-4391-4ce2-a33f-6cccc71671e5", "2026-09", "draw", "2026-09-03", "79100.00", "47682"),
    ("2a095a5e-facb-40a7-a7bd-59b16ce01fb7", "2026-09", "draw", "2026-09-03", "65000.00", "47680"),
    ("83f64654-4e88-4267-9135-380bd0578139", "2026-09", "draw", "2026-09-03", "81800.00", "47681"),
    ("2a2d2222-23d3-4fe9-91c2-7a732cf7a1f6", "2026-09", "draw", "2026-09-03", "125000.00", "47683"),
    ("1ea9d841-99af-4b9c-9f30-2e32f387b221", "2026-09", "draw", "2026-09-21", "200000.00", "47698"),
    ("2a2d2222-23d3-4fe9-91c2-7a732cf7a1f6", "2026-09", "draw", "2026-09-21", "100000.00", "47700"),
    ("267836e7-8fab-465a-9ae8-dee51f03f43c", "2026-09", "draw", "2026-09-21", "100000.00", "47701"),
    ("e53017c0-f19a-4c09-84b8-1220b8f32e81", "2026-09", "repayment", "2026-09-22", "11394.86", "12190"),
    ("b078cbfb-7fb9-49f7-addf-7330101fdcd4", "2026-09", "repayment", "2026-09-22", "11394.86", "12190"),
]


def cheque(reference):
    match = re.search(r"\d{5}", reference or "")
    return match.group() if match else None


def proposal_key(snapshot_id, kind, proposal):
    return (
        str(snapshot_id), kind,
        str(proposal.get("date") or proposal.get("txn_date")),
        Decimal(str(proposal["amount"])), cheque(proposal.get("reference")),
    )


async def run(apply):
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest() != BACKUP_SHA256:
        raise RuntimeError("Verified pre-write backup is missing or changed")
    expected = Counter((sid, kind, when, Decimal(amount), number) for sid, _, kind, when, amount, number in APPROVED)
    assert len(APPROVED) == 12 and sum(Decimal(a) for _, _, k, _, a, _ in APPROVED if k == "draw") == Decimal("1275900.00")
    assert sum(Decimal(a) for _, _, k, _, a, _ in APPROVED if k == "repayment") == Decimal("22789.72")

    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock(20261020, 12)"))
        rows = (await db.execute(text("""
            SELECT s.*, l.period, l.lender
            FROM documents.facility_statement_snapshots s
            JOIN documents.lender_statements l ON l.id=s.statement_id
            WHERE l.id IN :ids
            ORDER BY l.period, s.matched_property_name
            FOR UPDATE OF s
        """).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(STATEMENTS.values())})).mappings().all()
        by_id = {str(row["id"]): row for row in rows}
        for sid, period, *_ in APPROVED:
            row = by_id.get(sid)
            if not row or row["statement_id"] != STATEMENTS[period] or row["lender"] != "PRO" or not row["facility_id"]:
                raise RuntimeError(f"Statement ownership or facility changed for {sid}")
        proposals = []
        for row in rows:
            for item in row["new_draws_detected"] or []:
                proposals.append((row, "draw", item))
            for item in (row["parse_payload"] or {}).get("proposed_repayments") or []:
                proposals.append((row, "repayment", item))
        actual = Counter(proposal_key(row["id"], kind, item) for row, kind, item in proposals)
        if actual != expected:
            raise RuntimeError(f"Review queue changed: missing={list((expected-actual).elements())}, extra={list((actual-expected).elements())}")

        facility_ids = {row["facility_id"] for row, _, _ in proposals}
        existing = (await db.execute(text("""
            SELECT facility_id, txn_date, txn_type, amount, reference
            FROM core.facility_transactions WHERE facility_id IN :ids
            FOR UPDATE
        """).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(facility_ids)})).mappings().all()
        for row, kind, item in proposals:
            when = date.fromisoformat(str(item.get("date") or item.get("txn_date")))
            amount = Decimal(str(item["amount"]))
            number = cheque(item.get("reference"))
            if any(t["facility_id"] == row["facility_id"] and t["txn_type"] == kind and (
                (t["txn_date"] == when and t["amount"] == amount)
                or (number and cheque(t["reference"]) == number)
            ) for t in existing):
                raise RuntimeError(f"Core already contains {kind} {number} on {row['matched_property_name']}")
            await db.execute(text("""
                INSERT INTO core.facility_transactions
                    (facility_id, txn_date, txn_type, amount, reference, source, statement_id)
                VALUES (:facility_id, :txn_date, :txn_type, :amount, :reference, 'pro_reconciliation', :statement_id)
            """), {
                "facility_id": row["facility_id"], "txn_date": when, "txn_type": kind,
                "amount": amount, "reference": item.get("reference"), "statement_id": row["statement_id"],
            })
        await db.execute(text("""
            UPDATE core.lender_facilities SET draw_eligible_override=NULL,
                updated_at=CASE WHEN draw_eligible_override IS NOT NULL THEN now() ELSE updated_at END
            WHERE id IN :ids
        """).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(facility_ids)})
        affected = [row for row in rows if row["facility_id"] in facility_ids]
        for row in affected:
            await _reconcile_snapshot(db, row["id"])
        for statement_id in STATEMENTS.values():
            await _refresh_statement_status(db, statement_id)

        balances = (await db.execute(text("""
            SELECT l.period, s.matched_property_name, s.reported_period_end_date,
                   s.reported_period_end_balance, s.computed_balance, s.delta, s.reconciliation_status
            FROM documents.facility_statement_snapshots s
            JOIN documents.lender_statements l ON l.id=s.statement_id
            WHERE s.facility_id IN :ids AND l.id IN :statement_ids
            ORDER BY l.period, s.matched_property_name
        """).bindparams(bindparam("ids", expanding=True), bindparam("statement_ids", expanding=True)),
            {"ids": tuple(facility_ids), "statement_ids": tuple(STATEMENTS.values())})).mappings().all()
        statuses = (await db.execute(text("""
            SELECT period, status FROM documents.lender_statements
            WHERE id IN :ids ORDER BY period
        """).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(STATEMENTS.values())})).mappings().all()
        discrepancies = (await db.execute(text("""
            SELECT l.period, d.display_name, d.details, d.status
            FROM documents.lender_statement_discrepancies d
            JOIN documents.lender_statements l ON l.id=d.statement_id
            WHERE l.id IN :ids ORDER BY l.period, d.display_name
        """).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(STATEMENTS.values())})).mappings().all()
        remaining = (await db.execute(text("""
            SELECT l.period, s.matched_property_name, s.reconciliation_status,
                   s.new_draws_detected, s.parse_payload->'proposed_repayments' AS proposed_repayments
            FROM documents.facility_statement_snapshots s
            JOIN documents.lender_statements l ON l.id=s.statement_id
            WHERE l.id IN :ids AND s.reconciliation_status NOT IN ('matched', 'acknowledged')
            ORDER BY l.period, s.matched_property_name
        """).bindparams(bindparam("ids", expanding=True)), {"ids": tuple(STATEMENTS.values())})).mappings().all()
        print(json.dumps({
            "mode": "applied" if apply else "dry_run_rolled_back",
            "booked_count": len(proposals),
            "draw_total": "1275900.00", "repayment_total": "22789.72",
            "balances": [dict(r) for r in balances],
            "statement_statuses": [dict(r) for r in statuses],
            "internal_missing": [dict(r) for r in discrepancies],
            "remaining_snapshot_reviews": [dict(r) for r in remaining],
        }, default=str, indent=2))
        if apply:
            await db.commit()
        else:
            await db.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Commit all twelve approved transactions")
    args = parser.parse_args()
    asyncio.run(run(args.apply))
