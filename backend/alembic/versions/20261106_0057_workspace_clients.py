"""Add tenant-owned clients, lots.client_id, and org project/land scope flags.

Revision ID: 20261106_0057
Revises: 20261105_0056

* ``core.orgs.member_project_scope``: ``org`` lets plain members work on every
  project of the org (Connection Homes, backward compatible with zero
  ``project_members`` rows); ``assigned`` (default, Potterstone) requires a
  ``project_members`` grant.
* ``core.orgs.land_enabled``: the org runs the land/OTP module (CH only).
* ``core.clients``: one tenant-owned record per client; no backfill.
* ``core.lots.client_id``: optional link from a project lot to its client.
  A trigger rejects links whose client org differs from the lot's
  development org, and ``core.clients.org_id`` is immutable.
* ``core.contacts`` gains a unique ``(id, org_id)`` so the client's optional
  primary contact is held to the same org by a composite foreign key.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261106_0057"
down_revision: str | None = "20261105_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column("member_project_scope", sa.String(length=8), nullable=False, server_default="assigned"),
        schema="core",
    )
    op.create_check_constraint(
        "ck_core_orgs_member_project_scope",
        "orgs",
        "member_project_scope IN ('org', 'assigned')",
        schema="core",
    )
    op.add_column(
        "orgs",
        sa.Column("land_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="core",
    )
    op.execute(sa.text("""
        UPDATE core.orgs
        SET member_project_scope = 'org', land_enabled = true
        WHERE slug = 'connection-homes'
    """))

    op.create_unique_constraint("uq_core_contacts_id_org", "contacts", ["id", "org_id"], schema="core")

    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.orgs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_type", sa.String(length=10), nullable=False, server_default="individual"),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), nullable=False),
        sa.Column("primary_contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lifecycle_stage", sa.String(length=12), nullable=False, server_default="lead"),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("client_type IN ('individual', 'company')", name="ck_core_clients_client_type"),
        sa.CheckConstraint(
            "lifecycle_stage IN ('lead', 'qualified', 'active', 'possession', 'warranty', 'closed', 'lost')",
            name="ck_core_clients_lifecycle_stage",
        ),
        sa.CheckConstraint("btrim(display_name) <> ''", name="ck_core_clients_display_name_not_blank"),
        sa.ForeignKeyConstraint(
            ["primary_contact_id", "org_id"],
            ["core.contacts.id", "core.contacts.org_id"],
            name="fk_core_clients_primary_contact_same_org",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "org_id", name="uq_core_clients_id_org"),
        schema="core",
    )
    op.create_index("idx_core_clients_org_name", "clients", ["org_id", "name_normalized"], schema="core")
    op.create_index("idx_core_clients_org_stage", "clients", ["org_id", "lifecycle_stage"], schema="core")
    op.create_index("idx_core_clients_primary_contact", "clients", ["primary_contact_id"], schema="core")
    op.create_index(
        "uq_core_clients_org_external_ref",
        "clients",
        ["org_id", "external_ref"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.add_column(
        "lots",
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.clients.id", ondelete="RESTRICT", name="fk_core_lots_client_id"),
            nullable=True,
        ),
        schema="core",
    )
    op.create_index("idx_core_lots_client_id", "lots", ["client_id"], schema="core",
                    postgresql_where=sa.text("client_id IS NOT NULL"))

    op.execute(sa.text("""
        CREATE FUNCTION core.enforce_lot_client_org() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            client_org uuid;
            lot_org uuid;
        BEGIN
            IF NEW.client_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT org_id INTO client_org FROM core.clients WHERE id = NEW.client_id;
            SELECT org_id INTO lot_org FROM core.developments WHERE id = NEW.development_id;
            IF client_org IS NULL OR lot_org IS NULL OR client_org <> lot_org THEN
                RAISE EXCEPTION 'client % and lot % belong to different orgs', NEW.client_id, NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_core_lots_client_org
        BEFORE INSERT OR UPDATE OF client_id, development_id ON core.lots
        FOR EACH ROW EXECUTE FUNCTION core.enforce_lot_client_org()
    """))
    op.execute(sa.text("""
        CREATE FUNCTION core.enforce_development_client_org() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.org_id IS DISTINCT FROM OLD.org_id AND EXISTS (
                SELECT 1 FROM core.lots l JOIN core.clients c ON c.id = l.client_id
                WHERE l.development_id = NEW.id AND c.org_id <> NEW.org_id
            ) THEN
                RAISE EXCEPTION 'development % has lots linked to clients of another org', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_core_developments_client_org
        BEFORE UPDATE OF org_id ON core.developments
        FOR EACH ROW EXECUTE FUNCTION core.enforce_development_client_org()
    """))
    op.execute(sa.text("""
        CREATE FUNCTION core.prevent_client_org_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.org_id IS DISTINCT FROM OLD.org_id THEN
                RAISE EXCEPTION 'core.clients.org_id is immutable' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_core_clients_org_immutable
        BEFORE UPDATE OF org_id ON core.clients
        FOR EACH ROW EXECUTE FUNCTION core.prevent_client_org_change()
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_core_clients_org_immutable ON core.clients"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS core.prevent_client_org_change()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_core_developments_client_org ON core.developments"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS core.enforce_development_client_org()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_core_lots_client_org ON core.lots"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS core.enforce_lot_client_org()"))
    op.drop_index("idx_core_lots_client_id", table_name="lots", schema="core")
    op.drop_column("lots", "client_id", schema="core")
    op.drop_table("clients", schema="core")
    op.drop_constraint("uq_core_contacts_id_org", "contacts", schema="core", type_="unique")
    op.drop_column("orgs", "land_enabled", schema="core")
    op.drop_constraint("ck_core_orgs_member_project_scope", "orgs", schema="core", type_="check")
    op.drop_column("orgs", "member_project_scope", schema="core")
