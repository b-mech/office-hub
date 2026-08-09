"""Add reviewed rental lease imports.

Revision ID: 20260809_0030
Revises: 20260809_0029
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260809_0030"
down_revision: str | None = "20260809_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rental_lease_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_pending", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("status IN ('processing', 'needs_review', 'closed')", name="chk_rental_lease_import_batch_status"),
    )
    op.create_table(
        "rental_lease_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("rental_lease_import_batches.id"), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        sa.Column("parsed_data", postgresql.JSONB()),
        sa.Column("confidence", postgresql.JSONB()),
        sa.Column("match_type", sa.String(20)),
        sa.Column("matched_unit_id", sa.Integer(), sa.ForeignKey("rental_units.id")),
        sa.Column("suggested_action", sa.String(20)),
        sa.Column("existing_lease_id", sa.Integer(), sa.ForeignKey("rental_leases.id")),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="needs_review"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("committed_lease_id", sa.Integer(), sa.ForeignKey("rental_leases.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("batch_id", "source_row_number", name="uq_rental_lease_import_batch_row"),
        sa.CheckConstraint("match_type IS NULL OR match_type IN ('existing_unit', 'new_unit', 'unresolved')", name="chk_rental_lease_import_match_type"),
        sa.CheckConstraint("suggested_action IS NULL OR suggested_action IN ('create_lease', 'renew_lease', 'update_lease', 'skip')", name="chk_rental_lease_import_action"),
        sa.CheckConstraint("review_status IN ('needs_review', 'edited', 'approved', 'rejected')", name="chk_rental_lease_import_review_status"),
    )
    op.create_index("idx_lease_import_rows_batch", "rental_lease_import_rows", ["batch_id"])
    op.create_index("idx_lease_import_rows_status", "rental_lease_import_rows", ["review_status"])


def downgrade() -> None:
    op.drop_table("rental_lease_import_rows")
    op.drop_table("rental_lease_import_batches")
