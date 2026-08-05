"""Manually activate confirmed Woodland Way projects.

Revision ID: 20260805_0025
Revises: 20260805_0024
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260805_0025"
down_revision: str | None = "20260805_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LOT_IDS = (
    "16ee6ac1-1ea4-4692-a76f-5b1d15236068",  # 185 Woodland Way
    "edb82243-5a84-4275-8635-6baaaea4ed04",  # 217 Woodland Way
)


def upgrade() -> None:
    result = op.get_bind().execute(
        sa.text(
            """
            UPDATE core.lots
            SET trigger_type = 'otp'
            WHERE id IN (:lot_185, :lot_217)
              AND trigger_type IS NULL
            """
        ),
        {"lot_185": LOT_IDS[0], "lot_217": LOT_IDS[1]},
    )
    if result.rowcount not in {0, 1, 2}:
        raise RuntimeError(f"Expected to update at most 2 Woodland Way lots; updated {result.rowcount}")


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE core.lots
            SET trigger_type = NULL
            WHERE id IN (:lot_185, :lot_217)
              AND trigger_type = 'otp'
            """
        ),
        {"lot_185": LOT_IDS[0], "lot_217": LOT_IDS[1]},
    )
