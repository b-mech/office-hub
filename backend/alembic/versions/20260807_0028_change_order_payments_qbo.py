"""Add Plooto and QuickBooks tracking to change orders.

Revision ID: 20260807_0028
Revises: 20260805_0027
"""
from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260807_0028"
down_revision: str | None = "20260805_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column("plooto_payment_link", sa.Text(), nullable=True),
        sa.Column("plooto_status", sa.Text(), nullable=False, server_default=sa.text("'not_started'")),
        sa.Column("qb_invoice_id", sa.Text(), nullable=True),
        sa.Column("qb_invoice_status", sa.Text(), nullable=False, server_default=sa.text("'not_created'")),
        sa.Column("qb_customer_id", sa.Text(), nullable=True),
        sa.Column("qb_project_id", sa.Text(), nullable=True),
        sa.Column("qb_sync_error", sa.Text(), nullable=True),
        sa.Column("payment_email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        op.add_column("change_orders", column, schema="sales")
    op.create_check_constraint("ck_change_orders_plooto_status", "change_orders", "plooto_status IN ('not_started','awaiting_link','link_received')", schema="sales")
    op.create_check_constraint("ck_change_orders_qb_invoice_status", "change_orders", "qb_invoice_status IN ('not_created','created','synced_error','paid')", schema="sales")


def downgrade() -> None:
    op.drop_constraint("ck_change_orders_qb_invoice_status", "change_orders", schema="sales", type_="check")
    op.drop_constraint("ck_change_orders_plooto_status", "change_orders", schema="sales", type_="check")
    for name in ("payment_email_sent_at", "qb_sync_error", "qb_project_id", "qb_customer_id", "qb_invoice_status", "qb_invoice_id", "plooto_status", "plooto_payment_link"):
        op.drop_column("change_orders", name, schema="sales")
