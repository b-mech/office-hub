"""Split 22/24 Oak Meadow into one property per legal lot.

Revision ID: 20260903_0040
Revises: 20260903_0039
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_0040"
down_revision: str | None = "20260903_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMBINED_PROPERTY = "afe24519-8e9d-47b9-a2cc-85c92f87b5f1"
LOT_22 = "ca971418-38a8-42d5-a88d-63c1dc0980ff"
LOT_24 = "61303b37-e937-48be-9abc-88089b6651b7"
GROUP = "98501644-f0ac-4bba-b4bc-0c93e6314224"
PROPERTY_22 = "38d62f41-6624-49e0-b83a-ad9d077f6784"
PROPERTY_24 = "920b3216-5d4c-4c54-8234-c3bc259f8460"


def upgrade() -> None:
    bind = op.get_bind()
    state = bind.execute(sa.text("""
        SELECT p.id AS property_id, l22.development_id, d.org_id
        FROM core.properties p
        JOIN core.lots l22 ON l22.id=:lot22 AND l22.property_id=p.id
        JOIN core.lots l24 ON l24.id=:lot24 AND l24.property_id=p.id
        JOIN core.developments d ON d.id=l22.development_id
        WHERE p.id=:property AND l24.development_id=l22.development_id
        FOR UPDATE OF p, l22, l24
    """), {"property": COMBINED_PROPERTY, "lot22": LOT_22, "lot24": LOT_24}).mappings().one_or_none()
    if state is None:
        raise RuntimeError("22/24 Oak Meadow preflight failed: expected combined property and two lots")

    unexpected = bind.execute(sa.text("""
        SELECT
          (SELECT count(*) FROM core.lender_facilities WHERE property_id=:property) AS facilities,
          (SELECT count(*) FROM core.tender_packages WHERE property_id=:property) AS tenders,
          (SELECT count(*) FROM documents.client_draw_requests WHERE property_id=:property) AS client_draw_requests,
          (SELECT count(*) FROM documents.client_draw_schedules WHERE property_id=:property) AS client_draw_schedules,
          (SELECT count(*) FROM documents.pro_draw_requests WHERE property_id=:property) AS pro_draw_requests
    """), {"property": COMBINED_PROPERTY}).mappings().one()
    if any(unexpected.values()):
        raise RuntimeError(f"22/24 Oak Meadow has unexpected property references: {dict(unexpected)}")

    bind.execute(sa.text("""
        INSERT INTO core.build_groups(id,org_id,development_id,group_type,display_name,status)
        VALUES (:group,:org,:development,'duplex','22/24 Oak Meadow Drive','active')
    """), {"group": GROUP, "org": state["org_id"], "development": state["development_id"]})
    bind.execute(sa.text("""
        INSERT INTO core.properties(id,address,address_normalized,canonical_address_key,property_type)
        VALUES
          (:p22,'22 Oak Meadow Drive','22 OAK MEADOW DRIVE','22 OAK MEADOW DR OAKBANK','lot'),
          (:p24,'24 Oak Meadow Drive','24 OAK MEADOW DRIVE','24 OAK MEADOW DR OAKBANK','lot')
    """), {"p22": PROPERTY_22, "p24": PROPERTY_24})
    bind.execute(sa.text("""
        UPDATE core.lots
        SET property_id=CASE id WHEN :lot22 THEN CAST(:p22 AS uuid) ELSE CAST(:p24 AS uuid) END,
            build_group_id=:group
        WHERE id IN (:lot22,:lot24)
    """), {"lot22": LOT_22, "lot24": LOT_24, "p22": PROPERTY_22, "p24": PROPERTY_24, "group": GROUP})
    bind.execute(sa.text("""
        UPDATE financing.allocation_requests
        SET property_id=CASE lot_id WHEN :lot22 THEN CAST(:p22 AS uuid) ELSE CAST(:p24 AS uuid) END
        WHERE property_id=:combined AND lot_id IN (:lot22,:lot24)
    """), {"combined": COMBINED_PROPERTY, "lot22": LOT_22, "lot24": LOT_24, "p22": PROPERTY_22, "p24": PROPERTY_24})
    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        bind.execute(sa.text(f"""
            UPDATE documents.{table}
            SET build_group_id=:group, property_id=NULL
            WHERE property_id=:combined
        """), {"group": GROUP, "combined": COMBINED_PROPERTY})

    remaining = bind.execute(sa.text("""
        SELECT
          (SELECT count(*) FROM core.lots WHERE property_id=:property) +
          (SELECT count(*) FROM financing.allocation_requests WHERE property_id=:property) +
          (SELECT count(*) FROM documents.construction_stage_sync WHERE property_id=:property) +
          (SELECT count(*) FROM documents.construction_stage_history WHERE property_id=:property) +
          (SELECT count(*) FROM documents.construction_stage_milestones WHERE property_id=:property)
    """), {"property": COMBINED_PROPERTY}).scalar_one()
    if remaining:
        raise RuntimeError(f"22/24 Oak Meadow still has {remaining} references after migration")
    bind.execute(sa.text("DELETE FROM core.properties WHERE id=:property"), {"property": COMBINED_PROPERTY})

    bind.execute(sa.text("""
        INSERT INTO core.audit_log(schema_name,table_name,record_id,action,old_data,new_data)
        VALUES
          ('core','build_groups',CAST(:group AS uuid),'INSERT',NULL,json_build_object('display_name','22/24 Oak Meadow Drive','group_type','duplex','member_lots',json_build_array(CAST(:lot22 AS text),CAST(:lot24 AS text)))),
          ('core','properties',CAST(:combined AS uuid),'DELETE',json_build_object('address','22/24 Oak Meadow Drive – SPEC'),json_build_object('split_into',json_build_array(CAST(:p22 AS text),CAST(:p24 AS text)),'build_group_id',CAST(:group AS text))),
          ('core','properties',CAST(:p22 AS uuid),'INSERT',NULL,json_build_object('address','22 Oak Meadow Drive','lot_id',CAST(:lot22 AS text),'build_group_id',CAST(:group AS text))),
          ('core','properties',CAST(:p24 AS uuid),'INSERT',NULL,json_build_object('address','24 Oak Meadow Drive','lot_id',CAST(:lot24 AS text),'build_group_id',CAST(:group AS text)))
    """), {"group": GROUP, "combined": COMBINED_PROPERTY, "lot22": LOT_22, "lot24": LOT_24, "p22": PROPERTY_22, "p24": PROPERTY_24})

    duplicate = bind.execute(sa.text("""
        SELECT property_id, count(*) AS lot_count FROM core.lots
        WHERE property_id IS NOT NULL GROUP BY property_id HAVING count(*) > 1 LIMIT 1
    """)).mappings().first()
    if duplicate is not None:
        raise RuntimeError(f"Cannot enforce one lot per property: {dict(duplicate)}")
    op.execute("CREATE UNIQUE INDEX uq_core_lots_property_id_not_null ON core.lots(property_id) WHERE property_id IS NOT NULL")


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("uq_core_lots_property_id_not_null", table_name="lots", schema="core")
    bind.execute(sa.text("""
        INSERT INTO core.properties(id,address,address_normalized,canonical_address_key,property_type)
        VALUES (:combined,'22/24 Oak Meadow Drive – SPEC','22 24 OAK MEADOW DRIVE SPEC','22-24 OAK MEADOW DR OAKBANK','lot')
    """), {"combined": COMBINED_PROPERTY})
    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        bind.execute(sa.text(f"""
            UPDATE documents.{table} SET property_id=:combined, build_group_id=NULL
            WHERE build_group_id=:group
        """), {"combined": COMBINED_PROPERTY, "group": GROUP})
    bind.execute(sa.text("UPDATE financing.allocation_requests SET property_id=:combined WHERE lot_id IN (:lot22,:lot24)"), {"combined": COMBINED_PROPERTY, "lot22": LOT_22, "lot24": LOT_24})
    bind.execute(sa.text("UPDATE core.lots SET property_id=:combined, build_group_id=NULL WHERE id IN (:lot22,:lot24)"), {"combined": COMBINED_PROPERTY, "lot22": LOT_22, "lot24": LOT_24})
    bind.execute(sa.text("DELETE FROM core.properties WHERE id IN (:p22,:p24)"), {"p22": PROPERTY_22, "p24": PROPERTY_24})
    bind.execute(sa.text("DELETE FROM core.build_groups WHERE id=:group"), {"group": GROUP})
