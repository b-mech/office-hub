"""Add durable Slack notification outbox.

Revision ID: 20261002_0049
Revises: 20261002_0048
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261002_0049"
down_revision: str | None = "20261002_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maint_slack_outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id")),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_work_orders.id")),
        sa.Column("sms_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_sms_messages.id")),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("attempts >= 0", name="ck_maint_slack_outbox_attempts"),
    )
    op.create_index(
        "idx_maint_slack_outbox_due",
        "maint_slack_outbox",
        ["available_at", "created_at"],
        postgresql_where=sa.text("delivered_at IS NULL AND failed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_maint_slack_outbox_due", table_name="maint_slack_outbox")
    op.drop_table("maint_slack_outbox")
