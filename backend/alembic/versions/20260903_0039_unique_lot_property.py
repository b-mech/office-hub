"""Ensure a property can belong to only one lot.

Revision ID: 20260903_0039
Revises: 20260901_0038
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_0039"
down_revision: str | None = "20260901_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT property_id, count(*) AS lot_count
            FROM core.lots
            WHERE property_id IS NOT NULL
            GROUP BY property_id
            HAVING count(*) > 1
            ORDER BY property_id
            LIMIT 1
            """
        )
    ).mappings().first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce one lot per property: property "
            f"{duplicate['property_id']} is linked to {duplicate['lot_count']} lots"
        )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_core_lots_property_id_not_null
        ON core.lots (property_id)
        WHERE property_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_core_lots_property_id_not_null",
        table_name="lots",
        schema="core",
    )
