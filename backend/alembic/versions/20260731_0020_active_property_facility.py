"""Allow only one active lender facility per property.

Revision ID: 20260731_0020
Revises: 20260731_0019
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260731_0020"
down_revision: str | None = "20260731_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_core_lender_facilities_active_property",
        "lender_facilities",
        ["property_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("status = 'active' AND property_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_core_lender_facilities_active_property",
        table_name="lender_facilities",
        schema="core",
    )
