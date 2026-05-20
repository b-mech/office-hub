"""Add Box URL to change orders.

Revision ID: 20260519_0002
Revises: 20260511_0001
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260519_0002"
down_revision: str | None = "20260511_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_orders",
        sa.Column("box_file_url", sa.Text(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_column("change_orders", "box_file_url", schema="sales")
