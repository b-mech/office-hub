"""Add maintenance intake and inbound-MMS support.

Revision ID: 20261001_0047
Revises: 20261001_0046
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261001_0047"
down_revision: str | None = "20261001_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rental_units",
        sa.Column("maintenance_qr_rotation_recommended_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "maint_intake_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("rental_units.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Twilio media must be accepted before an unmatched number can be linked to
    # a ticket. The attachment is associated as soon as routing succeeds.
    op.alter_column("maint_attachments", "ticket_id", existing_type=postgresql.UUID(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM maint_attachments WHERE ticket_id IS NULL")
    op.alter_column("maint_attachments", "ticket_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_table("maint_intake_tokens")
    op.drop_column("rental_units", "maintenance_qr_rotation_recommended_at")
