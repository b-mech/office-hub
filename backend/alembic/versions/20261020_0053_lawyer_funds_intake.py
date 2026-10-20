"""Lawyer funds intake, review, posting provenance, and closing watch.

Revision ID: 20261020_0053
Revises: 20261019_0052
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261020_0053"
down_revision = "20261019_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funds_notices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="SET NULL")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="SET NULL")),
        sa.Column("email_message_id", sa.Text()), sa.Column("email_from", sa.Text()),
        sa.Column("email_subject", sa.Text()), sa.Column("email_received_at", sa.DateTime(timezone=True)),
        sa.Column("email_body_text", sa.Text()),
        sa.Column("capture_source", sa.Text(), nullable=False, server_default="gmail_extension"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_extraction"),
        sa.Column("funds_type", sa.Text()), sa.Column("law_firm", sa.Text()),
        sa.Column("trust_statement_total", sa.Numeric(15, 2)),
        sa.Column("funds_release_date", sa.Date()),
        sa.Column("classification_reason", sa.Text()),
        sa.Column("review_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending_extraction','pending_review','posted','needs_attention','rejected')", name="ck_funds_notice_status"),
        schema="documents",
    )
    op.create_table(
        "funds_attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("file_key", sa.Text(), nullable=False), sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False, server_default="application/pdf"),
        sa.Column("box_file_id", sa.Text()), sa.Column("box_file_url", sa.Text()),
        sa.Column("box_filing_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("extraction_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("extracted", JSONB()), sa.Column("extraction_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="documents",
    )
    op.create_table(
        "funds_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attachment_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_attachments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="SET NULL")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="SET NULL")),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("core.lender_facilities.id", ondelete="SET NULL")),
        sa.Column("funds_type", sa.Text(), nullable=False), sa.Column("deposit_ordinal", sa.Integer()),
        sa.Column("property_address", sa.Text()), sa.Column("amount", sa.Numeric(15, 2)),
        sa.Column("cheque_number", sa.Text()), sa.Column("txn_date", sa.Date()),
        sa.Column("payee", sa.Text()), sa.Column("memo", sa.Text()),
        sa.Column("closing", JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_review"),
        sa.Column("review_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("matched_statement_id", UUID(as_uuid=True), sa.ForeignKey("documents.lender_statements.id", ondelete="SET NULL")),
        sa.Column("matched_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("documents.facility_statement_snapshots.id", ondelete="SET NULL")),
        sa.Column("posted_transaction_id", UUID(as_uuid=True), sa.ForeignKey("core.facility_transactions.id", ondelete="SET NULL")),
        sa.Column("posting_result", JSONB()),
        sa.Column("confirmed_by", UUID(as_uuid=True), sa.ForeignKey("core.users.id", ondelete="SET NULL")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("funds_type IN ('lot_deposit','pro_draw','client_funded_draw','statement_of_adjustments','other')", name="ck_funds_entry_type"),
        sa.CheckConstraint("status IN ('pending_review','confirmed','posted','needs_attention','rejected')", name="ck_funds_entry_status"),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_funds_entry_amount"),
        schema="documents",
    )
    op.create_index("idx_funds_entries_notice", "funds_entries", ["notice_id", "status"], schema="documents")
    op.create_table(
        "funds_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_key", sa.Text(), nullable=False, unique=True),
        sa.Column("notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="CASCADE")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="CASCADE")),
        sa.Column("task_type", sa.Text(), nullable=False), sa.Column("title", sa.Text(), nullable=False),
        sa.Column("assignee_id", UUID(as_uuid=True), sa.ForeignKey("core.users.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open','completed')", name="ck_funds_task_status"),
        schema="documents",
    )
    op.create_table(
        "funds_box_watches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("folder_id", sa.Text()), sa.Column("possession_date", sa.Date(), nullable=False),
        sa.Column("escalate_after_days", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="watching"),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('watching','completed')", name="ck_funds_watch_status"),
        schema="documents",
    )
    op.create_table(
        "client_funded_draws",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("funds_entry_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_entries.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("funds_notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False), sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("cheque_number", sa.Text()), sa.Column("box_file_url", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False, server_default="client_funded"),
        sa.Column("intake_origin", sa.Text(), nullable=False, server_default="lawyer_notice"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="core",
    )
    op.create_table(
        "lot_closings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("funds_entry_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_entries.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("funds_notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("closing_type", sa.Text(), nullable=False), sa.Column("closing_date", sa.Date(), nullable=False),
        sa.Column("sale_price", sa.Numeric(15, 2)), sa.Column("net_proceeds", sa.Numeric(15, 2)),
        sa.Column("adjustments", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("new_lender", sa.Text()), sa.Column("box_file_url", sa.Text()),
        sa.Column("intake_origin", sa.Text(), nullable=False, server_default="lawyer_notice"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("closing_type IN ('sale','refinance')", name="ck_lot_closing_type"),
        schema="core",
    )
    op.create_table(
        "deposit_payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deposit_schedule_id", UUID(as_uuid=True), sa.ForeignKey("land.deposit_schedule.id", ondelete="SET NULL")),
        sa.Column("funds_entry_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_entries.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("funds_notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deposit_number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False), sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("cheque_number", sa.Text()), sa.Column("box_file_url", sa.Text()),
        sa.Column("variance", sa.Numeric(15, 2)),
        sa.Column("intake_origin", sa.Text(), nullable=False, server_default="lawyer_notice"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="land",
    )
    op.add_column("facility_transactions", sa.Column("funds_entry_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_entries.id", ondelete="SET NULL")), schema="core")
    op.add_column("facility_transactions", sa.Column("funds_notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="SET NULL")), schema="core")
    op.add_column("facility_transactions", sa.Column("intake_origin", sa.Text()), schema="core")
    op.add_column("facility_transactions", sa.Column("box_file_url", sa.Text()), schema="core")
    op.create_index("uq_facility_transaction_funds_entry", "facility_transactions", ["facility_id", "funds_entry_id"], unique=True, schema="core", postgresql_where=sa.text("funds_entry_id IS NOT NULL"))
    op.add_column("lender_facilities", sa.Column("closing_pending_at", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("payout_date", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("payout_amount", sa.Numeric(15, 2)), schema="core")
    op.add_column("lender_facilities", sa.Column("payout_notice_id", UUID(as_uuid=True), sa.ForeignKey("documents.funds_notices.id", ondelete="SET NULL")), schema="core")
    op.add_column("lots", sa.Column("possession_confirmed_date", sa.Date()), schema="core")
    op.add_column("lots", sa.Column("possession_confirmed_at", sa.DateTime(timezone=True)), schema="core")
    op.add_column("lots", sa.Column("closing_date", sa.Date()), schema="core")
    op.add_column("lots", sa.Column("final_sale_price", sa.Numeric(15, 2)), schema="core")
    op.add_column("lots", sa.Column("net_proceeds", sa.Numeric(15, 2)), schema="core")
    op.add_column("construction_stage_sync", sa.Column("possession_date_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema="documents")
    op.add_column("construction_stage_sync", sa.Column("possession_confirmed_date", sa.Date()), schema="documents")


def downgrade() -> None:
    op.drop_column("construction_stage_sync", "possession_confirmed_date", schema="documents")
    op.drop_column("construction_stage_sync", "possession_date_locked", schema="documents")
    for name in ("net_proceeds", "final_sale_price", "closing_date", "possession_confirmed_at", "possession_confirmed_date"):
        op.drop_column("lots", name, schema="core")
    for name in ("payout_notice_id", "payout_amount", "payout_date", "closing_pending_at"):
        op.drop_column("lender_facilities", name, schema="core")
    op.drop_index("uq_facility_transaction_funds_entry", table_name="facility_transactions", schema="core")
    op.drop_column("facility_transactions", "box_file_url", schema="core")
    op.drop_column("facility_transactions", "intake_origin", schema="core")
    op.drop_column("facility_transactions", "funds_notice_id", schema="core")
    op.drop_column("facility_transactions", "funds_entry_id", schema="core")
    op.drop_table("deposit_payments", schema="land")
    op.drop_table("lot_closings", schema="core")
    op.drop_table("client_funded_draws", schema="core")
    op.drop_table("funds_box_watches", schema="documents")
    op.drop_table("funds_tasks", schema="documents")
    op.drop_index("idx_funds_entries_notice", table_name="funds_entries", schema="documents")
    op.drop_table("funds_entries", schema="documents")
    op.drop_table("funds_attachments", schema="documents")
    op.drop_table("funds_notices", schema="documents")
