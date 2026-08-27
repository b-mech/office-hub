"""Persist user invite state and permissions.

Revision ID: 20260819_0036
Revises: 20260813_0035
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260819_0036"
down_revision: str | None = "20260813_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="core",
    )
    op.add_column("users", sa.Column("invited_at", sa.DateTime(timezone=True)), schema="core")
    op.add_column("users", sa.Column("invite_sent_at", sa.DateTime(timezone=True)), schema="core")


def downgrade() -> None:
    op.drop_column("users", "invite_sent_at", schema="core")
    op.drop_column("users", "invited_at", schema="core")
    op.drop_column("users", "permissions", schema="core")
