"""Link paired PRO commitments to duplex groups and Grande Pointe lots.

Default is rollback-only. Every target is checked against the surveyed IDs so
that this script cannot silently attach a facility to a different lot.
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.financing import _refresh_statement_status, _sync_statement_discrepancies  # noqa: E402


ORG = UUID("ed83acdb-7a3a-4999-b5b0-4d41ee24a99d")
PAIRS = [
    ("141/145 Laurent Drive", "50f950d8-4942-4bd4-ac1b-300f1eae1219",
     "e03b7c68-467a-4eca-beea-04447537bcc7", "ef2aa024-06d6-45d9-a6bf-826ccb514231",
     ("333b0767-e404-4186-bd76-291c4e3c062a", "8da31723-1613-499f-aee2-89741cf9cdc2")),
    ("149/153 Laurent Drive", "50f950d8-4942-4bd4-ac1b-300f1eae1219",
     "c546b087-d1d3-4869-8928-9ec3e32163e4", "ea8f7099-6c9d-4569-a77c-90e0e049e69f",
     ("31bbe46a-d47b-4299-bacd-2273c2f3f71e", "2bfd883e-ae2c-452b-9c59-888ba411f286")),
    ("37/39 Ella Drive", "8a17c627-08f7-43f6-abf0-356d6e602d68",
     "2ddb6114-0a77-4087-b890-7f1cc0a78cca", "9f051abc-02c2-45dc-b313-bf0828d42b73",
     ("ddbcd66c-f7fa-4569-9d3d-264d54bffa15", "d1b78748-d229-435e-87f4-461b254a808c")),
    ("45/47 Ella Drive", "8a17c627-08f7-43f6-abf0-356d6e602d68",
     "d10392b4-e2d8-4806-a2a7-0f32f884fea5", "73c436b3-603a-4ac8-8901-99f04329793b",
     ("b4d969ef-dddd-464b-aab6-8f374b05793f", "52afbe5b-4f60-4920-bb0b-bb11b8b6c7c9")),
]
GRANDE_POINTE = [
    ("57-100 Grande Pointe Meadows Blvd", "0fb9646e-b3e6-4f20-a6ff-c40d3b99b41a",
     "fc1ccc7a-6722-4364-8ad5-c0ed6842d765", "210f2b98-8195-4d0f-8f26-9c698f11e324"),
    ("8-100 Grande Pointe Meadows Blvd", "f35d9b32-4761-48a9-9af5-50bf8e2d59af",
     "b6a52664-89be-47b2-8d60-b86b3c2aadb9", "4373bb2d-6efd-4611-87f3-7d831fe9c467"),
]


async def run(apply):
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock(20261020, 13)"))
        result = {"mode": "applied" if apply else "dry_run_rolled_back", "groups": [], "grande_pointe": []}
        for name, development, facility_id, property_id, lot_ids in PAIRS:
            facility = (await db.execute(text("""
                SELECT property_id, build_group_id, facility_scope, lender, lender_type
                FROM core.lender_facilities WHERE id=:id FOR UPDATE
            """), {"id": UUID(facility_id)})).mappings().one()
            if facility["property_id"] != UUID(property_id) or (facility["lender"] or facility["lender_type"]) != "PRO":
                raise RuntimeError(f"Facility identity changed: {name}")
            lots = (await db.execute(text("""
                SELECT id, property_id, build_group_id, development_id, civic_address
                FROM core.lots WHERE id IN (:a, :b) ORDER BY civic_address FOR UPDATE
            """), {"a": UUID(lot_ids[0]), "b": UUID(lot_ids[1])})).mappings().all()
            if len(lots) != 2 or any(lot["development_id"] != UUID(development) or lot["property_id"] for lot in lots):
                raise RuntimeError(f"Duplex lot identities changed: {name}")
            group = (await db.execute(text("""
                SELECT id FROM core.build_groups
                WHERE development_id=:development AND display_name=:name FOR UPDATE
            """), {"development": UUID(development), "name": name})).scalar_one_or_none()
            if group is None:
                group = (await db.execute(text("""
                    INSERT INTO core.build_groups (org_id, development_id, group_type, display_name, status)
                    VALUES (:org, :development, 'duplex', :name, 'active') RETURNING id
                """), {"org": ORG, "development": UUID(development), "name": name})).scalar_one()
            if facility["build_group_id"] not in (None, group) or any(lot["build_group_id"] not in (None, group) for lot in lots):
                raise RuntimeError(f"Existing group link conflicts: {name}")
            await db.execute(text("""
                UPDATE core.lots SET build_group_id=:group_id, updated_at=now()
                WHERE id IN (:a, :b)
            """), {"group_id": group, "a": UUID(lot_ids[0]), "b": UUID(lot_ids[1])})
            await db.execute(text("""
                UPDATE core.lender_facilities SET build_group_id=:group_id,
                    facility_scope='build_group', updated_at=now() WHERE id=:facility_id
            """), {"group_id": group, "facility_id": UUID(facility_id)})
            stages = (await db.execute(text("""
                UPDATE documents.construction_stage_sync
                SET property_id=NULL, build_group_id=:group_id
                WHERE property_id=:property_id RETURNING address_raw
            """), {"group_id": group, "property_id": UUID(property_id)})).scalars().all()
            moved_history = (await db.execute(text("""
                UPDATE documents.construction_stage_history
                SET property_id=NULL, build_group_id=:group_id
                WHERE property_id=:property_id RETURNING id
            """), {"group_id": group, "property_id": UUID(property_id)})).scalars().all()
            moved_milestones = (await db.execute(text("""
                UPDATE documents.construction_stage_milestones
                SET property_id=NULL, build_group_id=:group_id
                WHERE property_id=:property_id RETURNING id
            """), {"group_id": group, "property_id": UUID(property_id)})).scalars().all()
            result["groups"].append({"name": name, "group_id": str(group),
                                     "lot_addresses": [lot["civic_address"] for lot in lots],
                                     "stage_rows_moved": stages,
                                     "history_rows_moved": len(moved_history),
                                     "milestones_moved": len(moved_milestones)})
        for name, facility_id, property_id, lot_id in GRANDE_POINTE:
            facility = (await db.execute(text("""
                SELECT property_id, lot_id, lender, lender_type
                FROM core.lender_facilities WHERE id=:id FOR UPDATE
            """), {"id": UUID(facility_id)})).mappings().one()
            lot = (await db.execute(text("""
                SELECT property_id, civic_address, development_id
                FROM core.lots WHERE id=:id FOR UPDATE
            """), {"id": UUID(lot_id)})).mappings().one()
            if facility["property_id"] != UUID(property_id) or facility["lot_id"] not in (None, UUID(lot_id)):
                raise RuntimeError(f"Facility identity changed: {name}")
            if lot["property_id"] not in (None, UUID(property_id)) or lot["civic_address"] != name or lot["development_id"] != UUID("066da849-b341-433c-ab93-fee1642860fa"):
                raise RuntimeError(f"Lot identity changed: {name}")
            await db.execute(text("UPDATE core.lots SET property_id=:property_id, updated_at=now() WHERE id=:lot_id"),
                             {"property_id": UUID(property_id), "lot_id": UUID(lot_id)})
            await db.execute(text("UPDATE core.lender_facilities SET lot_id=:lot_id, updated_at=now() WHERE id=:facility_id"),
                             {"lot_id": UUID(lot_id), "facility_id": UUID(facility_id)})
            result["grande_pointe"].append({"name": name, "facility_id": facility_id,
                                             "property_id": property_id, "lot_id": lot_id})
        statements = (await db.execute(text("""
            SELECT id, period FROM documents.lender_statements
            WHERE lender='PRO' AND period BETWEEN '2026-06' AND '2026-09'
            ORDER BY period
        """))).mappings().all()
        if len(statements) != 4:
            raise RuntimeError("Expected four PRO statements")
        for statement in statements:
            await _sync_statement_discrepancies(db, statement["id"])
            await _refresh_statement_status(db, statement["id"])
        counts = (await db.execute(text("""
            SELECT l.period, l.status, COUNT(d.id) FILTER (WHERE d.status='open') AS open_missing
            FROM documents.lender_statements l
            LEFT JOIN documents.lender_statement_discrepancies d ON d.statement_id=l.id
            WHERE l.id IN (:june, :july, :august, :september)
            GROUP BY l.id ORDER BY l.period
        """), {"june": statements[0]["id"], "july": statements[1]["id"],
               "august": statements[2]["id"], "september": statements[3]["id"]})).mappings().all()
        result["statement_counts"] = [dict(row) for row in counts]
        print(json.dumps(result, indent=2))
        if apply:
            await db.commit()
        else:
            await db.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args().apply))
