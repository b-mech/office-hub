"""Supplemental dated draw confirmations without changing bank balances.

Follows 0060 on PR #2; PR #3's independent 0058 still needs a merge revision
with this branch's latest head (0061) before deploying both histories together.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0061"
down_revision = "20261109_0060"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("facility_transactions", sa.Column("notes", sa.Text(), nullable=True), schema="core")
    op.add_column("facility_transactions", sa.Column("confirmed_by", sa.String(255), nullable=True), schema="core")
    op.add_column("facility_transactions", sa.Column("percent_complete", sa.Numeric(5, 2), nullable=True), schema="core")
    op.create_check_constraint("ck_facility_transactions_percent_complete", "facility_transactions", "percent_complete IS NULL OR percent_complete BETWEEN 0 AND 100", schema="core")


def downgrade():
    op.drop_constraint("ck_facility_transactions_percent_complete", "facility_transactions", schema="core", type_="check")
    for column in ["percent_complete", "confirmed_by", "notes"]:
        op.drop_column("facility_transactions", column, schema="core")
