"""Add PRO lender financing tables.

Revision ID: 20260702_0007
Revises: 20260702_0006
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260702_0007"
down_revision: str | None = "20260702_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "lender_facilities",
        "property_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        nullable=True,
        schema="core",
    )
    op.add_column("lender_facilities", sa.Column("lender", sa.String(length=20)), schema="core")
    op.add_column("lender_facilities", sa.Column("facility_key", sa.String(length=100)), schema="core")
    op.add_column("lender_facilities", sa.Column("property_name", sa.String(length=255)), schema="core")
    op.add_column("lender_facilities", sa.Column("lot_id", postgresql.UUID(as_uuid=True)), schema="core")
    op.add_column(
        "lender_facilities",
        sa.Column("facility_scope", sa.String(length=20), nullable=False, server_default="lot"),
        schema="core",
    )
    op.add_column("lender_facilities", sa.Column("instrument", sa.String(length=100)), schema="core")
    op.add_column("lender_facilities", sa.Column("borrower", sa.String(length=255)), schema="core")
    op.add_column("lender_facilities", sa.Column("annual_rate", sa.Numeric(6, 5)), schema="core")
    op.add_column("lender_facilities", sa.Column("original_advance_date", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("original_advance_amount", sa.Numeric(14, 2)), schema="core")
    op.add_column(
        "lender_facilities",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        schema="core",
    )
    op.create_unique_constraint("uq_core_lender_facilities_facility_key", "lender_facilities", ["facility_key"], schema="core")
    op.create_foreign_key(
        "fk_core_lender_facilities_lot_id",
        "lender_facilities",
        "lots",
        ["lot_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="SET NULL",
    )

    op.create_table(
        "lender_statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lender", sa.String(length=20), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("minio_object_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(length=255)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("parsed_at", sa.DateTime(timezone=True)),
        sa.Column("parse_payload", postgresql.JSONB()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="uploaded"),
        sa.UniqueConstraint("lender", "period", "minio_object_key", name="uq_lender_statements_object"),
        schema="documents",
    )

    op.create_table(
        "facility_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.lender_facilities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("txn_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference", sa.Text()),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.lender_statements.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("facility_id", "txn_date", "amount", "reference", name="uq_facility_transactions_identity"),
        schema="core",
    )
    op.create_index("idx_core_facility_transactions_facility_date", "facility_transactions", ["facility_id", "txn_date"], schema="core")

    op.create_table(
        "facility_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.lender_facilities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("alias", name="uq_core_facility_aliases_alias"),
        schema="core",
    )

    op.create_table(
        "facility_statement_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "statement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.lender_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lender_facilities.id", ondelete="SET NULL")),
        sa.Column("matched_property_name", sa.Text(), nullable=False),
        sa.Column("reported_period_end_date", sa.Date(), nullable=False),
        sa.Column("reported_period_end_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("computed_balance", sa.Numeric(14, 2)),
        sa.Column("delta", sa.Numeric(14, 2)),
        sa.Column("reconciliation_status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("statement_id", "matched_property_name", name="uq_statement_snapshot_property"),
        schema="documents",
    )
    op.create_index("idx_documents_facility_statement_snapshots_statement", "facility_statement_snapshots", ["statement_id"], schema="documents")


def downgrade() -> None:
    op.drop_index("idx_documents_facility_statement_snapshots_statement", table_name="facility_statement_snapshots", schema="documents")
    op.drop_table("facility_statement_snapshots", schema="documents")
    op.drop_table("facility_aliases", schema="core")
    op.drop_index("idx_core_facility_transactions_facility_date", table_name="facility_transactions", schema="core")
    op.drop_table("facility_transactions", schema="core")
    op.drop_table("lender_statements", schema="documents")

    op.drop_constraint("fk_core_lender_facilities_lot_id", "lender_facilities", schema="core", type_="foreignkey")
    op.drop_constraint("uq_core_lender_facilities_facility_key", "lender_facilities", schema="core", type_="unique")
    op.drop_column("lender_facilities", "status", schema="core")
    op.drop_column("lender_facilities", "original_advance_amount", schema="core")
    op.drop_column("lender_facilities", "original_advance_date", schema="core")
    op.drop_column("lender_facilities", "annual_rate", schema="core")
    op.drop_column("lender_facilities", "borrower", schema="core")
    op.drop_column("lender_facilities", "instrument", schema="core")
    op.drop_column("lender_facilities", "facility_scope", schema="core")
    op.drop_column("lender_facilities", "lot_id", schema="core")
    op.drop_column("lender_facilities", "property_name", schema="core")
    op.drop_column("lender_facilities", "facility_key", schema="core")
    op.drop_column("lender_facilities", "lender", schema="core")
    op.alter_column(
        "lender_facilities",
        "property_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=True,
        nullable=False,
        schema="core",
    )
