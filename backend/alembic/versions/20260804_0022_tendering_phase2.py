"""Add tender bids and awards.

Revision ID: 20260804_0022
Revises: 20260804_0021
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0022"
down_revision: str | None = "20260804_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table("tender_bids",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.tender_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contractor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.contractors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="invited"),
        sa.Column("quote_amount", sa.Numeric(15,2)), sa.Column("extracted_amount", sa.Numeric(15,2)),
        sa.Column("extracted_line_items", postgresql.JSONB()), sa.Column("excluded_scope_notes", sa.Text()), sa.Column("reviewer_notes", sa.Text()),
        sa.Column("invited_at", sa.DateTime(timezone=True)), sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('invited','received','reviewed','cancelled')", name="ck_tender_bids_status"),
        sa.UniqueConstraint("tender_package_id", "contractor_id", name="uq_tender_bids_package_contractor"), schema="core")
    op.create_index("ix_core_tender_bids_package_id", "tender_bids", ["tender_package_id"], schema="core")
    op.create_table("tender_bid_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_bid_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.tender_bids.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False), sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema="documents")
    op.create_index("ix_documents_tender_bid_documents_bid_id", "tender_bid_documents", ["tender_bid_id"], schema="documents")
    op.create_table("tender_awards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tender_package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.tender_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("winning_bid_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.tender_bids.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("costbook.purchase_orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("award_instructions", sa.Text(), nullable=False), sa.Column("project_start_date", sa.Date(), nullable=False),
        sa.Column("contractor_start_date", sa.Date(), nullable=False), sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tender_package_id", name="uq_tender_awards_package"), schema="core")

def downgrade() -> None:
    op.drop_table("tender_awards", schema="core")
    op.drop_table("tender_bid_documents", schema="documents")
    op.drop_table("tender_bids", schema="core")
