"""Add client OTP draw schedules and requests.

Revision ID: 20260715_0010
Revises: 20260707_0009
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260715_0010"
down_revision: str | None = "20260707_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_draw_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("minio_object_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(length=255)),
        sa.Column("purchase_price", sa.Numeric(14, 2)),
        sa.Column("client_name", sa.Text()),
        sa.Column("otp_date", sa.Date()),
        sa.Column("schedule", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("deposits", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extraction_confidence", sa.String(length=20), nullable=False, server_default="needs_review"),
        sa.Column("extraction_status", sa.String(length=30), nullable=False, server_default="uploaded"),
        sa.Column("extraction_notes", sa.Text()),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="documents",
    )
    op.create_index("idx_client_draw_schedules_property", "client_draw_schedules", ["property_id"], schema="documents")
    op.create_index(
        "idx_client_draw_schedules_active",
        "client_draw_schedules",
        ["property_id"],
        schema="documents",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "client_draw_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.client_draw_schedules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("draw_items", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("stage_at_prep", sa.Text()),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("prepared_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="prepared"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="documents",
    )
    op.create_index("idx_client_draw_requests_property", "client_draw_requests", ["property_id"], schema="documents")
    op.create_index("idx_client_draw_requests_schedule", "client_draw_requests", ["schedule_id"], schema="documents")

    op.create_table(
        "stage_label_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("label_raw", sa.Text(), nullable=False),
        sa.Column("label_normalized", sa.Text(), nullable=False),
        sa.Column("stage_key", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("label_normalized", name="uq_stage_label_aliases_label_normalized"),
        schema="documents",
    )
    op.bulk_insert(
        sa.table(
            "stage_label_aliases",
            sa.column("label_raw", sa.Text),
            sa.column("label_normalized", sa.Text),
            sa.column("stage_key", sa.String),
            schema="documents",
        ),
        [
            {"label_raw": "foundation", "label_normalized": "FOUNDATION", "stage_key": "FOUNDATION"},
            {"label_raw": "footings", "label_normalized": "FOOTINGS", "stage_key": "FOUNDATION"},
            {"label_raw": "basement", "label_normalized": "BASEMENT", "stage_key": "FOUNDATION"},
            {"label_raw": "framing", "label_normalized": "FRAMING", "stage_key": "LOCKUP"},
            {"label_raw": "roof", "label_normalized": "ROOF", "stage_key": "LOCKUP"},
            {"label_raw": "lockup", "label_normalized": "LOCKUP", "stage_key": "LOCKUP"},
            {"label_raw": "drywall", "label_normalized": "DRYWALL", "stage_key": "DRYWALL"},
            {"label_raw": "paint", "label_normalized": "PAINT", "stage_key": "CABINETRY"},
            {"label_raw": "cabinetry", "label_normalized": "CABINETRY", "stage_key": "CABINETRY"},
            {"label_raw": "possession", "label_normalized": "POSSESSION", "stage_key": "COMPLETED"},
            {"label_raw": "completion", "label_normalized": "COMPLETION", "stage_key": "COMPLETED"},
            {"label_raw": "closing", "label_normalized": "CLOSING", "stage_key": "COMPLETED"},
        ],
    )


def downgrade() -> None:
    op.drop_table("stage_label_aliases", schema="documents")
    op.drop_index("idx_client_draw_requests_schedule", table_name="client_draw_requests", schema="documents")
    op.drop_index("idx_client_draw_requests_property", table_name="client_draw_requests", schema="documents")
    op.drop_table("client_draw_requests", schema="documents")
    op.drop_index("idx_client_draw_schedules_active", table_name="client_draw_schedules", schema="documents")
    op.drop_index("idx_client_draw_schedules_property", table_name="client_draw_schedules", schema="documents")
    op.drop_table("client_draw_schedules", schema="documents")
