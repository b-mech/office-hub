"""Add PRIVI rentals data architecture.

Revision ID: 20260809_0029
Revises: 20260807_0028
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0029"
down_revision: str | None = "20260807_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rental_companies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "rental_properties",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("rental_companies.id"), nullable=False),
        sa.Column("group_name", sa.String(100)),
        sa.Column("street_address", sa.String(255), nullable=False),
        sa.Column("former_address", sa.String(255)),
        sa.Column("city", sa.String(100), server_default="Winnipeg"),
        sa.Column("property_type", sa.String(30), nullable=False, server_default="residential"),
        sa.Column("general_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "street_address", name="uq_rental_properties_company_address"),
        sa.CheckConstraint("property_type IN ('residential', 'commercial')", name="chk_rental_property_type"),
    )
    op.create_index("idx_rental_properties_company", "rental_properties", ["company_id"])
    op.create_index("idx_rental_properties_group", "rental_properties", ["group_name"])
    op.create_table(
        "rental_units",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("rental_properties.id"), nullable=False),
        sa.Column("unit_label", sa.String(50)),
        sa.Column("is_basement", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("water_credit_amount", sa.Numeric(8, 2)),
        sa.Column("water_deal_raw", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("property_id", "unit_label", name="uq_rental_units_property_label", postgresql_nulls_not_distinct=True),
        sa.CheckConstraint("status IN ('occupied', 'vacant', 'unknown')", name="chk_rental_unit_status"),
    )
    op.create_index("idx_rental_units_property", "rental_units", ["property_id"])
    op.create_table(
        "rental_tenants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column("email", sa.String(150)),
        sa.Column("secondary_email", sa.String(150)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_rental_tenants_full_name_ci", "rental_tenants", [sa.text("lower(full_name)")], unique=True)
    op.create_table(
        "rental_leases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("rental_units.id"), nullable=False),
        sa.Column("rent", sa.Numeric(8, 2), nullable=False),
        sa.Column("rent_discount_amount", sa.Numeric(8, 2)),
        sa.Column("rent_discount_raw", sa.String(100)),
        sa.Column("deposit", sa.Numeric(8, 2)),
        sa.Column("lease_start", sa.Date()),
        sa.Column("lease_end", sa.Date()),
        sa.Column("date_parse_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("lease_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'month_to_month', 'expired', 'terminated')", name="chk_rental_lease_status"),
    )
    op.create_index("idx_rental_leases_unit", "rental_leases", ["unit_id"])
    op.create_index("idx_rental_leases_status", "rental_leases", ["status"])
    op.create_table(
        "rental_lease_tenants",
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("rental_leases.id"), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("rental_tenants.id"), primary_key=True),
        sa.Column("is_primary_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "rental_inspections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("rental_units.id"), nullable=False),
        sa.Column("inspection_type", sa.String(20), nullable=False, server_default="exterior"),
        sa.Column("inspection_date", sa.Date(), nullable=False),
        sa.Column("inspector_name", sa.String(100)),
        sa.Column("front_yard_score", sa.SmallInteger()),
        sa.Column("front_yard_notes", sa.Text()),
        sa.Column("back_yard_score", sa.SmallInteger()),
        sa.Column("back_yard_notes", sa.Text()),
        sa.Column("building_condition", sa.String(50)),
        sa.Column("building_notes", sa.Text()),
        sa.Column("occupancy_flag", sa.String(20)),
        sa.Column("general_notes", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("unit_id", "inspection_date", "inspection_type", name="uq_rental_inspections_unit_date_type"),
        sa.CheckConstraint("front_yard_score BETWEEN 1 AND 10", name="chk_front_yard_score"),
        sa.CheckConstraint("back_yard_score BETWEEN 1 AND 10", name="chk_back_yard_score"),
        sa.CheckConstraint("inspection_type IN ('exterior', 'interior')", name="chk_rental_inspection_type"),
        sa.CheckConstraint("status IN ('draft', 'submitted')", name="chk_rental_inspection_status"),
    )
    op.create_index("idx_rental_inspections_unit", "rental_inspections", ["unit_id"])
    op.create_index("idx_rental_inspections_date", "rental_inspections", ["inspection_date"])
    op.create_table(
        "rental_inspection_photos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("inspection_id", sa.Integer(), sa.ForeignKey("rental_inspections.id"), nullable=False),
        sa.Column("box_file_id", sa.String(100)),
        sa.Column("box_folder_path", sa.String(500)),
        sa.Column("caption", sa.String(255)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_rental_inspection_photos_inspection", "rental_inspection_photos", ["inspection_id"])
    op.execute("INSERT INTO rental_companies (name) VALUES ('PRIVI') ON CONFLICT (name) DO NOTHING")


def downgrade() -> None:
    op.drop_table("rental_inspection_photos")
    op.drop_table("rental_inspections")
    op.drop_table("rental_lease_tenants")
    op.drop_table("rental_leases")
    op.drop_table("rental_tenants")
    op.drop_table("rental_units")
    op.drop_table("rental_properties")
    op.drop_table("rental_companies")
