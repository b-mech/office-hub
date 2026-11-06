"""Tenant-owned clients and their links to project lots.

A client belongs to exactly one org (``core.clients.org_id``), always taken
from the resolved tenant, never from the request body. Projects are the same
``core.lots`` rows used everywhere else, linked through ``lots.client_id``;
nothing is copied. The DB trigger ``trg_core_lots_client_org`` repeats the
same-org rule so no other code path can link across tenants.
"""
from __future__ import annotations

import re
from datetime import datetime
from datetime import timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.core.tenancy import lot_scope_sql
from app.core.tenancy import require_lot_role
from app.models.core import AuditLog
from app.models.core import Client
from app.models.core import Contact
from app.models.core import Development
from app.models.core import Lot
from app.models.core import ProjectRole
from app.schemas.clients import ClientCreate
from app.schemas.clients import ClientDetail
from app.schemas.clients import ClientList
from app.schemas.clients import ClientOut
from app.schemas.clients import ClientProject
from app.schemas.clients import ClientUpdate
from app.schemas.clients import ContactSummary


PROJECT_PREDICATE = "l.trigger_type IS NOT NULL AND l.cancelled = false"


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def require_manage(ctx: TenantContext) -> None:
    if not ctx.can_manage_clients:
        raise HTTPException(status_code=403, detail="Client management is not available for your role")


def _visibility_sql(ctx: TenantContext) -> tuple[str, dict[str, object]]:
    """Org-wide actors see every org client; assigned members only clients of their projects."""
    params: dict[str, object] = {"tenant_org_id": str(ctx.org_id)}
    predicate = "c.org_id = CAST(:tenant_org_id AS uuid)"
    if not ctx.org_wide_projects:
        lot_predicate, lot_params = lot_scope_sql(ctx)
        params.update(lot_params)
        predicate += (
            " AND EXISTS (SELECT 1 FROM core.lots l JOIN core.developments d ON d.id = l.development_id"
            f" WHERE l.client_id = c.id AND {PROJECT_PREDICATE} AND {lot_predicate})"
        )
    return predicate, params


async def _contact_summary(db: AsyncSession, contact_id: UUID | None, org_id: UUID) -> ContactSummary | None:
    if contact_id is None:
        return None
    contact = await db.scalar(select(Contact).where(Contact.id == contact_id, Contact.org_id == org_id))
    if contact is None:
        return None
    return ContactSummary(id=contact.id, full_name=contact.full_name, company_name=contact.company_name,
                          email=contact.email, phone=contact.phone, contact_type=str(getattr(contact.contact_type, "value", contact.contact_type)))


