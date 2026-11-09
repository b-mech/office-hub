"""Store reviewed lot and rental geocodes; do not trust legacy rental points.

0058 belongs to PR #3. Before merging both branches, add a merge revision
with parents 20261106_0058 and the latest map-branch head (now
20261109_0060); do not merge the obsolete 0059 head after 0060 exists.
Lot locations live on core.lots: 116/153 QA lots have no property_id.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0059"
down_revision = "20261106_0057"
branch_labels = None
depends_on = None


def upgrade():
    for table, schema in [("lots", "core"), ("rental_properties", None)]:
        if table == "lots":
            op.add_column(table, sa.Column("latitude", sa.Numeric(9, 6)), schema=schema)
            op.add_column(table, sa.Column("longitude", sa.Numeric(9, 6)), schema=schema)
        op.add_column(table, sa.Column("geocode_precision", sa.String(20)), schema=schema)
        op.add_column(table, sa.Column("geocode_source", sa.String(100)), schema=schema)
        op.add_column(table, sa.Column("geocoded_at", sa.DateTime(timezone=True)), schema=schema)


def downgrade():
    for table, schema in [("rental_properties", None), ("lots", "core")]:
        for name in ["geocoded_at", "geocode_source", "geocode_precision"]:
            op.drop_column(table, name, schema=schema)
        if table == "lots":
            op.drop_column(table, "longitude", schema=schema)
            op.drop_column(table, "latitude", schema=schema)
