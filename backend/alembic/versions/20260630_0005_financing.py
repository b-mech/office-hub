"""Add financing dashboard tables.

Revision ID: 20260630_0005
Revises: 20260611_0004
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260630_0005"
down_revision: str | None = "20260611_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("address_normalized", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("address_normalized", name="uq_core_properties_address_normalized"),
        schema="core",
    )

    op.create_table(
        "lender_facilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lender_type", sa.String(length=20), nullable=False),
        sa.Column("lender_name", sa.String(length=100)),
        sa.Column("total_facility", sa.Numeric(12, 2)),
        sa.Column("opening_balance", sa.Numeric(12, 2)),
        sa.Column("rate", sa.Numeric(5, 4)),
        sa.Column("already_drawn", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("last_draw_date", sa.Date()),
        sa.Column("last_draw_amount", sa.Numeric(12, 2)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "lender_type IN ('SCU','PRO','STRIDE','RSU','CLIENT','OTHER')",
            name="ck_lender_facilities_lender_type",
        ),
        schema="core",
    )
    op.create_index("idx_core_lender_facilities_property", "lender_facilities", ["property_id"], schema="core")

    op.create_table(
        "construction_stage_sync",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="SET NULL")),
        sa.Column("address_raw", sa.String(length=255), nullable=False),
        sa.Column("banker_raw", sa.String(length=255)),
        sa.Column("lender_type", sa.String(length=20)),
        sa.Column("sold_or_spec", sa.String(length=10)),
        sa.Column("stage_clean", sa.String(length=50)),
        sa.Column("client_name", sa.String(length=255)),
        sa.Column("build_start", sa.Date()),
        sa.Column("possession_date", sa.Date()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("address_raw", name="uq_documents_construction_stage_sync_address_raw"),
        schema="documents",
    )
    op.create_index("idx_documents_construction_stage_sync_property", "construction_stage_sync", ["property_id"], schema="documents")

    op.create_table(
        "lender_facility_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lender_facilities.id", ondelete="CASCADE")),
        sa.Column("lender_type", sa.String(length=20), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("minio_bucket", sa.String(length=100), nullable=False),
        sa.Column("minio_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("extracted_values", postgresql.JSONB()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("notes", sa.Text()),
        schema="documents",
    )
    op.create_index("idx_documents_lender_facility_documents_facility", "lender_facility_documents", ["facility_id"], schema="documents")


def downgrade() -> None:
    op.drop_index("idx_documents_lender_facility_documents_facility", table_name="lender_facility_documents", schema="documents")
    op.drop_table("lender_facility_documents", schema="documents")
    op.drop_index("idx_documents_construction_stage_sync_property", table_name="construction_stage_sync", schema="documents")
    op.drop_table("construction_stage_sync", schema="documents")
    op.drop_index("idx_core_lender_facilities_property", table_name="lender_facilities", schema="core")
    op.drop_table("lender_facilities", schema="core")
    op.drop_table("properties", schema="core")
