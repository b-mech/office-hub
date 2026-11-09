"""Tenant context, dashboard, and rentals overview for the project-first workspace."""
from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import Annotated
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import TenantContext
from app.core.tenancy import get_tenant
from app.core.tenancy import lot_scope_sql
from app.core.tenancy import require_rentals
from app.core.tenancy import user_org_ids
from app.models.core import Org
from app.modules.lots.router import _list_lots
from app.modules.lots.router import timeline_events


router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])
Tenant = Annotated[TenantContext, Depends(get_tenant)]

TENDER_ACTION_STATUSES = ("draft", "sent", "bids_in", "compared")
OPEN_TICKET_EXCLUDED = ("resolved", "closed", "cancelled", "duplicate")


class OrgOut(BaseModel):
    id: str
    slug: str
    name: str
    member_project_scope: str
    land_enabled: bool


class ActorOut(BaseModel):
    id: str
    full_name: str
    email: str
    is_superadmin: bool
    is_fallback: bool


class WorkspaceContext(BaseModel):
    actor: ActorOut
    org: OrgOut
    membership_role: str | None
    available_orgs: list[OrgOut]
    capabilities: dict[str, bool]


def _org_out(org: Org) -> OrgOut:
    return OrgOut(id=str(org.id), slug=org.slug, name=org.name,
                  member_project_scope=str(getattr(org.member_project_scope, "value", org.member_project_scope)),
                  land_enabled=bool(org.land_enabled))


def capabilities(ctx: TenantContext) -> dict[str, bool]:
    legacy = ctx.is_legacy_org and (ctx.org_wide_projects or ctx.is_superadmin)
    return {
        "projects": True,
        "clients": True,
        "manage_clients": ctx.can_manage_clients,
        "land": ctx.can_access_land,
        "rentals": ctx.can_access_rentals,
        # Legacy CH modules (documents, financing, costbook, change orders,
        # contractors, lenders, settings) hold org-less CH data.
        "legacy_modules": legacy,
        "settings": legacy and (ctx.is_org_admin or ctx.user.role.value == "admin"),
        "org_switch": ctx.is_superadmin and not ctx.is_fallback,
    }


@router.get("/context", response_model=WorkspaceContext)
async def workspace_context(ctx: Tenant, db: AsyncSession = Depends(get_db)) -> WorkspaceContext:
    if ctx.is_fallback:
        orgs = [ctx.org]
    elif ctx.is_superadmin:
        orgs = list((await db.scalars(select(Org).order_by(Org.name))).all())
    else:
        ids = await user_org_ids(ctx.user, db)
        orgs = list((await db.scalars(select(Org).where(Org.id.in_(ids)).order_by(Org.name))).all()) if ids else []
    return WorkspaceContext(
        actor=ActorOut(id=str(ctx.user.id), full_name=ctx.user.full_name, email=ctx.user.email,
                       is_superadmin=ctx.is_superadmin, is_fallback=ctx.is_fallback),
        org=_org_out(ctx.org),
        membership_role=ctx.membership_role.value if ctx.membership_role else None,
        available_orgs=[_org_out(org) for org in orgs],
        capabilities=capabilities(ctx),
    )


async def tenders_needing_action(db: AsyncSession, ctx: TenantContext, limit: int = 10) -> dict[str, Any]:
    predicate, params = lot_scope_sql(ctx)
    params["statuses"] = list(TENDER_ACTION_STATUSES)
    base = f"""
        FROM core.tender_packages tp
        JOIN core.lots l ON l.property_id = tp.property_id
        JOIN core.developments d ON d.id = l.development_id
        JOIN core.contractor_categories cc ON cc.id = tp.category_id
        WHERE tp.status = ANY(:statuses) AND {predicate}
    """
    total = int((await db.execute(text(f"SELECT count(*) {base}"), params)).scalar_one())
    rows = (await db.execute(text(f"""
        SELECT tp.id::text AS id, tp.status, tp.due_date, tp.scope_description, cc.name AS category,
               l.id::text AS lot_id,
               COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
               (SELECT count(*) FROM core.tender_bids b WHERE b.tender_package_id = tp.id
                  AND b.status IN ('received', 'reviewed')) AS bids_received
        {base}
        ORDER BY tp.due_date ASC NULLS LAST, tp.created_at ASC
        LIMIT :limit
    """), {**params, "limit": limit})).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["due_date"] = item["due_date"].isoformat() if item["due_date"] else None
        item["bids_received"] = int(item["bids_received"])
        items.append(item)
    return {"total": total, "items": items}


