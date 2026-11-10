"""Add maintenance domain guards for Slack relay.

Revision ID: 20261002_0048
Revises: 20261001_0047
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261002_0048"
down_revision: str | None = "20261001_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_maint_sms_messages_slack_message",
        "maint_sms_messages",
        ["slack_channel_id", "slack_ts"],
        unique=True,
        postgresql_where=sa.text("slack_channel_id IS NOT NULL AND slack_ts IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_maint_sms_messages_slack_message", table_name="maint_sms_messages")
