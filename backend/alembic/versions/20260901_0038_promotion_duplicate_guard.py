"""Prevent duplicate agreement promotion by source document.

Revision ID: 20260901_0038
Revises: 20260824_0037
"""
from collections.abc import Sequence

from alembic import op


revision: str = "20260901_0038"
down_revision: str | None = "20260824_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_land_agreements_document_id",
        "agreements",
        ["document_id"],
        schema="land",
    )
    op.create_unique_constraint(
        "uq_sales_agreements_document_id",
        "agreements",
        ["document_id"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_sales_agreements_document_id",
        "agreements",
        schema="sales",
        type_="unique",
    )
    op.drop_constraint(
        "uq_land_agreements_document_id",
        "agreements",
        schema="land",
        type_="unique",
    )
