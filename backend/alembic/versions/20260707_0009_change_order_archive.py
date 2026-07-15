"""Add change order archive marker.

Revision ID: 20260707_0009
Revises: 20260703_0008
Create Date: 2026-07-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260707_0009"
down_revision: str | None = "20260703_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_orders",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_column("change_orders", "archived_at", schema="sales")
