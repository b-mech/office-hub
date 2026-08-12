"""Add construction milestone date confirmation history.

Revision ID: 20260723_0012
Revises: 20260723_0011
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260723_0012"
down_revision: str | None = "20260723_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "construction_stage_milestones",
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        schema="documents",
    )
    op.add_column(
        "construction_stage_milestones",
        sa.Column("confirmation_note", sa.Text()),
        schema="documents",
    )
    op.create_table(
        "construction_stage_milestone_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "milestone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "documents.construction_stage_milestones.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "previous_achieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="documents",
    )
    op.create_index(
        "idx_documents_milestone_revisions_milestone",
        "construction_stage_milestone_revisions",
        ["milestone_id", "created_at"],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_documents_milestone_revisions_milestone",
        table_name="construction_stage_milestone_revisions",
        schema="documents",
    )
    op.drop_table(
        "construction_stage_milestone_revisions",
        schema="documents",
    )
    op.drop_column(
        "construction_stage_milestones",
        "confirmation_note",
        schema="documents",
    )
    op.drop_column(
        "construction_stage_milestones",
        "confirmed_at",
        schema="documents",
    )
