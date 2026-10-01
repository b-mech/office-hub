"""Add presale approval letter intake and partner readiness.

Revision ID: 20260908_0041
Revises: 20260903_0040, 20260810_0032, 20260727_0018
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260908_0041"
down_revision: tuple[str, str, str] = (
    "20260903_0040",
    "20260810_0032",
    "20260727_0018",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents.documents DROP CONSTRAINT IF EXISTS doc_type")
    op.alter_column("documents", "doc_type", type_=sa.String(length=30), schema="documents")
    op.create_check_constraint(
        "doc_type",
        "documents",
        "doc_type IN ('land_otp','sale_otp','appraisal','stamped_plans','invoice','legal','other')",
        schema="documents",
    )
    op.create_table(
        "presale_approval_letters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text(), nullable=False, server_default="requested"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("requested_from", sa.Text()),
        sa.Column("file_key", sa.Text()),
        sa.Column("file_sha256", sa.Text()),
        sa.Column("original_filename", sa.Text()),
        sa.Column("email_message_id", sa.Text()),
        sa.Column("email_from", sa.Text()),
        sa.Column("email_subject", sa.Text()),
        sa.Column("email_received_at", sa.DateTime(timezone=True)),
        sa.Column("email_body_text", sa.Text()),
        sa.Column("extracted", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("extraction_confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("low_confidence_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("needs_manual_entry", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("quality_score", sa.Integer()),
        sa.Column("lender_contacted_at", sa.DateTime(timezone=True)),
        sa.Column("lender_contact_notes", sa.Text()),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('requested','pending_extraction','pending_review','approved','rejected','superseded')",
            name="ck_presale_approval_letter_status",
        ),
        sa.CheckConstraint("quality_score IS NULL OR quality_score BETWEEN 1 AND 10", name="ck_presale_quality_score"),
        schema="core",
    )
    op.create_index("idx_presale_approval_letters_lot_status", "presale_approval_letters", ["lot_id", "status"], schema="core")
    op.create_index("idx_presale_approval_letters_review", "presale_approval_letters", ["status", "created_at"], schema="core")
    op.execute("CREATE UNIQUE INDEX uq_presale_letter_lot_sha ON core.presale_approval_letters(lot_id, file_sha256) WHERE lot_id IS NOT NULL AND file_sha256 IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_presale_letter_unmatched_sha ON core.presale_approval_letters(file_sha256) WHERE lot_id IS NULL AND file_sha256 IS NOT NULL")

    op.create_table(
        "funding_partner_rules",
        sa.Column("partner_code", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("required_docs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("required_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("disqualifying_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("min_quality_score", sa.Integer()),
        sa.Column("formula", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("max_advance_rule", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("package_recipient", sa.Text()),
        sa.Column("package_docs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority >= 0", name="ck_funding_partner_priority"),
        sa.CheckConstraint("min_quality_score IS NULL OR min_quality_score BETWEEN 1 AND 10", name="ck_funding_partner_min_quality"),
        schema="core",
    )

    op.create_table(
        "presale_package_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("ordered_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.documents.id", ondelete="SET NULL")),
        sa.Column("file_key", sa.Text()),
        sa.Column("original_filename", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("item_type IN ('appraisal','stamped_plans','otp_land','otp_sale','prelim_budget')", name="ck_presale_package_item_type"),
        sa.UniqueConstraint("lot_id", "item_type", name="uq_presale_package_item_lot_type"),
        schema="core",
    )

    op.create_table(
        "presale_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="CASCADE")),
        sa.Column("approval_letter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.presale_approval_letters.id", ondelete="CASCADE")),
        sa.Column("task_key", sa.Text(), nullable=False, unique=True),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('open','completed','cancelled')", name="ck_presale_task_status"),
        schema="core",
    )
    op.create_index("idx_presale_tasks_queue", "presale_tasks", ["status", "created_at"], schema="core")
    op.create_index("idx_presale_tasks_lot", "presale_tasks", ["lot_id", "status"], schema="core")

    op.create_table(
        "presale_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="CASCADE")),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="core",
    )
    op.create_index("idx_presale_notifications_unread", "presale_notifications", ["recipient_id", "read_at", "created_at"], schema="core")

    op.add_column("lots", sa.Column("sale_type", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("building_type", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("realtor_name", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("realtor_email", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("realtor_brokerage", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("active_approval_letter_id", postgresql.UUID(as_uuid=True)), schema="core")
    op.add_column("lots", sa.Column("funding_partner_suggested", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("funding_readiness", postgresql.JSONB(astext_type=sa.Text())), schema="core")
    op.add_column("lots", sa.Column("package_sent_to", sa.Text()), schema="core")
    op.add_column("lots", sa.Column("package_sent_at", sa.DateTime(timezone=True)), schema="core")
    op.create_check_constraint("ck_core_lots_sale_type", "lots", "sale_type IS NULL OR sale_type IN ('presale','spec','showhome','other')", schema="core")
    op.create_check_constraint("ck_core_lots_building_type", "lots", "building_type IS NULL OR building_type IN ('bungalow','two_storey','duplex','other')", schema="core")
    op.create_foreign_key("fk_core_lots_active_approval_letter", "lots", "presale_approval_letters", ["active_approval_letter_id"], ["id"], source_schema="core", referent_schema="core", ondelete="SET NULL")

    op.add_column("budgets", sa.Column("is_prelim", sa.Boolean(), nullable=False, server_default=sa.text("false")), schema="costbook")
    op.add_column("budgets", sa.Column("requested_at", sa.DateTime(timezone=True)), schema="costbook")
    op.add_column("budgets", sa.Column("received_at", sa.DateTime(timezone=True)), schema="costbook")

    rules = sa.table(
        "funding_partner_rules",
        sa.column("partner_code", sa.Text()),
        sa.column("display_name", sa.Text()),
        sa.column("priority", sa.Integer()),
        sa.column("required_docs", postgresql.JSONB()),
        sa.column("required_fields", postgresql.JSONB()),
        sa.column("disqualifying_conditions", postgresql.JSONB()),
        sa.column("min_quality_score", sa.Integer()),
        sa.column("formula", postgresql.JSONB()),
        sa.column("max_advance_rule", postgresql.JSONB()),
        sa.column("package_recipient", sa.Text()),
        sa.column("package_docs", postgresql.JSONB()),
        sa.column("active", sa.Boolean()),
        schema="core",
    )
    op.bulk_insert(rules, [
        {
            "partner_code": "SCU",
            "display_name": "Steinbach Credit Union",
            "priority": 1,
            "required_docs": ["approval_letter", "appraisal", "otp_land", "otp_sale", "stamped_plans", "prelim_budget"],
            "required_fields": [],
            "disqualifying_conditions": ["sale_of_existing_home"],
            "min_quality_score": 6,
            "formula": None,
            "max_advance_rule": None,
            "package_recipient": None,
            "package_docs": ["approval_letter", "otp_land", "otp_sale", "stamped_plans", "appraisal", "prelim_budget"],
            "active": True,
        },
        {
            "partner_code": "PROAUTO",
            "display_name": "PROAuto",
            "priority": 2,
            "required_docs": ["approval_letter", "otp_land", "otp_sale", "prelim_budget"],
            "required_fields": ["otp_sale.sale_price", "lot.building_type", "prelim_budget.total", "otp_land.lot_cost"],
            "disqualifying_conditions": [],
            "min_quality_score": None,
            "formula": {"type": "pct_of_sum", "pct": 0.90, "inputs": ["otp_land.lot_cost", "prelim_budget.total"]},
            "max_advance_rule": None,
            "package_recipient": None,
            "package_docs": ["approval_letter", "otp_land", "otp_sale", "prelim_budget"],
            "active": True,
        },
    ])


def downgrade() -> None:
    op.drop_column("budgets", "received_at", schema="costbook")
    op.drop_column("budgets", "requested_at", schema="costbook")
    op.drop_column("budgets", "is_prelim", schema="costbook")
    op.drop_constraint("fk_core_lots_active_approval_letter", "lots", schema="core", type_="foreignkey")
    op.drop_constraint("ck_core_lots_building_type", "lots", schema="core", type_="check")
    op.drop_constraint("ck_core_lots_sale_type", "lots", schema="core", type_="check")
    for column in (
        "package_sent_at", "package_sent_to", "funding_readiness", "funding_partner_suggested",
        "active_approval_letter_id", "realtor_brokerage", "realtor_email", "realtor_name",
        "building_type", "sale_type",
    ):
        op.drop_column("lots", column, schema="core")
    op.drop_table("presale_notifications", schema="core")
    op.drop_table("presale_tasks", schema="core")
    op.drop_table("presale_package_items", schema="core")
    op.drop_table("funding_partner_rules", schema="core")
    op.drop_table("presale_approval_letters", schema="core")
    op.execute("UPDATE documents.documents SET doc_type = 'other' WHERE doc_type IN ('appraisal','stamped_plans')")
    op.drop_constraint("doc_type", "documents", schema="documents", type_="check")
    op.alter_column("documents", "doc_type", type_=sa.String(length=8), schema="documents")
    op.create_check_constraint(
        "doc_type",
        "documents",
        "doc_type IN ('land_otp','sale_otp','invoice','legal','other')",
        schema="documents",
    )
