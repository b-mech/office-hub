"""Add lender-confirmed PRO draw availability overrides.

Revision ID: 20260724_0014
Revises: 20260724_0013
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0014"
down_revision: str | None = "20260724_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lender_facilities",
        sa.Column("draw_eligible_override", sa.Numeric(12, 2)),
        schema="core",
    )
    op.execute(
        """
        UPDATE core.lender_facilities
        SET draw_eligible_override = 235000.00,
            updated_at = now()
        WHERE facility_key = 'PRO-28-GLENEAGLES'
        """
    )


def downgrade() -> None:
    op.drop_column(
        "lender_facilities",
        "draw_eligible_override",
        schema="core",
    )
