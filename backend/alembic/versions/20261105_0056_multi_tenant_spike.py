"""Add org memberships and lot project ACLs.

Revision ID: 20261105_0056
Revises: 20261022_0054
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261105_0056"
down_revision: str | None = "20261022_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="core",
    )
    op.create_table(
        "user_org_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('tenant_admin', 'member')", name="ck_core_user_org_memberships_role"),
        sa.UniqueConstraint("user_id", "org_id", name="uq_core_user_org_memberships_user_org"),
        schema="core",
    )
    op.create_index("idx_core_user_org_memberships_org_id", "user_org_memberships", ["org_id"], schema="core")
    op.create_table(
        "project_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_core_project_members_role"),
        sa.UniqueConstraint("lot_id", "user_id", name="uq_core_project_members_lot_user"),
        schema="core",
    )
    op.create_index("idx_core_project_members_user_id", "project_members", ["user_id"], schema="core")
    op.create_index("idx_core_project_members_lot_id", "project_members", ["lot_id"], schema="core")

    op.execute(sa.text("""
        INSERT INTO core.orgs (name, slug)
        VALUES ('Potterstone Builders', 'potterstone-builders'),
               ('PRIVI Holdings', 'privi-holdings')
        ON CONFLICT (slug) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO core.user_org_memberships (user_id, org_id, role)
        SELECT id, org_id, CASE WHEN role = 'admin' THEN 'tenant_admin' ELSE 'member' END
        FROM core.users
        WHERE true
        ON CONFLICT (user_id, org_id) DO NOTHING
    """))
    op.execute(sa.text("""
        UPDATE core.users SET is_superadmin = true
        WHERE email = 'nicholas@connectionhomes.ca'
    """))


def downgrade() -> None:
    raise RuntimeError("This additive tenant migration is intentionally not reversible")
