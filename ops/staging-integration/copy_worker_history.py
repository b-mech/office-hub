#!/usr/bin/env python3
"""Explicit, transactional rental/maintenance history carryover; never sends anything.

Default target guard requires a *_trial_* DB. Real staging requires BOTH
--allow-live-target and --target-db with its exact database name. Connections
come from protected dotenv files, never URL command-line arguments or output.
Existing canonical rows are not overwritten; natural keys remap integer IDs.
Pending outbound records are quarantined, not replayed. See README.md.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

RENTAL_KEYS = {
    "rental_companies": ("name",),
    "rental_properties": ("company_id", "street_address"),
    "rental_units": ("property_id", "unit_label"),
    "rental_tenants": ("full_name", "phone", "email"),
    "rental_leases": ("unit_id", "lease_start", "lease_end", "rent"),
    "rental_lease_tenants": ("lease_id", "tenant_id"),
    "rental_inspections": ("unit_id", "inspection_type", "inspection_date", "created_at"),
    "rental_inspection_photos": ("inspection_id", "box_file_id", "box_folder_path", "uploaded_at"),
}
UUID_HISTORY_TABLES = ("rental_inspection_reports", "rental_inspection_report_items", "rental_inspection_report_comments")
MAINT_TABLES = (
    "maint_vendors", "maint_tickets", "maint_work_orders", "maint_sms_messages",
    "maint_events", "maint_attachments", "maint_intake_tokens", "maint_unit_tokens",
    "maint_on_call", "maint_slack_outbox",
)
DEFERRED = {"maint_tickets": "duplicate_of", "maint_work_orders": "invoice_attachment_id"}


def natural_key(table: str, row: dict) -> tuple:
    return tuple(value.strip().casefold() if isinstance(value, str) else value
                 for value in (row.get(column) for column in RENTAL_KEYS[table]))


def guard_target(source_url: str, target_url: str, expected: str, allow_live: bool = False) -> None:
    source, target = make_url(source_url), make_url(target_url)
    if (source.host, source.port, source.database) == (target.host, target.port, target.database):
        raise ValueError("Source and target must be different databases")
    if target.database != expected:
        raise ValueError("Target database name does not match --target-db")
    if not allow_live and "_trial_" not in (target.database or ""):
        raise ValueError("Non-trial target requires explicit --allow-live-target")
    if not expected.startswith("officehub_"):
        raise ValueError("Unexpected database namespace")


def quarantine(table: str, row: dict, now: datetime) -> tuple[dict, bool]:
    row = dict(row)
    if table == "maint_sms_messages" and row.get("direction") == "outbound" and row.get("status") in {"pending", "held"}:
        row.update(status="cancelled", cancelled_at=now, error_code="staging_history_import_no_replay")
        return row, True
    if table == "maint_slack_outbox" and not row.get("delivered_at") and not row.get("failed_at"):
        row.update(failed_at=now, claimed_at=None, last_error="staging_history_import_no_replay")
        return row, True
    return row, False


def unique_index(table: str, rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        key = natural_key(table, row)
        if key in result:
            raise ValueError(f"Ambiguous natural key in {table}; manual mapping required")
        result[key] = row
    return result


def historical_actor(row: dict, org_id) -> dict:
    """Audit identity only: no authority, consent, login binding or contact route."""
    return dict(id=row["id"], org_id=org_id, email=row["email"], full_name=row["full_name"],
                role="readonly", is_active=False, permissions={})


async def copy_history(source_url: str, target_url: str, expected: str, allow_live: bool = False, import_disabled_actors: bool = False) -> dict:
    guard_target(source_url, target_url, expected, allow_live)
    source = create_async_engine(source_url, hide_parameters=True)
    target = create_async_engine(target_url, hide_parameters=True)
    report, maps, deferred = {}, {}, []
    now = datetime.now(timezone.utc)
    try:
        async with source.connect() as src, target.begin() as dst:
            await src.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            src_meta, dst_meta = MetaData(), MetaData()
            names = tuple(RENTAL_KEYS) + UUID_HISTORY_TABLES + MAINT_TABLES
            for conn, meta in ((src, src_meta), (dst, dst_meta)):
                await conn.run_sync(lambda sync, m=meta: m.reflect(sync, schema="public", only=names))
                await conn.run_sync(lambda sync, m=meta: Table("users", m, schema="core", autoload_with=sync, extend_existing=True))
            # Serialize imports and fail closed if another writer is active for too long.
            await dst.execute(text("SET LOCAL lock_timeout = '5s'"))
            await dst.execute(text("LOCK TABLE " + ", ".join("public." + n for n in names) + " IN SHARE ROW EXCLUSIVE MODE"))
            src_users = [dict(r) for r in (await src.execute(select(src_meta.tables["core.users"]))).mappings()]
            dst_users = [dict(r) for r in (await dst.execute(select(dst_meta.tables["core.users"]))).mappings()]
            user_by_id = {r["id"]: r for r in dst_users}
            user_by_email = {str(r.get("email", "")).strip().casefold(): r for r in dst_users}
            maps["core.users"] = {}
            actors_added = 0
            for row in src_users:
                match = user_by_id.get(row["id"]) or user_by_email.get(str(row.get("email", "")).strip().casefold())
                if match:
                    maps["core.users"][row["id"]] = match["id"]
                elif import_disabled_actors:
                    # Preserve historic audit identity, never copy login subjects,
                    # permissions, phones, Slack IDs or an active on-call contact.
                    org_table = dst_meta.tables["core.orgs"]
                    src_org = dict((await src.execute(select(src_meta.tables["core.orgs"]).where(src_meta.tables["core.orgs"].c.id == row["org_id"]))).mappings().one())
                    org = (await dst.execute(select(org_table).where(org_table.c.id == src_org["id"]))).mappings().first()
                    if org is None:
                        org = (await dst.execute(select(org_table).where(org_table.c.slug == src_org["slug"]))).mappings().first()
                    if org is None:
                        await dst.execute(org_table.insert().values(**{k: src_org[k] for k in ("id", "name", "slug", "created_at")}))
                        org = src_org
                    safe_actor = historical_actor(row, org["id"])
                    await dst.execute(dst_meta.tables["core.users"].insert().values(**safe_actor))
                    maps["core.users"][row["id"]] = row["id"]
                    actors_added += 1
            report["historical_actors"] = {"inserted_disabled": actors_added}
            for name in names:
                st, dt = src_meta.tables["public." + name], dst_meta.tables["public." + name]
                records = [dict(r) for r in (await src.execute(select(st).order_by(*st.primary_key.columns))).mappings()]
                existing = [dict(r) for r in (await dst.execute(select(dt))).mappings()]
                index = unique_index(name, existing) if name in RENTAL_KEYS else {r["id"]: r for r in existing}
                next_id = max((r.get("id", 0) for r in existing), default=0) + 1 if name in RENTAL_KEYS else None
                maps["public." + name] = {}
                stats = {"source": len(records), "inserted": 0, "matched": 0, "quarantined": 0}
                for original in records:
                    row = {k: v for k, v in original.items() if k in dt.c}
                    defer_col = DEFERRED.get(name)
                    defer_value = row.get(defer_col) if defer_col else None
                    if defer_col:
                        row[defer_col] = None
                    for column in dt.columns:
                        if row.get(column.name) is None:
                            continue
                        for fk in column.foreign_keys:
                            fk_name = fk.column.table.fullname
                            if column.name == defer_col:
                                continue
                            if fk_name in maps:
                                if row[column.name] not in maps[fk_name]:
                                    raise ValueError(f"Unmapped foreign key in {name}.{column.name}; explicit review needed")
                                row[column.name] = maps[fk_name][row[column.name]]
                    key = natural_key(name, row) if name in RENTAL_KEYS else row["id"]
                    if key in index:
                        match = index[key]
                        stats["matched"] += 1
                        if "id" in row:
                            maps["public." + name][original["id"]] = match["id"]
                        # STOP consent can only become more restrictive, never be cleared.
                        if name == "rental_tenants" and row.get("sms_opted_out") and not match.get("sms_opted_out"):
                            await dst.execute(dt.update().where(dt.c.id == match["id"]).values(sms_opted_out=True))
                        continue
                    if name in RENTAL_KEYS and "id" in row:
                        row["id"] = next_id
                        next_id += 1
                    row, quarantined = quarantine(name, row, now)
                    await dst.execute(dt.insert().values(**row))
                    index[key] = row
                    if "id" in row:
                        maps["public." + name][original["id"]] = row["id"]
                    if defer_value is not None:
                        deferred.append((dt, row["id"], defer_col, defer_value))
                    stats["inserted"] += 1
                    stats["quarantined"] += int(quarantined)
                report[name] = stats
                if name in RENTAL_KEYS and "id" in dt.c:
                    await dst.execute(text("SELECT setval(pg_get_serial_sequence(:name, 'id'), GREATEST(COALESCE((SELECT MAX(id) FROM public." + name + "), 0), 1), true)"), {"name": "public." + name})
            for table, identity, column, value in deferred:
                fk = next(iter(table.c[column].foreign_keys))
                mapped = maps.get(fk.column.table.fullname, {}).get(value, value)
                await dst.execute(table.update().where(table.c.id == identity).values({column: mapped}))
            await dst.execute(text("SELECT setval('maint_ticket_number_seq', GREATEST((SELECT last_value FROM maint_ticket_number_seq), COALESCE((SELECT MAX(substring(number from '[0-9]+$')::bigint) FROM maint_tickets), 1)), true)"))
        return report
    finally:
        await source.dispose()
        await target.dispose()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-env", type=Path, required=True)
    p.add_argument("--target-env", type=Path, required=True)
    p.add_argument("--target-db", required=True)
    p.add_argument("--allow-live-target", action="store_true")
    p.add_argument("--import-disabled-actors", action="store_true", help="Preserve unknown audit identities as inactive readonly users with no contact/login permissions")
    args = p.parse_args()
    try:
        source = dotenv_values(args.source_env)["DATABASE_URL"]
        target = dotenv_values(args.target_env)["DATABASE_URL"]
        report = asyncio.run(copy_history(source, target, args.target_db, args.allow_live_target, args.import_disabled_actors))
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        # Some driver/config exceptions include credentials, statements or tenant PII.
        print("Copy aborted; transaction rolled back. Error class: " + type(exc).__name__ + ". Inspect privately; never paste raw connection errors.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
