"""Add interactive rental inspection reports.

Revision ID: 20260810_0032
Revises: 20260810_0031
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260810_0032"
down_revision: str | None = "20260810_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rental_inspection_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("recipient_email", sa.String(255)),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft', 'sent')", name="chk_rental_inspection_report_status"),
    )
    op.create_table(
        "rental_inspection_report_items",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("rental_inspection_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inspection_id", sa.Integer(), sa.ForeignKey("rental_inspections.id"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("notes_submitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("report_id", "inspection_id", name="uq_rental_report_inspection"),
    )
    op.create_index("idx_rental_report_items_report", "rental_inspection_report_items", ["report_id"])


def downgrade() -> None:
    op.drop_table("rental_inspection_report_items")
    op.drop_table("rental_inspection_reports")
