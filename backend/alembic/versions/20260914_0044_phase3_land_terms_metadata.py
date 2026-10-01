"""Preserve Phase 3 source terms and unallocated agreement prices.

Revision ID: 20260914_0044
Revises: 20260909_0043
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260914_0044"
down_revision: str | None = "20260909_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "lot_terms",
        "purchase_price",
        existing_type=sa.Numeric(15, 2),
        nullable=True,
        schema="land",
    )
    op.add_column(
        "lot_terms",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="land",
    )


def downgrade() -> None:
    op.drop_column("lot_terms", "metadata", schema="land")
    op.alter_column(
        "lot_terms",
        "purchase_price",
        existing_type=sa.Numeric(15, 2),
        nullable=False,
        schema="land",
    )
