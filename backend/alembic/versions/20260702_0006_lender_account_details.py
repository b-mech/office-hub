"""Add lender account detail fields.

Revision ID: 20260702_0006
Revises: 20260630_0005
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260702_0006"
down_revision: str | None = "20260630_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "lender_facilities",
        "rate",
        existing_type=sa.Numeric(5, 4),
        type_=sa.Numeric(7, 4),
        existing_nullable=True,
        schema="core",
    )
    op.add_column("lender_facilities", sa.Column("account_number", sa.String(length=50)), schema="core")
    op.add_column("lender_facilities", sa.Column("account_title", sa.String(length=100)), schema="core")
    op.add_column("lender_facilities", sa.Column("account_type", sa.String(length=50)), schema="core")
    op.add_column("lender_facilities", sa.Column("current_balance", sa.Numeric(12, 2)), schema="core")
    op.add_column("lender_facilities", sa.Column("outstanding_balance", sa.Numeric(12, 2)), schema="core")
    op.add_column("lender_facilities", sa.Column("account_currency", sa.String(length=3)), schema="core")
    op.add_column("lender_facilities", sa.Column("maturity_date", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("member_number", sa.String(length=50)), schema="core")
    op.add_column("lender_facilities", sa.Column("next_interest_payment_date", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("next_payment_date", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("account_nickname", sa.String(length=255)), schema="core")
    op.add_column("lender_facilities", sa.Column("open_date", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("original_loan_amount", sa.Numeric(12, 2)), schema="core")
    op.add_column("lender_facilities", sa.Column("payment_schedule", sa.String(length=50)), schema="core")
    op.add_column("lender_facilities", sa.Column("term_length_days", sa.Integer()), schema="core")


def downgrade() -> None:
    op.drop_column("lender_facilities", "term_length_days", schema="core")
    op.drop_column("lender_facilities", "payment_schedule", schema="core")
    op.drop_column("lender_facilities", "original_loan_amount", schema="core")
    op.drop_column("lender_facilities", "open_date", schema="core")
    op.drop_column("lender_facilities", "account_nickname", schema="core")
    op.drop_column("lender_facilities", "next_payment_date", schema="core")
    op.drop_column("lender_facilities", "next_interest_payment_date", schema="core")
    op.drop_column("lender_facilities", "member_number", schema="core")
    op.drop_column("lender_facilities", "maturity_date", schema="core")
    op.drop_column("lender_facilities", "account_currency", schema="core")
    op.drop_column("lender_facilities", "outstanding_balance", schema="core")
    op.drop_column("lender_facilities", "current_balance", schema="core")
    op.drop_column("lender_facilities", "account_type", schema="core")
    op.drop_column("lender_facilities", "account_title", schema="core")
    op.drop_column("lender_facilities", "account_number", schema="core")
    op.alter_column(
        "lender_facilities",
        "rate",
        existing_type=sa.Numeric(7, 4),
        type_=sa.Numeric(5, 4),
        existing_nullable=True,
        schema="core",
    )
