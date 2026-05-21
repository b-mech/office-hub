"""Add customer email to change orders.

Revision ID: 20260520_0003
Revises: 20260519_0002
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260520_0003"
down_revision: str | None = "20260519_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_orders",
        sa.Column("customer_email", sa.Text(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_column("change_orders", "customer_email", schema="sales")
