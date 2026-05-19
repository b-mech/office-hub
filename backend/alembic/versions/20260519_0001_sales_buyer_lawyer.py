"""Add buyer lawyer to sales agreements.

Revision ID: 20260519_0001
Revises: 20260511_0001
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260519_0001"
down_revision: str | None = "20260511_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agreements",
        sa.Column("buyer_lawyer_name", sa.Text(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_column("agreements", "buyer_lawyer_name", schema="sales")
