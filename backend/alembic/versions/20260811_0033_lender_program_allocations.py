"""Add lender program allocations and capacity requests.

Revision ID: 20260811_0033
Revises: 20260810_0031
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_0033"
down_revision: str | None = "20260810_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS financing")
    op.create_table(
        "lender_programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("lender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lenders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("umbrella_limit", sa.Numeric(15, 2), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lender_id", "name", name="uq_lender_programs_lender_name"),
        sa.CheckConstraint("umbrella_limit >= 0", name="ck_lender_programs_umbrella_limit"),
        schema="financing",
    )
    op.create_index("idx_lender_programs_lender", "lender_programs", ["lender_id"], schema="financing")
    op.create_table(
        "program_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financing.lender_programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("allocation_limit", sa.Numeric(15, 2), nullable=False),
        sa.Column("max_units", sa.Integer(), nullable=False),
        sa.Column("max_per_unit", sa.Numeric(15, 2)),
        sa.Column("funding_percentage", sa.Numeric(7, 6), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.UniqueConstraint("program_id", "name", name="uq_program_allocations_program_name"),
        sa.CheckConstraint("allocation_limit >= 0", name="ck_program_allocations_limit"),
        sa.CheckConstraint("max_units >= 0", name="ck_program_allocations_max_units"),
        sa.CheckConstraint("max_per_unit IS NULL OR max_per_unit >= 0", name="ck_program_allocations_max_per_unit"),
        sa.CheckConstraint("funding_percentage >= 0", name="ck_program_allocations_funding_percentage"),
        schema="financing",
    )
    op.create_index("idx_program_allocations_program", "program_allocations", ["program_id"], schema="financing")
    op.create_table(
        "allocation_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financing.program_allocations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("face_value", sa.Numeric(15, 2), nullable=False),
        sa.Column("slot_count", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text()),
        sa.CheckConstraint("face_value >= 0", name="ck_allocation_tiers_face_value"),
        sa.CheckConstraint("slot_count >= 0", name="ck_allocation_tiers_slot_count"),
        schema="financing",
    )
    op.create_index("idx_allocation_tiers_allocation", "allocation_tiers", ["allocation_id"], schema="financing")
    op.create_table(
        "allocation_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financing.program_allocations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="SET NULL")),
        sa.Column("appraisal_value", sa.Numeric(15, 2)),
        sa.Column("estimated_sale_price", sa.Numeric(15, 2)),
        sa.Column("basis_value", sa.Numeric(15, 2), nullable=False),
        sa.Column("basis_source", sa.Text(), nullable=False),
        sa.Column("suggested_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("actual_amount", sa.Numeric(15, 2)),
        sa.Column("nearest_tier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financing.allocation_tiers.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.CheckConstraint("basis_value >= 0", name="ck_allocation_requests_basis_value"),
        sa.CheckConstraint("suggested_amount >= 0", name="ck_allocation_requests_suggested_amount"),
        sa.CheckConstraint("actual_amount IS NULL OR actual_amount >= 0", name="ck_allocation_requests_actual_amount"),
        sa.CheckConstraint("status IN ('draft','requested','approved','released')", name="ck_allocation_requests_status"),
        sa.CheckConstraint("basis_source IN ('appraisal','estimated_sale_price','lesser_of_appraisal_and_estimated_sale_price','lot_purchase_price','explicit_historical')", name="ck_allocation_requests_basis_source"),
        schema="financing",
    )
    op.create_index("idx_allocation_requests_allocation_status", "allocation_requests", ["allocation_id", "status"], schema="financing")
    op.create_index("idx_allocation_requests_lot", "allocation_requests", ["lot_id"], schema="financing")


def downgrade() -> None:
    op.drop_table("allocation_requests", schema="financing")
    op.drop_table("allocation_tiers", schema="financing")
    op.drop_table("program_allocations", schema="financing")
    op.drop_table("lender_programs", schema="financing")
    op.execute("DROP SCHEMA IF EXISTS financing")
