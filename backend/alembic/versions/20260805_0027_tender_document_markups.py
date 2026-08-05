"""Add versioned tender document markup layers.

Revision ID: 20260805_0027
Revises: 20260805_0026
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260805_0027"
down_revision: str | None = "20260805_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tender_document_markups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tender_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.tender_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("annotation_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calibration", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("flattened_pdf_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tender_document_id", "version_number", name="uq_tender_document_markups_version"),
        schema="documents",
    )
    op.create_index(
        "ix_documents_tender_document_markups_document_id",
        "tender_document_markups",
        ["tender_document_id"],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_documents_tender_document_markups_document_id",
        table_name="tender_document_markups",
        schema="documents",
    )
    op.drop_table("tender_document_markups", schema="documents")
