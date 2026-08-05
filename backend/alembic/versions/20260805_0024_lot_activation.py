"""Add lot activation trigger and manual flags.

Revision ID: 20260805_0024
Revises: 20260805_0023
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260805_0024"
down_revision: str | None = "20260805_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lots", sa.Column("trigger_type", sa.String(length=20), nullable=True), schema="core")
    op.add_column(
        "lots",
        sa.Column("on_hold", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="core",
    )
    op.add_column(
        "lots",
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="core",
    )
    op.create_check_constraint(
        "ck_core_lots_trigger_type",
        "lots",
        "trigger_type IN ('otp', 'spec', 'showhome')",
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint("ck_core_lots_trigger_type", "lots", schema="core", type_="check")
    op.drop_column("lots", "cancelled", schema="core")
    op.drop_column("lots", "on_hold", schema="core")
    op.drop_column("lots", "trigger_type", schema="core")