async def list_clients(
    db: AsyncSession, ctx: TenantContext, *, q: str | None, stage: str | None, limit: int, offset: int
) -> ClientList:
    predicate, params = _visibility_sql(ctx)
    lot_predicate, lot_params = lot_scope_sql(ctx)
    params.update(lot_params)
    if q:
        predicate += " AND c.name_normalized LIKE :q"
        params["q"] = f"%{normalize_name(q)}%"
    if stage:
        predicate += " AND c.lifecycle_stage = :stage"
        params["stage"] = stage
    total = int((await db.execute(text(f"SELECT count(*) FROM core.clients c WHERE {predicate}"), params)).scalar_one())
    rows = (await db.execute(text(f"""
        SELECT c.id,
               (SELECT count(*) FROM core.lots l JOIN core.developments d ON d.id = l.development_id
                WHERE l.client_id = c.id AND {PROJECT_PREDICATE} AND {lot_predicate}) AS project_count
        FROM core.clients c
        WHERE {predicate}
        ORDER BY c.name_normalized, c.created_at, c.id
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": limit, "offset": offset})).all()
    items: list[ClientOut] = []
    for row in rows:
        client = await db.get(Client, row.id)
        if client is not None:
            items.append(await _client_out(db, client, int(row.project_count)))
    return ClientList(items=items, total=total, limit=limit, offset=offset)


async def _client_out(db: AsyncSession, client: Client, project_count: int) -> ClientOut:
    return ClientOut(
        id=client.id, org_id=client.org_id, display_name=client.display_name,
        client_type=client.client_type, lifecycle_stage=client.lifecycle_stage,  # type: ignore[arg-type]
        stage_changed_at=client.stage_changed_at,
        primary_contact=await _contact_summary(db, client.primary_contact_id, client.org_id),
        external_ref=client.external_ref, notes=client.notes, project_count=project_count,
        created_at=client.created_at, updated_at=client.updated_at,
    )


async def get_visible_client(db: AsyncSession, ctx: TenantContext, client_id: UUID) -> Client:
    predicate, params = _visibility_sql(ctx)
    found = (await db.execute(
        text(f"SELECT c.id FROM core.clients c WHERE c.id = CAST(:client_id AS uuid) AND {predicate}"),
        {**params, "client_id": str(client_id)},
    )).first()
    client = await db.get(Client, client_id) if found else None
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def client_projects(db: AsyncSession, ctx: TenantContext, client_id: UUID) -> list[ClientProject]:
    lot_predicate, params = lot_scope_sql(ctx)
    rows = (await db.execute(text(f"""
        SELECT l.id, COALESCE(l.civic_address, l.legal_description_normalized, 'Unknown Address') AS address,
               COALESCE(d.name, d.municipality, 'Unknown Community') AS community,
               l.status::text AS lifecycle_status, l.trigger_type, l.on_hold,
               (SELECT sa.possession_date::text FROM sales.agreements sa WHERE sa.lot_id = l.id
                ORDER BY sa.created_at DESC LIMIT 1) AS possession_date
        FROM core.lots l JOIN core.developments d ON d.id = l.development_id
        WHERE l.client_id = CAST(:client_id AS uuid) AND {PROJECT_PREDICATE} AND {lot_predicate}
        ORDER BY address
    """), {**params, "client_id": str(client_id)})).mappings().all()
    return [ClientProject(**dict(row)) for row in rows]


async def client_detail(db: AsyncSession, ctx: TenantContext, client: Client) -> ClientDetail:
    projects = await client_projects(db, ctx, client.id)
    duplicates = int((await db.execute(text(
        "SELECT count(*) FROM core.clients WHERE org_id = CAST(:org AS uuid) AND name_normalized = :name AND id <> CAST(:id AS uuid)"
    ), {"org": str(client.org_id), "name": client.name_normalized, "id": str(client.id)})).scalar_one())
    base = await _client_out(db, client, len(projects))
    return ClientDetail(**base.model_dump(), projects=projects, duplicate_name_count=duplicates)


async def _validate_contact(db: AsyncSession, ctx: TenantContext, contact_id: UUID | None) -> None:
    if contact_id is None:
        return
    org_id = await db.scalar(select(Contact.org_id).where(Contact.id == contact_id))
    if org_id is None or org_id != ctx.org_id:
        raise HTTPException(status_code=422, detail="Primary contact not found in this organization")


def _snapshot(client: Client) -> dict[str, object]:
    return {
        "display_name": client.display_name, "client_type": client.client_type,
        "lifecycle_stage": client.lifecycle_stage,
        "primary_contact_id": str(client.primary_contact_id) if client.primary_contact_id else None,
        "external_ref": client.external_ref, "notes": client.notes,
    }


async def _commit(db: AsyncSession, conflict: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409 if "external_ref" in str(exc.orig) else 422, detail=conflict) from exc


async def create_client(db: AsyncSession, ctx: TenantContext, data: ClientCreate) -> Client:
    require_manage(ctx)
    await _validate_contact(db, ctx, data.primary_contact_id)
    name = data.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Client name is required")
    client = Client(
        org_id=ctx.org_id, display_name=name, name_normalized=normalize_name(name),
        client_type=data.client_type, lifecycle_stage=data.lifecycle_stage,
        primary_contact_id=data.primary_contact_id,
        external_ref=(data.external_ref or "").strip() or None,
        notes=(data.notes or "").strip() or None, created_by=ctx.user.id,
    )
    db.add(client)
    await db.flush()
    db.add(AuditLog(user_id=ctx.user.id, schema_name="core", table_name="clients", record_id=client.id,
                    action="INSERT", old_data=None, new_data=_snapshot(client)))
    await _commit(db, "A client with this external reference already exists")
    await db.refresh(client)
    return client


async def update_client(db: AsyncSession, ctx: TenantContext, client: Client, data: ClientUpdate) -> Client:
    require_manage(ctx)
    fields = data.model_fields_set
    before = _snapshot(client)
    if "display_name" in fields and data.display_name is not None:
        name = data.display_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Client name is required")
        client.display_name, client.name_normalized = name, normalize_name(name)
    if "client_type" in fields and data.client_type is not None:
        client.client_type = data.client_type
    if "lifecycle_stage" in fields and data.lifecycle_stage is not None and data.lifecycle_stage != client.lifecycle_stage:
        client.lifecycle_stage = data.lifecycle_stage
        client.stage_changed_at = datetime.now(timezone.utc)
    if "primary_contact_id" in fields:
        await _validate_contact(db, ctx, data.primary_contact_id)
        client.primary_contact_id = data.primary_contact_id
    if "external_ref" in fields:
        client.external_ref = (data.external_ref or "").strip() or None
    if "notes" in fields:
        client.notes = (data.notes or "").strip() or None
    after = _snapshot(client)
    if after != before:
        client.updated_at = datetime.now(timezone.utc)
        db.add(AuditLog(user_id=ctx.user.id, schema_name="core", table_name="clients", record_id=client.id,
                        action="UPDATE", old_data=before, new_data=after))
    await _commit(db, "A client with this external reference already exists")
    await db.refresh(client)
    return client


async def set_project_client(db: AsyncSession, ctx: TenantContext, lot_id: UUID, client_id: UUID | None) -> Lot:
    await require_lot_role(ctx, lot_id, ProjectRole.EDITOR, db)
    require_manage(ctx)
    lot = await db.scalar(select(Lot).where(Lot.id == lot_id).with_for_update())
    if lot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if lot.trigger_type is None or lot.cancelled:
        raise HTTPException(status_code=422, detail="Clients can only be linked to active project lots")
    if client_id is not None:
        client_org = await db.scalar(select(Client.org_id).where(Client.id == client_id))
        lot_org = await db.scalar(select(Development.org_id).where(Development.id == lot.development_id))
        if client_org is None or client_org != ctx.org_id or client_org != lot_org:
            raise HTTPException(status_code=422, detail="Client not found in this organization")
    before = str(lot.client_id) if lot.client_id else None
    lot.client_id = client_id
    db.add(AuditLog(user_id=ctx.user.id, schema_name="core", table_name="lots", record_id=lot.id,
                    action="UPDATE", old_data={"client_id": before},
                    new_data={"client_id": str(client_id) if client_id else None}))
    try:
        await db.commit()
    except (IntegrityError, DBAPIError) as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail="Client not found in this organization") from exc
    await db.refresh(lot)
    return lot


async def contact_options(db: AsyncSession, ctx: TenantContext, q: str | None, limit: int = 25) -> list[ContactSummary]:
    require_manage(ctx)
    query = select(Contact).where(Contact.org_id == ctx.org_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(Contact.full_name.ilike(like) | Contact.company_name.ilike(like) | Contact.email.ilike(like))
    contacts = (await db.scalars(query.order_by(Contact.full_name).limit(limit))).all()
    return [ContactSummary(id=c.id, full_name=c.full_name, company_name=c.company_name, email=c.email,
                           phone=c.phone, contact_type=str(getattr(c.contact_type, "value", c.contact_type)))
            for c in contacts]