async def rentals_overview_data(db: AsyncSession) -> dict[str, Any]:
    today = date.today()
    horizon = today + timedelta(days=90)

    async def scalar(sql: str, params: dict[str, Any] | None = None) -> int:
        return int((await db.execute(text(sql), params or {})).scalar_one() or 0)

    async def counts(sql: str, params: dict[str, Any] | None = None) -> dict[str, int]:
        return {str(k): int(v) for k, v in (await db.execute(text(sql), params or {})).all()}

    expiring = (await db.execute(text("""
        SELECT rl.id, rl.lease_end, rp.street_address, ru.unit_label, ru.id AS unit_id,
               (rl.lease_end - CURRENT_DATE)::int AS days_until
        FROM rental_leases rl
        JOIN rental_units ru ON ru.id = rl.unit_id
        JOIN rental_properties rp ON rp.id = ru.property_id
        WHERE rl.status = 'active' AND rl.lease_end IS NOT NULL
          AND rl.lease_end BETWEEN :today AND :horizon
        ORDER BY rl.lease_end, rp.street_address
        LIMIT 20
    """), {"today": today, "horizon": horizon})).mappings().all()
    open_tickets = (await db.execute(text("""
        SELECT mt.id::text AS id, mt.number, mt.title, mt.priority::text AS priority, mt.status::text AS status,
               mt.created_at, mt.sla_due_at, rp.street_address, ru.unit_label
        FROM maint_tickets mt
        LEFT JOIN rental_properties rp ON rp.id = mt.property_id
        LEFT JOIN rental_units ru ON ru.id = mt.unit_id
        WHERE mt.status::text <> ALL(:closed)
        ORDER BY CASE mt.priority::text WHEN 'emergency' THEN 0 WHEN 'urgent' THEN 1 WHEN 'routine' THEN 2 ELSE 3 END,
                 mt.sla_due_at ASC NULLS LAST, mt.created_at ASC
        LIMIT 10
    """), {"closed": list(OPEN_TICKET_EXCLUDED)})).mappings().all()
    return {
        "scope_note": "Rental tables are not org-owned yet; figures cover every rental record in Office Hub.",
        "properties": await scalar("SELECT count(*) FROM rental_properties"),
        "units": await scalar("SELECT count(*) FROM rental_units"),
        "rental_leases_by_status": await counts("SELECT COALESCE(status, 'unknown'), count(*) FROM rental_leases GROUP BY 1"),
        "lease_agreements_by_status": await counts("SELECT status, count(*) FROM lease_agreements GROUP BY 1"),
        "lease_agreements_awaiting_signature": await scalar(
            "SELECT count(*) FROM lease_agreements WHERE status IN ('sent', 'delivered')"),
        "lease_agreement_open_tasks": await scalar("SELECT count(*) FROM lease_agreement_tasks WHERE status = 'open'"),
        "leases_expiring_90_days_count": await scalar(
            "SELECT count(*) FROM rental_leases WHERE status = 'active' AND lease_end BETWEEN :today AND :horizon",
            {"today": today, "horizon": horizon}),
        "leases_expiring_90_days": [
            {**dict(row), "lease_end": row["lease_end"].isoformat()} for row in expiring
        ],
        "maintenance_open_by_priority": await counts(
            "SELECT priority::text, count(*) FROM maint_tickets WHERE status::text <> ALL(:closed) GROUP BY 1",
            {"closed": list(OPEN_TICKET_EXCLUDED)}),
        "maintenance_open_tickets": [
            {**dict(row),
             "created_at": row["created_at"].isoformat() if row["created_at"] else None,
             "sla_due_at": row["sla_due_at"].isoformat() if row["sla_due_at"] else None}
            for row in open_tickets
        ],
        # Not stored anywhere today; the UI shows "Not tracked" instead of 0.
        "occupancy": None,
        "rent_collected": None,
        "not_tracked": ["occupancy", "rent_collected"],
    }


