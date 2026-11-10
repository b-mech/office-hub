"""Remove inbound Slack relay persistence.

Revision ID: 20261005_0050
Revises: 20261002_0049
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261005_0050"
down_revision: str | None = "20261002_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("maint_slack_cards")
    op.drop_index("uq_maint_sms_messages_slack_message", table_name="maint_sms_messages")
    op.drop_column("maint_sms_messages", "slack_ts")
    op.drop_column("maint_sms_messages", "slack_channel_id")
    op.drop_column("maint_events", "slack_ts")


def downgrade() -> None:
    party = postgresql.ENUM(name="maint_party", create_type=False)
    op.add_column("maint_events", sa.Column("slack_ts", sa.Text()))
    op.add_column("maint_sms_messages", sa.Column("slack_channel_id", sa.Text()))
    op.add_column("maint_sms_messages", sa.Column("slack_ts", sa.Text()))
    op.create_index(
        "uq_maint_sms_messages_slack_message",
        "maint_sms_messages",
        ["slack_channel_id", "slack_ts"],
        unique=True,
        postgresql_where=sa.text("slack_channel_id IS NOT NULL AND slack_ts IS NOT NULL"),
    )
    op.create_table(
        "maint_slack_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("maint_tickets.id"),
            nullable=False,
        ),
        sa.Column(
            "work_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("maint_work_orders.id"),
        ),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("message_ts", sa.Text(), nullable=False),
        sa.Column("thread_party", party, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("channel_id", "message_ts", name="uq_maint_slack_cards_message"),
    )
    op.create_index(
        "uq_maint_slack_cards_ticket",
        "maint_slack_cards",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("work_order_id IS NULL"),
    )
    op.create_index(
        "uq_maint_slack_cards_work_order",
        "maint_slack_cards",
        ["work_order_id"],
        unique=True,
        postgresql_where=sa.text("work_order_id IS NOT NULL"),
    )
