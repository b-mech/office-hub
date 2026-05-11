"""Add sales change order tables.

Revision ID: 20260511_0001
Revises:
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260511_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "change_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "lot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("land.agreements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("co_number", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("payment_method", sa.Text(), nullable=False, server_default=sa.text("'due_upon_receipt'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("gst", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("docusign_envelope_id", sa.Text(), nullable=True),
        sa.Column("box_file_id", sa.Text(), nullable=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.orgs.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="sales",
    )
    op.execute(
        "CREATE INDEX idx_sales_change_orders_org_status_created "
        "ON sales.change_orders (org_id, status, created_at DESC)"
    )

    op.create_table(
        "change_order_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "change_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sales.change_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("is_credit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="sales",
    )
    op.create_index(
        "idx_sales_change_order_line_items_change_order",
        "change_order_line_items",
        ["change_order_id"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_sales_change_order_line_items_change_order",
        table_name="change_order_line_items",
        schema="sales",
    )
    op.drop_table("change_order_line_items", schema="sales")
    op.drop_index(
        "idx_sales_change_orders_org_status_created",
        table_name="change_orders",
        schema="sales",
    )
    op.drop_table("change_orders", schema="sales")
