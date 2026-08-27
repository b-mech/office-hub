"""Add Google login identity fields to core users.

Revision ID: 20260824_0037
Revises: 20260819_0036
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0037"
down_revision: str | None = "20260819_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_subject", sa.Text(), nullable=True), schema="core")
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.create_unique_constraint(
        "uq_core_users_google_subject",
        "users",
        ["google_subject"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint("uq_core_users_google_subject", "users", schema="core", type_="unique")
    op.drop_column("users", "last_login_at", schema="core")
    op.drop_column("users", "google_subject", schema="core")
