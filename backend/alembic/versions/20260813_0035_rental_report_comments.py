"""Add append-only rental report discussions.

Revision ID: 20260813_0035
Revises: 20260811_0034
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260813_0035"
down_revision: str | None = "20260811_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rental_inspection_report_comments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "report_item_id",
            sa.Uuid(),
            sa.ForeignKey("rental_inspection_report_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_rental_report_comments_item_created",
        "rental_inspection_report_comments",
        ["report_item_id", "created_at"],
    )
    op.execute(
        """
        INSERT INTO rental_inspection_report_comments (report_item_id, author_name, body, created_at)
        SELECT id, 'Report reviewer', notes, COALESCE(notes_submitted_at, now())
        FROM rental_inspection_report_items
        WHERE notes IS NOT NULL AND btrim(notes) <> ''
        """
    )


def downgrade() -> None:
    op.drop_table("rental_inspection_report_comments")
