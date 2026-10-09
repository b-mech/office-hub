"""Track scheduled visit disposition independently of work-order status.

Revision ID: 20261009_0051
Revises: 20261005_0050
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0051"
down_revision: str | None = "20261005_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("maint_work_orders", sa.Column("scheduled_visit_status", sa.Text()))
    op.create_check_constraint(
        "ck_maint_work_orders_scheduled_visit_status",
        "maint_work_orders",
        "scheduled_visit_status IS NULL OR scheduled_visit_status IN ('scheduled','completed','cancelled')",
    )
    op.execute(
        "UPDATE maint_work_orders SET scheduled_visit_status = 'scheduled' "
        "WHERE scheduled_start IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_maint_work_orders_scheduled_visit_status",
        "maint_work_orders",
        type_="check",
    )
    op.drop_column("maint_work_orders", "scheduled_visit_status")
