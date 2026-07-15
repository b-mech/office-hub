"""Add canonical financing address keys.

Revision ID: 20260703_0008
Revises: 20260702_0007
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260703_0008"
down_revision: str | None = "20260702_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("canonical_address_key", sa.String(length=255)), schema="core")
    op.add_column("properties", sa.Column("property_type", sa.String(length=30), nullable=False, server_default="lot"), schema="core")
    op.create_index("idx_core_properties_canonical_address_key", "properties", ["canonical_address_key"], schema="core")

    op.add_column("lender_facilities", sa.Column("canonical_address_key", sa.String(length=255)), schema="core")
    op.create_index("idx_core_lender_facilities_canonical_address_key", "lender_facilities", ["canonical_address_key"], schema="core")

    op.add_column("facility_statement_snapshots", sa.Column("canonical_address_key", sa.String(length=255)), schema="documents")
    op.add_column("facility_statement_snapshots", sa.Column("parse_payload", postgresql.JSONB()), schema="documents")
    op.add_column("facility_statement_snapshots", sa.Column("new_draws_detected", postgresql.JSONB()), schema="documents")


def downgrade() -> None:
    op.drop_column("facility_statement_snapshots", "new_draws_detected", schema="documents")
    op.drop_column("facility_statement_snapshots", "parse_payload", schema="documents")
    op.drop_column("facility_statement_snapshots", "canonical_address_key", schema="documents")
    op.drop_index("idx_core_lender_facilities_canonical_address_key", table_name="lender_facilities", schema="core")
    op.drop_column("lender_facilities", "canonical_address_key", schema="core")
    op.drop_index("idx_core_properties_canonical_address_key", table_name="properties", schema="core")
    op.drop_column("properties", "property_type", schema="core")
    op.drop_column("properties", "canonical_address_key", schema="core")
