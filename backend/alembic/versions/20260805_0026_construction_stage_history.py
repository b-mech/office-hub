"""Add immutable construction stage transition history.

Revision ID: 20260805_0026
Revises: 20260805_0025
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260805_0026"
down_revision: str | None = "20260805_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "construction_stage_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("previous_stage", sa.Text(), nullable=True),
        sa.Column("new_stage", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="documents",
    )
    op.create_index(
        "idx_documents_construction_stage_history_property_changed",
        "construction_stage_history",
        ["property_id", "changed_at"],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_documents_construction_stage_history_property_changed",
        table_name="construction_stage_history",
        schema="documents",
    )
    op.drop_table("construction_stage_history", schema="documents")
