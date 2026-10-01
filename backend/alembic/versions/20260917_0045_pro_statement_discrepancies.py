"""Add reviewable PRO statement discrepancies.

Revision ID: 20260917_0045
Revises: 20260914_0044
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260917_0045"
down_revision: str | None = "20260914_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lender_statement_discrepancies",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "statement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.lender_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.lender_facilities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("issue_type", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("canonical_address_key", sa.String(length=255), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("issue_type IN ('internal_missing_from_report')", name="ck_statement_discrepancy_issue_type"),
        sa.CheckConstraint("status IN ('open', 'acknowledged')", name="ck_statement_discrepancy_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("statement_id", "entity_key", name="uq_statement_discrepancy_entity"),
        schema="documents",
    )
    op.create_index(
        "idx_statement_discrepancies_statement_status",
        "lender_statement_discrepancies",
        ["statement_id", "status"],
        schema="documents",
    )
    op.create_index(
        "idx_statement_discrepancies_facility",
        "lender_statement_discrepancies",
        ["facility_id"],
        schema="documents",
    )
    op.create_index(
        "idx_statement_discrepancies_property",
        "lender_statement_discrepancies",
        ["property_id"],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index("idx_statement_discrepancies_property", table_name="lender_statement_discrepancies", schema="documents")
    op.drop_index("idx_statement_discrepancies_facility", table_name="lender_statement_discrepancies", schema="documents")
    op.drop_index("idx_statement_discrepancies_statement_status", table_name="lender_statement_discrepancies", schema="documents")
    op.drop_table("lender_statement_discrepancies", schema="documents")
