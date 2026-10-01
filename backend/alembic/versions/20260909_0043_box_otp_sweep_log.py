"""Add durable Box OTP sweep outcome logging.

Revision ID: 20260909_0043
Revises: 20260909_0042
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260909_0043"
down_revision: str | None = "20260909_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "box_sweep_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("box_file_id", sa.Text(), nullable=False),
        sa.Column("box_sha1", sa.Text(), nullable=True),
        sa.Column("box_path", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("classification IN ('land_otp', 'sale_otp', 'supporting', 'other')"),
        sa.CheckConstraint("outcome IN ('ingested', 'skipped', 'failed', 'dry_run')"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )
    op.create_index(
        "idx_documents_box_sweep_events_run_outcome",
        "box_sweep_events",
        ["run_id", "outcome"],
        schema="documents",
    )
    op.create_index(
        "idx_documents_box_sweep_events_file_created",
        "box_sweep_events",
        ["box_file_id", sa.text("created_at DESC")],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_documents_box_sweep_events_file_created",
        table_name="box_sweep_events",
        schema="documents",
    )
    op.drop_index(
        "idx_documents_box_sweep_events_run_outcome",
        table_name="box_sweep_events",
        schema="documents",
    )
    op.drop_table("box_sweep_events", schema="documents")
