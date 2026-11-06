"""Office Hub password sign-in: password hash and session version on users.

Revision ID: 20261106_0058
Revises: 20261106_0057

* ``core.users.password_hash``: bcrypt hash (``$2b$``), NULL = no password set.
  NULL users cannot use password sign-in; nothing is backfilled.
* ``core.users.password_changed_at``: audit timestamp of the last set/change.
* ``core.users.session_version``: embedded in session cookies as ``sv``.
  Bumping it (sign-out, password change) revokes every outstanding session of
  that user server-side.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261106_0058"
down_revision: str | None = "20261106_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True), schema="core")
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
        schema="core",
    )
    op.create_check_constraint(
        "ck_core_users_password_hash_bcrypt",
        "users",
        "password_hash IS NULL OR password_hash LIKE '$2%'",
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint("ck_core_users_password_hash_bcrypt", "users", schema="core", type_="check")
    op.drop_column("users", "session_version", schema="core")
    op.drop_column("users", "password_changed_at", schema="core")
    op.drop_column("users", "password_hash", schema="core")
