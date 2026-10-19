"""Repair PRO reconciliation property identities and Ramona duplex grouping.

Revision ID: 20261016_0050
Revises: 20261015_0049
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261016_0050"
down_revision: str | None = "20261015_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

P57 = "fc1ccc7a-6722-4364-8ad5-c0ed6842d765"
D57 = "c4881e59-5345-43e7-a389-7cc1d876cfb2"
P8 = "b6a52664-89be-47b2-8d60-b86b3c2aadb9"
D8 = "c6d071bd-d9fa-4c55-aacc-0a57b8241eaa"
RAMONA_COMBINED = "e68e7c8b-8f3b-49b4-a127-e457ed117844"
P149 = "1c602ec5-bb92-4733-adea-f1fe160fae54"
P153 = "bbfeb3d3-2610-469f-ae23-5a5a71d45ede"
F149 = "7890c536-7188-402d-af77-8fba52c02bcb"
F153 = "7b9ccbf4-3864-4b6e-9046-4aa113b8eacd"
RAMONA_GROUP = "97b50f84-187a-4ead-93ba-bf6401d84153"
TEMPLETON_DEVELOPMENT = "51153aa5-f1dc-4f52-96cc-c9b8891fff48"
F217 = "3777cd90-9905-4161-b143-612e519e32c8"
F5GRAY = "2e251c68-94e4-49a7-b12d-cfcd03542064"
DEER_FACILITY = "6d463d98-f1c8-4963-9bb2-88b6d037366c"


def upgrade() -> None:
    bind = op.get_bind()
    expected = {P57, D57, P8, D8, RAMONA_COMBINED, P149, P153}
    found = set(bind.execute(sa.text("SELECT id::text FROM core.properties WHERE id::text = ANY(:ids)"), {"ids": list(expected)}).scalars())
    if found != expected:
        raise RuntimeError(f"PRO property repair preflight failed; missing IDs: {sorted(expected - found)}")

    for duplicate, canonical in ((D57, P57), (D8, P8)):
        for table in ("construction_stage_sync", "construction_stage_history"):
            bind.execute(sa.text(f"UPDATE documents.{table} SET property_id=:canonical WHERE property_id=:duplicate"), {"canonical": canonical, "duplicate": duplicate})
        bind.execute(sa.text("DELETE FROM documents.lender_statement_discrepancies WHERE property_id=:duplicate"), {"duplicate": duplicate})
        bind.execute(sa.text("DELETE FROM core.properties WHERE id=:duplicate"), {"duplicate": duplicate})

    state = bind.execute(sa.text("""
        SELECT d.org_id FROM core.developments d WHERE d.id=:development
    """), {"development": TEMPLETON_DEVELOPMENT}).mappings().one_or_none()
    if state is None:
        raise RuntimeError("Ramona build-group preflight failed: Templeton Gates development not found")
    bind.execute(sa.text("""
        INSERT INTO core.build_groups(id,org_id,development_id,group_type,display_name,status)
        VALUES (:group,:org,:development,'duplex','149/153 Ramona Gallos Way','active')
    """), {"group": RAMONA_GROUP, "org": state["org_id"], "development": TEMPLETON_DEVELOPMENT})
    bind.execute(sa.text("UPDATE core.lender_facilities SET build_group_id=:group WHERE id IN (:f149,:f153)"), {"group": RAMONA_GROUP, "f149": F149, "f153": F153})
    for table in ("construction_stage_sync", "construction_stage_history", "construction_stage_milestones"):
        bind.execute(sa.text(f"UPDATE documents.{table} SET build_group_id=:group, property_id=NULL WHERE property_id=:combined"), {"group": RAMONA_GROUP, "combined": RAMONA_COMBINED})
    bind.execute(sa.text("DELETE FROM documents.lender_statement_discrepancies WHERE property_id=:combined"), {"combined": RAMONA_COMBINED})
    bind.execute(sa.text("DELETE FROM core.properties WHERE id=:combined"), {"combined": RAMONA_COMBINED})

    bind.execute(sa.text("""
        UPDATE core.lender_facilities lf SET
          property_name=p.address,
          canonical_address_key=p.canonical_address_key,
          facility_key=CASE lf.id WHEN CAST(:f217 AS uuid) THEN 'PRO-217-WOODLAND' ELSE 'PRO-5-GRAY' END,
          lender='PRO', updated_at=now()
        FROM core.properties p
        WHERE lf.property_id=p.id AND lf.id IN (:f217,:f5)
    """), {"f217": F217, "f5": F5GRAY})
    bind.execute(sa.text("""
        INSERT INTO core.facility_aliases(facility_id,alias)
        SELECT id, property_name FROM core.lender_facilities WHERE id IN (:f217,:f5)
        ON CONFLICT (alias) DO UPDATE SET facility_id=EXCLUDED.facility_id
    """), {"f217": F217, "f5": F5GRAY})

    deer = bind.execute(sa.text("""
        UPDATE core.facility_transactions
        SET amount=125000.00
        WHERE facility_id=:facility AND reference ILIKE '%47662%' AND amount=125060.00
        RETURNING id
    """), {"facility": DEER_FACILITY}).scalar_one_or_none()
    if deer is None:
        raise RuntimeError("Deer Meadow cheque 47662 preflight failed")

    bind.execute(sa.text("""
        INSERT INTO core.audit_log(schema_name,table_name,record_id,action,old_data,new_data)
        VALUES
          ('core','properties',CAST(:d57 AS uuid),'DELETE',json_build_object('duplicate',true),json_build_object('merged_into',CAST(:p57 AS text))),
          ('core','properties',CAST(:d8 AS uuid),'DELETE',json_build_object('duplicate',true),json_build_object('merged_into',CAST(:p8 AS text))),
          ('core','properties',CAST(:combined AS uuid),'DELETE',json_build_object('address','149/153 Ramona Gallos Way'),json_build_object('build_group_id',CAST(:group AS text),'members',json_build_array(CAST(:p149 AS text),CAST(:p153 AS text)))),
          ('core','facility_transactions',CAST(:deer AS uuid),'UPDATE',json_build_object('amount',125060.00,'reference','47662'),json_build_object('amount',125000.00,'basis','PRO row principal/interest and schedule total'))
    """), {"d57": D57, "p57": P57, "d8": D8, "p8": P8, "combined": RAMONA_COMBINED, "group": RAMONA_GROUP, "p149": P149, "p153": P153, "deer": deer})


def downgrade() -> None:
    raise RuntimeError("This audited production data repair is intentionally irreversible")
