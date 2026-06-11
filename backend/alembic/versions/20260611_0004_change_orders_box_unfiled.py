"""Add Box unfiled flag to change orders.

Revision ID: 20260611_0004
Revises: 20260520_0003
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260611_0004"
down_revision: str | None = "20260520_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_orders",
        sa.Column("box_unfiled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_column("change_orders", "box_unfiled", schema="sales")
