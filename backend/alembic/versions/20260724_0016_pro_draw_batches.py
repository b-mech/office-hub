"""Group consolidated PRO draw request items.

Revision ID: 20260724_0016
Revises: 20260724_0015
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260724_0016"
down_revision: str | None = "20260724_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pro_draw_requests",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True)),
        schema="documents",
    )
    op.execute("UPDATE documents.pro_draw_requests SET batch_id = id WHERE batch_id IS NULL")
    op.alter_column(
        "pro_draw_requests",
        "batch_id",
        nullable=False,
        schema="documents",
    )
    op.create_index(
        "idx_pro_draw_requests_batch",
        "pro_draw_requests",
        ["batch_id"],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pro_draw_requests_batch",
        table_name="pro_draw_requests",
        schema="documents",
    )
    op.drop_column("pro_draw_requests", "batch_id", schema="documents")
