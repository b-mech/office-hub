"""Add financing construction milestone history.

Revision ID: 20260723_0011
Revises: 20260715_0010
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260723_0011"
down_revision: str | None = "20260715_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "construction_stage_milestones",
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
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column(
            "achieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
            server_default="sheet_sync",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "property_id",
            "stage",
            "achieved_at",
            name="uq_construction_stage_milestones_event",
        ),
        schema="documents",
    )
    op.create_index(
        "idx_documents_construction_stage_milestones_property",
        "construction_stage_milestones",
        ["property_id", "achieved_at"],
        schema="documents",
    )

    # Establish a baseline for existing properties. The first known date is the
    # last sheet observation; earlier milestone dates were not retained.
    op.execute(
        """
        INSERT INTO documents.construction_stage_milestones (
            property_id, stage, achieved_at, source
        )
        SELECT property_id, stage_clean, last_synced_at, 'migration_baseline'
        FROM documents.construction_stage_sync
        WHERE property_id IS NOT NULL
          AND stage_clean IS NOT NULL
          AND stage_clean NOT IN ('', 'NA', 'SYNC_CONFLICT')
        """
    )


def downgrade() -> None:
    op.drop_index(
        "idx_documents_construction_stage_milestones_property",
        table_name="construction_stage_milestones",
        schema="documents",
    )
    op.drop_table("construction_stage_milestones", schema="documents")
