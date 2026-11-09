"""Rental lease agreement API."""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.core import User, UserRole
from app.models.rentals import LeaseAgreement, LeaseAgreementTask, RentalLease, RentalLeaseTenant, RentalProperty, RentalTenant, RentalUnit
from app.services import lease_workflow
from app.services.lease_rendering import draft_pdf

router = APIRouter(prefix="/api/rentals/leases", tags=["rentals"])


async def viewer(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user: User | None = getattr(request.state, "user", None)
    if user is None and not settings.auth_enforced:
        user = await db.scalar(select(User).where(User.is_active.is_(True), User.role == UserRole.ADMIN)
                               .order_by(User.created_at, User.id).limit(1))
        if user is None:
            raise HTTPException(503, "No active Office Hub admin is available for lease actions")
    if user is None:
        user = current_user(request)
    if user.role != UserRole.ADMIN and (user.permissions or {}).get("rentals") not in {"viewer", "editor"}:
        raise HTTPException(403, "Rentals access is required")
    return user


async def editor(user: User = Depends(viewer)) -> User:
    if user.role != UserRole.ADMIN and (user.permissions or {}).get("rentals") != "editor":
        raise HTTPException(403, "Rentals editor permission is required")
    return user


def output(lease: LeaseAgreement) -> dict:
    result = {key: getattr(lease, key) for key in (
        "id", "unit_id", "tenancy_id", "template_version", "status", "draft_revision", "context", "tenants",
        "draft_docx_key", "draft_pdf_key", "docusign_envelope_id", "sent_at", "completed_at",
        "voided_at", "signed_pdf_box_file_id", "contact_form_data", "recipient_status",
        "created_by", "created_at", "updated_at")}
    recipients = lease.recipient_status or {}
    if lease.status in {"sent", "delivered"}:
        result["display_status"] = "With tenants" if recipients.get("1") == "completed" else "Awaiting landlord"
    else:
        result["display_status"] = lease.status.title()
    result["signed_pdf_box_url"] = f"https://app.box.com/file/{lease.signed_pdf_box_file_id}" if lease.signed_pdf_box_file_id else None
    return jsonable_encoder(result)


async def get_lease(db: AsyncSession, lease_id: UUID) -> LeaseAgreement:
    lease = await db.get(LeaseAgreement, lease_id)
    if not lease:
        raise HTTPException(404, "Lease agreement not found")
    return lease


class CreateIn(BaseModel):
    unit_id: int
    copy_id: UUID | None = None


class DraftIn(BaseModel):
    context: dict


class VoidIn(BaseModel):
    reason: str = Field(min_length=1)


class PropertyIn(BaseModel):
    municipality: str = Field(min_length=1)
    is_multiplex: bool
    is_condo: bool
    lease_utility_override: dict[str, str | None] | None = None


class ApplyContactsIn(BaseModel):
    updates: list[dict]


@router.get("/units/{unit_id}")
async def list_unit(unit_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(viewer)) -> dict:
    try:
        unit, property = await lease_workflow.unit_property(db, unit_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    leases = (await db.scalars(select(LeaseAgreement).where(LeaseAgreement.unit_id == unit_id)
                               .order_by(LeaseAgreement.created_at.desc()))).all()
    has_imported_lease = await db.scalar(select(RentalLease.id).where(RentalLease.unit_id == unit_id).limit(1)) is not None
    return {"unit": {"id": unit.id, "unit_label": unit.unit_label},
            "property": {"id": property.id, "street_address": property.street_address,
                         "municipality": property.municipality or property.city,
                         "is_multiplex": property.is_multiplex, "is_condo": property.is_condo,
                         "lease_utility_override": property.lease_utility_override},
            "has_imported_lease": has_imported_lease,
            "leases": [output(lease) for lease in leases]}


@router.patch("/properties/{property_id}")
async def update_property(property_id: int, data: PropertyIn, db: AsyncSession = Depends(get_db),
                          user: User = Depends(editor)) -> dict:
    property = await db.get(RentalProperty, property_id)
    if property is None:
        raise HTTPException(404, "Property not found")
    property.municipality = data.municipality.strip()
    property.is_multiplex, property.is_condo = data.is_multiplex, data.is_condo
    property.lease_utility_override = data.lease_utility_override
    await db.commit()
    return {"id": property.id}


@router.post("")
async def create(data: CreateIn, db: AsyncSession = Depends(get_db), user: User = Depends(editor)) -> dict:
    try:
        return output(await lease_workflow.create(db, data.unit_id, user.id, data.copy_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{lease_id}")
async def detail(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(viewer)) -> dict:
    return output(await get_lease(db, lease_id))


@router.get("/{lease_id}/tenant-records")
async def tenant_records(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(viewer)) -> list[dict]:
    lease = await get_lease(db, lease_id)
    if not lease.tenancy_id:
        return []
    tenants = (await db.scalars(select(RentalTenant).join(RentalLeaseTenant,
        RentalLeaseTenant.tenant_id == RentalTenant.id).where(RentalLeaseTenant.lease_id == lease.tenancy_id))).all()
    return [{"id": tenant.id, "name": tenant.full_name, "phone": tenant.phone, "email": tenant.email}
            for tenant in tenants]


@router.get("/{lease_id}/task")
async def task(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(viewer)) -> dict | None:
    await get_lease(db, lease_id)
    item = await db.scalar(select(LeaseAgreementTask).where(LeaseAgreementTask.lease_agreement_id == lease_id))
    return jsonable_encoder({"id": item.id, "title": item.title, "status": item.status,
                             "created_at": item.created_at}) if item else None


@router.post("/{lease_id}/task/complete")
async def complete_task(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(editor)) -> dict:
    await get_lease(db, lease_id)
    item = await db.scalar(select(LeaseAgreementTask).where(LeaseAgreementTask.lease_agreement_id == lease_id))
    if item is None:
        raise HTTPException(404, "Plooto setup task not found")
    item.status = "completed"
    await db.commit()
    return {"status": "completed"}


@router.patch("/{lease_id}")
async def save(lease_id: UUID, data: DraftIn, db: AsyncSession = Depends(get_db),
               user: User = Depends(editor)) -> dict:
    try:
        return output(await lease_workflow.save_draft(db, await get_lease(db, lease_id), data.context, user.id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{lease_id}/preview")
async def preview(lease_id: UUID, db: AsyncSession = Depends(get_db),
                  user: User = Depends(editor)) -> Response:
    try:
        pdf = await lease_workflow.preview(db, await get_lease(db, lease_id), user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "inline; filename=lease-preview.pdf"})


@router.get("/{lease_id}/pdf")
async def pdf(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(viewer)) -> Response:
    lease = await get_lease(db, lease_id)
    if not lease.draft_pdf_key:
        raise HTTPException(404, "Preview this lease first")
    return Response(await asyncio.to_thread(draft_pdf, lease.draft_pdf_key), media_type="application/pdf")


@router.post("/{lease_id}/send")
async def send(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(editor)) -> dict:
    try:
        return output(await lease_workflow.send(db, await get_lease(db, lease_id), user.id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/{lease_id}/void")
async def void(lease_id: UUID, data: VoidIn, db: AsyncSession = Depends(get_db),
               user: User = Depends(editor)) -> dict:
    try:
        return output(await lease_workflow.void(db, await get_lease(db, lease_id), data.reason, user.id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{lease_id}/resend")
async def resend(lease_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(editor)) -> dict:
    try:
        await lease_workflow.resend(await get_lease(db, lease_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "resent"}


@router.post("/{lease_id}/apply-contacts")
async def apply_contacts(lease_id: UUID, data: ApplyContactsIn, db: AsyncSession = Depends(get_db),
                         user: User = Depends(editor)) -> dict:
    try:
        await lease_workflow.apply_contacts(db, await get_lease(db, lease_id), user.id, data.updates)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "applied"}
