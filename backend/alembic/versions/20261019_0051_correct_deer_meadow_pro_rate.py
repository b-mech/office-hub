"""Correct Deer Meadow PRO rate and refresh affected cached balances.

Revision ID: 20261019_0051
Revises: 20261016_0050
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision: str = "20261019_0051"
down_revision: str | None = "20261016_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEER_FACILITY = "6d463d98-f1c8-4963-9bb2-88b6d037366c"


def upgrade() -> None:
    bind = op.get_bind()
    facility = bind.execute(sa.text("""
        SELECT annual_rate FROM core.lender_facilities WHERE id=:facility
    """), {"facility": DEER_FACILITY}).scalar_one()
    cheque = bind.execute(sa.text("""
        SELECT amount FROM core.facility_transactions
        WHERE facility_id=:facility AND reference ILIKE '%47662%' AND txn_type='draw'
    """), {"facility": DEER_FACILITY}).scalar_one()
    if facility != Decimal("0.11500") or cheque != Decimal("125000.00"):
        raise RuntimeError("Deer Meadow rate correction preflight failed")

    bind.execute(sa.text("""
        UPDATE core.lender_facilities
        SET annual_rate=0.11000, updated_at=now()
        WHERE id=:facility
    """), {"facility": DEER_FACILITY})
    bind.execute(sa.text("""
        INSERT INTO core.audit_log(schema_name,table_name,record_id,action,old_data,new_data)
        VALUES ('core','lender_facilities',CAST(:facility AS uuid),'UPDATE',
                json_build_object('annual_rate',0.11500),
                json_build_object('annual_rate',0.11000,
                  'basis','PRO August and September pages print 11.00%; August ending balance reconciles at 11.00%'))
    """), {"facility": DEER_FACILITY})

    # Both values are produced by the PRO ledger engine with the corrected
    # $125,000 July cheque. The September $79,100 draw remains unapproved.
    bind.execute(sa.text("""
        UPDATE documents.facility_statement_snapshots
        SET computed_balance=CASE reported_period_end_date
                WHEN DATE '2026-08-06' THEN 231233.14
                WHEN DATE '2026-09-06' THEN 233352.78
            END,
            delta=CASE reported_period_end_date
                WHEN DATE '2026-08-06' THEN 231233.14 - reported_period_end_balance
                WHEN DATE '2026-09-06' THEN 233352.78 - reported_period_end_balance
            END,
            reconciliation_status=CASE reported_period_end_date
                WHEN DATE '2026-08-06' THEN 'matched'
                WHEN DATE '2026-09-06' THEN 'new_draws_detected'
            END
        WHERE facility_id=:facility
          AND reported_period_end_date IN (DATE '2026-08-06',DATE '2026-09-06')
    """), {"facility": DEER_FACILITY})


def downgrade() -> None:
    raise RuntimeError("This audited production data correction is intentionally irreversible")
