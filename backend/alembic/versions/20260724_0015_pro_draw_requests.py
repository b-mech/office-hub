"""Add PRO draw request and email tracking records.

Revision ID: 20260724_0015
Revises: 20260724_0014
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260724_0015"
down_revision: str | None = "20260724_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pro_draw_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.lender_facilities.id", ondelete="SET NULL"),
        ),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("stage", sa.String(length=50)),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="prepared"),
        sa.Column("initial_recipient", sa.Text(), nullable=False),
        sa.Column("intermediary_email", sa.Text(), nullable=False),
        sa.Column("email_subject", sa.Text(), nullable=False),
        sa.Column("email_body", sa.Text(), nullable=False),
        sa.Column("gmail_thread_id", sa.Text()),
        sa.Column("gmail_message_id", sa.Text()),
        sa.Column("last_email_at", sa.DateTime(timezone=True)),
        sa.Column("last_email_from", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("lawyer_processing_at", sa.DateTime(timezone=True)),
        sa.Column("funded_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('prepared','sent','acknowledged','lawyer_processing','funded','closed','cancelled')",
            name="ck_pro_draw_requests_status",
        ),
        schema="documents",
    )
    op.create_index(
        "idx_pro_draw_requests_property",
        "pro_draw_requests",
        ["property_id", "created_at"],
        schema="documents",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pro_draw_requests_property",
        table_name="pro_draw_requests",
        schema="documents",
    )
    op.drop_table("pro_draw_requests", schema="documents")
