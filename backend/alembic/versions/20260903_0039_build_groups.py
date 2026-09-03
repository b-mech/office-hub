"""Add build groups and group-level construction and funding targets.

Revision ID: 20260903_0039
Revises: 20260901_0038
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260903_0039"
down_revision: str | None = "20260901_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "build_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.orgs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("development_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.developments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("group_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("group_type IN ('duplex')", name="ck_core_build_groups_type"),
        sa.CheckConstraint("status IN ('proposed','active','completed','cancelled')", name="ck_core_build_groups_status"),
        schema="core",
    )
    op.create_index("idx_core_build_groups_org_status", "build_groups", ["org_id", "status"], schema="core")
    op.create_index("idx_core_build_groups_development", "build_groups", ["development_id"], schema="core")

    op.add_column("lots", sa.Column("build_group_id", postgresql.UUID(as_uuid=True)), schema="core")
    op.create_foreign_key("fk_core_lots_build_group_id", "lots", "build_groups", ["build_group_id"], ["id"], source_schema="core", referent_schema="core", ondelete="RESTRICT")
    op.create_index("idx_core_lots_build_group_id", "lots", ["build_group_id"], schema="core")

    op.add_column("lender_facilities", sa.Column("build_group_id", postgresql.UUID(as_uuid=True)), schema="core")
    op.create_foreign_key("fk_core_lender_facilities_build_group_id", "lender_facilities", "build_groups", ["build_group_id"], ["id"], source_schema="core", referent_schema="core", ondelete="SET NULL")
    op.create_index("ix_core_lender_facilities_build_group_id", "lender_facilities", ["build_group_id"], schema="core")

    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        op.add_column(table, sa.Column("build_group_id", postgresql.UUID(as_uuid=True)), schema="documents")
        op.create_foreign_key(f"fk_documents_{table}_build_group_id", table, "build_groups", ["build_group_id"], ["id"], source_schema="documents", referent_schema="core", ondelete="CASCADE")
        op.create_index(f"ix_documents_{table}_build_group_id", table, ["build_group_id"], schema="documents")
    op.alter_column("construction_stage_history", "property_id", nullable=True, schema="documents")
    op.alter_column("construction_stage_milestones", "property_id", nullable=True, schema="documents")
    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        op.create_check_constraint(f"ck_{table}_target", table, "num_nonnulls(property_id, build_group_id) = 1", schema="documents")
    op.create_unique_constraint("uq_construction_stage_milestones_group_event", "construction_stage_milestones", ["build_group_id", "stage", "achieved_at"], schema="documents")

    op.add_column("allocation_tiers", sa.Column("build_group_type", sa.Text()), schema="financing")
    op.add_column("allocation_tiers", sa.Column("amount_per_unit", sa.Numeric(15, 2)), schema="financing")
    op.add_column("allocation_tiers", sa.Column("units_per_group", sa.Integer()), schema="financing")
    op.add_column("allocation_tiers", sa.Column("group_ceiling", sa.Numeric(15, 2)), schema="financing")
    op.create_check_constraint("ck_allocation_tiers_group_config_complete", "allocation_tiers", "(build_group_type IS NULL AND amount_per_unit IS NULL AND units_per_group IS NULL AND group_ceiling IS NULL) OR (build_group_type IS NOT NULL AND amount_per_unit IS NOT NULL AND units_per_group IS NOT NULL AND group_ceiling IS NOT NULL)", schema="financing")
    op.create_check_constraint("ck_allocation_tiers_group_ceiling", "allocation_tiers", "group_ceiling IS NULL OR group_ceiling = amount_per_unit * units_per_group", schema="financing")
    op.execute("""
        UPDATE financing.allocation_tiers
        SET build_group_type='duplex', amount_per_unit=310000.00,
            units_per_group=2, group_ceiling=620000.00, slot_count=2
        WHERE id='fede6593-fc6b-4ec2-a055-b873c77c2760'::uuid
          AND allocation_id='a111c9cb-9e40-4298-a281-2459fd9f5207'::uuid
          AND label='Duplex' AND face_value=310000.00
    """)
    result = op.get_bind().execute(sa.text("""
        SELECT count(*) FROM financing.allocation_tiers
        WHERE id='fede6593-fc6b-4ec2-a055-b873c77c2760'::uuid
          AND build_group_type='duplex' AND amount_per_unit=310000.00
          AND units_per_group=2 AND group_ceiling=620000.00 AND slot_count=2
    """)).scalar_one()
    if result != 1:
        raise RuntimeError("SCU duplex tier was not found or could not be configured explicitly")

    op.create_table(
        "build_group_funding_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("build_group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.build_groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financing.program_allocations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financing.allocation_tiers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_count", sa.Integer(), nullable=False),
        sa.Column("amount_per_unit", sa.Numeric(15, 2), nullable=False),
        sa.Column("group_ceiling", sa.Numeric(15, 2), nullable=False),
        sa.Column("slots_consumed", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("build_group_id", "allocation_id", name="uq_build_group_funding_decisions_group_allocation"),
        sa.CheckConstraint("status IN ('draft','approved','released')", name="ck_build_group_funding_decisions_status"),
        sa.CheckConstraint("unit_count > 0", name="ck_build_group_funding_decisions_unit_count"),
        sa.CheckConstraint("slots_consumed > 0", name="ck_build_group_funding_decisions_slots"),
        sa.CheckConstraint("amount_per_unit >= 0", name="ck_build_group_funding_decisions_amount"),
        sa.CheckConstraint("group_ceiling = amount_per_unit * unit_count", name="ck_build_group_funding_decisions_ceiling"),
        schema="financing",
    )
    op.create_index("idx_build_group_funding_decisions_allocation_status", "build_group_funding_decisions", ["allocation_id", "status"], schema="financing")
    op.add_column("allocation_requests", sa.Column("funding_decision_id", postgresql.UUID(as_uuid=True)), schema="financing")
    op.create_foreign_key("fk_allocation_requests_funding_decision_id", "allocation_requests", "build_group_funding_decisions", ["funding_decision_id"], ["id"], source_schema="financing", referent_schema="financing", ondelete="RESTRICT")
    op.create_index("idx_allocation_requests_funding_decision", "allocation_requests", ["funding_decision_id"], schema="financing")


def downgrade() -> None:
    op.drop_index("idx_allocation_requests_funding_decision", table_name="allocation_requests", schema="financing")
    op.drop_constraint("fk_allocation_requests_funding_decision_id", "allocation_requests", schema="financing", type_="foreignkey")
    op.drop_column("allocation_requests", "funding_decision_id", schema="financing")
    op.drop_table("build_group_funding_decisions", schema="financing")
    op.drop_constraint("ck_allocation_tiers_group_ceiling", "allocation_tiers", schema="financing", type_="check")
    op.drop_constraint("ck_allocation_tiers_group_config_complete", "allocation_tiers", schema="financing", type_="check")
    for column in ("group_ceiling", "units_per_group", "amount_per_unit", "build_group_type"):
        op.drop_column("allocation_tiers", column, schema="financing")
    op.drop_constraint("uq_construction_stage_milestones_group_event", "construction_stage_milestones", schema="documents", type_="unique")
    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        op.drop_constraint(f"ck_{table}_target", table, schema="documents", type_="check")
    op.alter_column("construction_stage_milestones", "property_id", nullable=False, schema="documents")
    op.alter_column("construction_stage_history", "property_id", nullable=False, schema="documents")
    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        op.drop_index(f"ix_documents_{table}_build_group_id", table_name=table, schema="documents")
        op.drop_constraint(f"fk_documents_{table}_build_group_id", table, schema="documents", type_="foreignkey")
        op.drop_column(table, "build_group_id", schema="documents")
    op.drop_index("ix_core_lender_facilities_build_group_id", table_name="lender_facilities", schema="core")
    op.drop_constraint("fk_core_lender_facilities_build_group_id", "lender_facilities", schema="core", type_="foreignkey")
    op.drop_column("lender_facilities", "build_group_id", schema="core")
    op.drop_index("idx_core_lots_build_group_id", table_name="lots", schema="core")
    op.drop_constraint("fk_core_lots_build_group_id", "lots", schema="core", type_="foreignkey")
    op.drop_column("lots", "build_group_id", schema="core")
    op.drop_table("build_groups", schema="core")
