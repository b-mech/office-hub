"""Correct two PRO rates confirmed by consecutive printed reports.

Revision ID: 20261019_0052
Revises: 20261019_0051
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision: str = "20261019_0052"
down_revision: str | None = "20261019_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACILITIES = (
    "fdcc4cfa-dc94-4b43-9ff0-2541d7942451",  # 114 Froese Crescent
    "fc3c0309-af18-44f7-9819-3378cc4e59b5",  # 28 Gleneagles Street
)


def upgrade() -> None:
    bind = op.get_bind()
    for facility_id in FACILITIES:
        rate = bind.execute(sa.text("""
            SELECT annual_rate FROM core.lender_facilities WHERE id=:facility
        """), {"facility": facility_id}).scalar_one()
        if rate != Decimal("0.11500"):
            raise RuntimeError(f"PRO rate correction preflight failed for {facility_id}")
        bind.execute(sa.text("""
            UPDATE core.lender_facilities SET annual_rate=0.11000, updated_at=now()
            WHERE id=:facility
        """), {"facility": facility_id})
        bind.execute(sa.text("""
            INSERT INTO core.audit_log(schema_name,table_name,record_id,action,old_data,new_data)
            VALUES ('core','lender_facilities',CAST(:facility AS uuid),'UPDATE',
                    json_build_object('annual_rate',0.11500),
                    json_build_object('annual_rate',0.11000,
                      'basis','August and September PRO pages both print 11.00%; transaction simulation reconciles to printed final balance'))
        """), {"facility": facility_id})


def downgrade() -> None:
    raise RuntimeError("This audited production data correction is intentionally irreversible")
