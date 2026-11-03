"""Rental lease agreement snapshots and property utility defaults.

Revision ID: 20261102_0055
Revises: 20261020_0053
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261102_0055"
down_revision = "20261020_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rental_properties", sa.Column("municipality", sa.String(100)))
    op.add_column("rental_properties", sa.Column("is_multiplex", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("rental_properties", sa.Column("is_condo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("rental_properties", sa.Column("lease_utility_override", JSONB()))
    op.execute("""UPDATE rental_properties SET municipality = CASE
        WHEN group_name IN ('Grande Pointe', 'Landmark', 'Lorette') THEN group_name
        ELSE city END""")
    op.execute("UPDATE rental_properties SET is_multiplex = true WHERE group_name = 'Guay'")
    op.create_table("lease_agreements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("rental_units.id"), nullable=False),
        sa.Column("tenancy_id", sa.Integer(), sa.ForeignKey("rental_leases.id")),
        sa.Column("template_version", sa.Text(), nullable=False, server_default="v1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context", JSONB(), nullable=False), sa.Column("tenants", JSONB(), nullable=False),
        sa.Column("draft_docx_key", sa.Text()), sa.Column("draft_pdf_key", sa.Text()),
        sa.Column("docusign_envelope_id", sa.Text(), unique=True),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column("signed_pdf_box_file_id", sa.Text()),
        sa.Column("contact_form_data", JSONB()), sa.Column("recipient_status", JSONB()),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','sent','delivered','completed','declined','voided')", name="ck_lease_agreement_status"))
    op.create_index("ix_lease_agreements_unit_created", "lease_agreements", ["unit_id", "created_at"])
    op.create_table("lease_agreement_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lease_agreement_id", UUID(as_uuid=True), sa.ForeignKey("lease_agreements.id"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("detail", JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("lease_agreement_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lease_agreement_id", UUID(as_uuid=True), sa.ForeignKey("lease_agreements.id"), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute("UPDATE core.users SET permissions = (permissions::jsonb || '{\"rentals\":\"editor\"}'::jsonb)::json WHERE role = 'staff' AND COALESCE(permissions->>'rentals', 'none') = 'none'")
    op.execute("UPDATE core.users SET permissions = (permissions::jsonb || '{\"rentals\":\"viewer\"}'::jsonb)::json WHERE role = 'readonly' AND COALESCE(permissions->>'rentals', 'none') = 'none'")


def downgrade() -> None:
    op.drop_table("lease_agreement_tasks")
    op.drop_table("lease_agreement_events")
    op.drop_index("ix_lease_agreements_unit_created", table_name="lease_agreements")
    op.drop_table("lease_agreements")
    op.drop_column("rental_properties", "lease_utility_override")
    op.drop_column("rental_properties", "is_multiplex")
    op.drop_column("rental_properties", "is_condo")
    op.drop_column("rental_properties", "municipality")
