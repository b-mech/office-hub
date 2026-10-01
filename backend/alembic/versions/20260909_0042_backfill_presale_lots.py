"""Flag the initial presale lot roster.

Revision ID: 20260909_0042
Revises: 20260908_0041
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260909_0042"
down_revision: str | None = "20260908_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH presale_addresses(address) AS (
            VALUES
                ('154 RAMONA GALLOS WAY'),
                ('217 WOODLAND WAY'),
                ('48 WOODLAND WAY'),
                ('112 BUFFALO TRAIL'),
                ('43 MORNING GLORY WAY'),
                ('29 MORNING GLORY WAY'),
                ('256 MIDDLECHURCH'),
                ('53 SPRUCE COVE')
        ), normalized_lots AS (
            SELECT
                id,
                btrim(regexp_replace(upper(COALESCE(civic_address, '')), '[^A-Z0-9]+', ' ', 'g')) AS address
            FROM core.lots
        )
        UPDATE core.lots AS lot
        SET sale_type = 'presale'
        FROM normalized_lots, presale_addresses
        WHERE lot.id = normalized_lots.id
          AND (
              normalized_lots.address = presale_addresses.address
              OR normalized_lots.address LIKE presale_addresses.address || ' %'
          )
        """
    )


def downgrade() -> None:
    # Presale status can be changed by users after this backfill. It is not safe
    # to clear those operational flags during a schema downgrade.
    pass
