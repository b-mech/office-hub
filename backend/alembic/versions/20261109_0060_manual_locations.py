"""Manual pin attribution and reversible geocode snapshot.

PR #3 has the independent 0058 head; retain the documented merge requirement.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261109_0060"
down_revision = "20261109_0059"
branch_labels = None
depends_on = None


def upgrade():
    for table, schema in [("lots", "core"), ("rental_properties", None)]:
        op.add_column(table, sa.Column("location_set_by", postgresql.UUID(as_uuid=True)), schema=schema)
        op.add_column(table, sa.Column("geocode_snapshot", postgresql.JSONB()), schema=schema)
        op.create_foreign_key(f"fk_{table}_location_set_by", table, "users", ["location_set_by"], ["id"], source_schema=schema, referent_schema="core", ondelete="SET NULL")


def downgrade():
    for table, schema in [("rental_properties", None), ("lots", "core")]:
        op.drop_constraint(f"fk_{table}_location_set_by", table, schema=schema, type_="foreignkey")
        op.drop_column(table, "geocode_snapshot", schema=schema)
        op.drop_column(table, "location_set_by", schema=schema)
