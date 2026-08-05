"""Link core lots to financing properties.

Revision ID: 20260805_0023
Revises: 20260804_0022
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260805_0023"
down_revision: str | None = "20260804_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lots",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="core",
    )
    op.create_foreign_key(
        "fk_core_lots_property_id",
        "lots",
        "properties",
        ["property_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_core_lots_property_id", "lots", schema="core", type_="foreignkey")
    op.drop_column("lots", "property_id", schema="core")
