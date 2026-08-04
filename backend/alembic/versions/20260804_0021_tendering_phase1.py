"""Add tendering Phase 1 tables.

Revision ID: 20260804_0021
Revises: 20260731_0020
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260804_0021"
down_revision: str | None = "20260731_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORIES = [
    ("Framing", "framing"), ("Electrical", "electrical"), ("Plumbing", "plumbing"),
    ("HVAC", "hvac"), ("Drywall", "drywall"), ("Roofing", "roofing"),
    ("Concrete/Foundation", "concrete-foundation"), ("Excavation", "excavation"),
    ("Painting", "painting"), ("Flooring", "flooring"), ("Landscaping", "landscaping"),
    ("Insulation", "insulation"), ("Windows & Doors", "windows-doors"),
    ("General Contractor", "general-contractor"), ("Other", "other"),
]


def upgrade() -> None:
    op.create_table(
        "contractor_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="core",
    )
    category_table = sa.Table(
        "contractor_categories",
        sa.MetaData(),
        sa.Column("name", sa.Text()),
        sa.Column("slug", sa.Text()),
        schema="core",
    )
    op.bulk_insert(category_table, [{"name": name, "slug": slug} for name, slug in CATEGORIES])
    op.create_table(
        "contractors",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False), sa.Column("contact_name", sa.Text()),
        sa.Column("email", sa.Text()), sa.Column("phone", sa.String(50)), sa.Column("address", sa.Text()),
        sa.Column("notes", sa.Text()), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="core",
    )
    op.create_table(
        "contractor_category_links",
        sa.Column("contractor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.contractors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.contractor_categories.id", ondelete="CASCADE"), primary_key=True),
        schema="core",
    )
    op.create_table(
        "tender_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.contractor_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"), sa.Column("due_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','sent','bids_in','compared','awarded','cancelled')", name="ck_tender_packages_status"),
        schema="core",
    )
    op.create_index("ix_core_tender_packages_property_id", "tender_packages", ["property_id"], schema="core")
    op.create_table(
        "tender_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tender_package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.tender_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False), sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("document_type IN ('plan','markup','spec')", name="ck_tender_documents_type"),
        sa.UniqueConstraint("tender_package_id", "file_path", name="uq_tender_documents_package_path"),
        schema="documents",
    )
    op.create_index("ix_documents_tender_documents_package_id", "tender_documents", ["tender_package_id"], schema="documents")


def downgrade() -> None:
    op.drop_table("tender_documents", schema="documents")
    op.drop_table("tender_packages", schema="core")
    op.drop_table("contractor_category_links", schema="core")
    op.drop_table("contractors", schema="core")
    op.drop_table("contractor_categories", schema="core")