@router.get("/rentals-overview")
async def rentals_overview(ctx: Tenant, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    require_rentals(ctx)
    return await rentals_overview_data(db)


@router.get("/dashboard")
async def dashboard(ctx: Tenant, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    projects = await _list_lots(db, "projects", ctx)
    by_status: dict[str, int] = {}
    for lot in projects:
        by_status[lot.status] = by_status.get(lot.status, 0) + 1
    today = date.today()
    horizon = today + timedelta(days=90)
    upcoming_possessions = sorted(
        (
            {"lot_id": lot.id, "address": lot.address, "community": lot.community,
             "client_name": lot.client_name or lot.buyer_name, "possession_date": lot.possession_date,
             "days_until": (date.fromisoformat(lot.possession_date) - today).days}
            for lot in projects
            if lot.possession_date and today <= date.fromisoformat(lot.possession_date) <= horizon
        ),
        key=lambda item: item["possession_date"],
    )
    active = [lot for lot in projects if lot.status in {"active", "hold"}]
    active.sort(key=lambda lot: (lot.possession_date or "9999-12-31", lot.address))
    result: dict[str, Any] = {
        "org": {"id": str(ctx.org_id), "name": ctx.org.name},
        "projects": {
            "total": len(projects),
            "by_status": by_status,
            "active": [
                {"id": lot.id, "address": lot.address, "community": lot.community, "status": lot.status,
                 "lifecycle_status": lot.lifecycle_status, "possession_date": lot.possession_date,
                 "client_name": lot.client_name, "construction_stage": lot.construction_stage}
                for lot in active[:8]
            ],
        },
        "tenders": await tenders_needing_action(db, ctx),
        "upcoming_possessions": upcoming_possessions[:10],
        "otp_milestones": None,
        "clients": None,
        "rentals": None,
    }
    if ctx.can_access_land:
        events = await timeline_events(db, ctx)
        soon = [event for event in events if event.days_until <= 30]
        result["otp_milestones"] = {
            "overdue": sum(1 for event in soon if event.urgency == "overdue"),
            "next_30_days": sum(1 for event in soon if event.days_until > 0),
            "items": [event.model_dump(mode="json") for event in soon[:10]],
        }
    predicate = "c.org_id = CAST(:org AS uuid)"
    params: dict[str, Any] = {"org": str(ctx.org_id)}
    if ctx.org_wide_projects:
        stage_counts = {str(k): int(v) for k, v in (await db.execute(text(
            f"SELECT lifecycle_stage, count(*) FROM core.clients c WHERE {predicate} GROUP BY 1"), params)).all()}
        recent = (await db.execute(text(f"""
            SELECT c.id::text AS id, c.display_name, c.lifecycle_stage, c.stage_changed_at
            FROM core.clients c WHERE {predicate}
            ORDER BY c.stage_changed_at DESC LIMIT 5
        """), params)).mappings().all()
        result["clients"] = {
            "by_stage": stage_counts,
            "recent_stage_changes": [
                {**dict(row), "stage_changed_at": row["stage_changed_at"].isoformat()} for row in recent
            ],
        }
    if ctx.can_access_rentals:
        overview = await rentals_overview_data(db)
        result["rentals"] = {
            "properties": overview["properties"],
            "units": overview["units"],
            "leases_expiring_90_days": overview["leases_expiring_90_days_count"],
            "maintenance_open": sum(overview["maintenance_open_by_priority"].values()),
            "lease_agreements_awaiting_signature": overview["lease_agreements_awaiting_signature"],
        }
    return result
