"""Lease agreement state transitions and external filing."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.rentals import (LeaseAgreement, LeaseAgreementEvent, LeaseAgreementTask,
                                RentalLease, RentalLeaseTenant, RentalProperty, RentalTenant, RentalUnit)
from app.services import lease_agreements as fields, lease_docusign, lease_rendering
from app.services.box import get_or_create_subfolder, upload_file
from app.services.docusign import get_signed_pdf


def event(db: AsyncSession, lease: LeaseAgreement, action: str, user_id: UUID | None = None,
          detail: dict | None = None) -> None:
    db.add(LeaseAgreementEvent(lease_agreement_id=lease.id, action=action, user_id=user_id, detail=detail))


async def unit_property(db: AsyncSession, unit_id: int) -> tuple[RentalUnit, RentalProperty]:
    unit = await db.get(RentalUnit, unit_id)
    property = await db.get(RentalProperty, unit.property_id) if unit else None
    if unit is None or property is None:
        raise ValueError("Rental unit not found")
    return unit, property


def default_term(today: date, after: date | None = None) -> tuple[date, date]:
    """A one-year fixed term. Starts the day after ``after`` when that is in the future,
    otherwise on the first day of next month."""
    if after is not None and after >= today:
        start = after + timedelta(days=1)
    else:
        start = date(today.year + today.month // 12, today.month % 12 + 1, 1)
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:  # Feb 29
        anniversary = start.replace(year=start.year + 1, day=28) + timedelta(days=1)
    return start, anniversary - timedelta(days=1)


START_FROM = ("blank", "tenancy")


async def initial_context(db: AsyncSession, unit_id: int, from_lease: LeaseAgreement | None = None,
                          start_from: str | None = None, today: date | None = None) -> tuple[dict, int | None]:
    """Starting context for a new lease agreement.

    ``start_from=None`` keeps the original behaviour (prefill from the newest rent-roll lease).
    ``"blank"`` starts with no tenants or rent and a default one-year term.
    ``"tenancy"`` prefills tenants and rent from the lease currently in force (chosen by dates)
    but never reuses a term that has already ended.
    """
    unit, property = await unit_property(db, unit_id)
    if from_lease:
        return dict(from_lease.context), from_lease.tenancy_id
    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    if start_from in START_FROM:
        from app.services.rental_units import pick_leases
        leases = list((await db.scalars(select(RentalLease).where(RentalLease.unit_id == unit.id))).all())
        current, latest = pick_leases(leases, today)
        tenancy = None if start_from == "blank" else (current.get(unit.id) or latest.get(unit.id))
    else:
        tenancy = await db.scalar(select(RentalLease).where(RentalLease.unit_id == unit.id)
                                  .order_by(RentalLease.lease_start.desc().nullslast(), RentalLease.id.desc()))
    tenants = []
    if tenancy:
        rows = (await db.execute(select(RentalTenant).join(RentalLeaseTenant, RentalLeaseTenant.tenant_id == RentalTenant.id)
                                 .where(RentalLeaseTenant.lease_id == tenancy.id)
                                 .order_by(RentalLeaseTenant.is_primary_contact.desc(), RentalTenant.id))).scalars()
        tenants = [{"name": row.full_name, "email": row.email or "", "phone": row.phone or ""} for row in rows]
    defaults = fields.utility_defaults(property.municipality or property.city, property.is_multiplex)
    defaults.update(property.lease_utility_override or {})
    context: dict[str, Any] = {key: None for key in fields.OPTIONAL}
    context.update(defaults)
    context.update({"tenant_names": " & ".join(t["name"] for t in tenants), "tenants": tenants,
                    "unit_address": f"{property.street_address}, {property.municipality or property.city or ''}, MB",
                    "is_condo": property.is_condo, "furniture_provided": False,
                    "rent_due_day": "first", "rent_period": "month",
                    "basic_rent": fields.money(tenancy.rent) if tenancy else None,
                    "rent_discount": fields.money(tenancy.rent_discount_amount, optional=True) if tenancy else None,
                    "rent_payable": fields.money(tenancy.rent) if tenancy else None,
                    "actual_rent": fields.money(tenancy.rent - (tenancy.rent_discount_amount or 0)) if tenancy else None,
                    "security_deposit_amount": fields.money(tenancy.deposit, optional=True) if tenancy else None,
                    "fixed_start": fields.long_date(tenancy.lease_start) if tenancy else None,
                    "fixed_end": fields.long_date(tenancy.lease_end) if tenancy else None})
    if start_from in START_FROM:
        in_term_end = tenancy.lease_end if tenancy and tenancy.lease_end and tenancy.lease_end >= today else None
        start, end = default_term(today, in_term_end)
        context.update({"fixed_start": fields.long_date(start), "fixed_end": fields.long_date(end)})
    return context, tenancy.id if tenancy else None


async def create(db: AsyncSession, unit_id: int, user_id: UUID | None, copy_id: UUID | None = None,
                 start_from: str | None = None) -> LeaseAgreement:
    source = await db.get(LeaseAgreement, copy_id) if copy_id else None
    if copy_id and (source is None or source.unit_id != unit_id):
        raise ValueError("Previous lease not found for this unit")
    if start_from is not None and start_from not in START_FROM:
        raise ValueError("start_from must be 'blank' or 'tenancy'")
    context, tenancy_id = await initial_context(db, unit_id, source, start_from)
    lease = LeaseAgreement(unit_id=unit_id, tenancy_id=tenancy_id, context=context,
                           tenants=context["tenants"], created_by=user_id)
    db.add(lease)
    await db.flush()
    event(db, lease, "create", user_id, {"copied_from": str(copy_id) if copy_id else None})
    await db.commit()
    await db.refresh(lease)
    return lease


async def save_draft(db: AsyncSession, lease: LeaseAgreement, raw: dict[str, Any], user_id: UUID | None) -> LeaseAgreement:
    await db.refresh(lease, with_for_update=True)
    if lease.status != "draft":
        raise ValueError("Sent leases are frozen; void and create a new lease")
    _, property = await unit_property(db, lease.unit_id)
    context = dict(lease.context)
    context.update(raw)
    context["unit_address"] = f"{property.street_address}, {property.municipality or property.city or ''}, MB"
    context["is_condo"] = property.is_condo
    context["tenants"] = raw.get("tenants", context.get("tenants", [])) or []
    context["tenant_names"] = " & ".join(str(t.get("name", "")).strip() for t in context["tenants"])
    context["rent_payable"] = context["actual_rent"] = None
    lease.context, lease.tenants = context, context["tenants"]
    lease.draft_revision += 1
    lease.draft_docx_key = lease.draft_pdf_key = None
    event(db, lease, "save_draft", user_id)
    await db.commit()
    await db.refresh(lease)
    return lease


async def preview(db: AsyncSession, lease: LeaseAgreement, user_id: UUID | None) -> bytes:
    if lease.status != "draft":
        if not lease.draft_pdf_key:
            raise ValueError("No lease preview is available")
        return await asyncio.to_thread(lease_rendering.draft_pdf, lease.draft_pdf_key)
    _, property = await unit_property(db, lease.unit_id)
    if not property.municipality:
        raise ValueError("Confirm the property's municipality before previewing")
    revision = lease.draft_revision
    context = fields.build_context(lease.context, property)
    from app.workers.lease_agreements import render_lease
    job = render_lease.delay(str(lease.id), context)
    docx_key, pdf_key = await asyncio.to_thread(job.get, timeout=120)
    await db.refresh(lease, with_for_update=True)
    if lease.status != "draft" or lease.draft_revision != revision:
        raise ValueError("Draft changed during rendering; preview the latest version")
    lease.context = context
    lease.tenants = [{**tenant, "phone": next((t.get("phone") for t in lease.tenants if t.get("email") == tenant["email"]), None)}
                     for tenant in context["tenants"]]
    lease.draft_docx_key, lease.draft_pdf_key = docx_key, pdf_key
    event(db, lease, "preview", user_id)
    await db.commit()
    return await asyncio.to_thread(lease_rendering.draft_pdf, pdf_key)


async def send(db: AsyncSession, lease: LeaseAgreement, user_id: UUID | None) -> LeaseAgreement:
    await db.refresh(lease, with_for_update=True)
    if lease.status != "draft":
        raise ValueError("Only drafts can be sent")
    if not lease.draft_pdf_key:
        raise ValueError("Preview the lease before sending")
    _, property = await unit_property(db, lease.unit_id)
    if not property.municipality:
        raise ValueError("Confirm the property's municipality before sending")
    if fields.build_context(lease.context, property) != lease.context:
        raise ValueError("Property or lease details changed; preview again before sending")
    pdf = await asyncio.to_thread(lease_rendering.draft_pdf, lease.draft_pdf_key)
    lease_rendering.check_pdf(pdf, len(lease.tenants))
    envelope_id = await asyncio.to_thread(lease_docusign.send, pdf, lease.context)
    lease.docusign_envelope_id = envelope_id
    lease.status = "sent"
    lease.sent_at = datetime.now(timezone.utc)
    event(db, lease, "send", user_id, {"envelope_id": envelope_id})
    await db.commit()
    return lease


async def void(db: AsyncSession, lease: LeaseAgreement, reason: str, user_id: UUID | None) -> LeaseAgreement:
    if lease.status not in {"sent", "delivered"} or not lease.docusign_envelope_id:
        raise ValueError("Only an open sent lease can be voided")
    if not reason.strip():
        raise ValueError("A void reason is required")
    await asyncio.to_thread(lease_docusign.void, lease.docusign_envelope_id, reason.strip())
    lease.status, lease.voided_at = "voided", datetime.now(timezone.utc)
    event(db, lease, "void", user_id, {"reason": reason.strip()})
    await db.commit()
    return lease


async def resend(lease: LeaseAgreement) -> None:
    if lease.status not in {"sent", "delivered"} or not lease.docusign_envelope_id:
        raise ValueError("Only an open sent lease can be resent")
    await asyncio.to_thread(lease_docusign.resend, lease.docusign_envelope_id)


async def poll(db: AsyncSession, lease: LeaseAgreement) -> None:
    if lease.status not in {"sent", "delivered"} or not lease.docusign_envelope_id:
        return
    envelope_status, recipients = await asyncio.to_thread(lease_docusign.status, lease.docusign_envelope_id)
    lease.recipient_status = recipients
    mapped = {"sent": "sent", "delivered": "delivered", "completed": "completed",
              "declined": "declined", "voided": "voided"}.get(envelope_status)
    if mapped and mapped != lease.status:
        lease.status = mapped
        if mapped == "completed":
            lease.completed_at = datetime.now(timezone.utc)
            event(db, lease, "completed")
        elif mapped == "voided":
            lease.voided_at = datetime.now(timezone.utc)
        await db.commit()
    else:
        await db.commit()
    if lease.status == "completed":
        await file_completed(db, lease)


async def file_completed(db: AsyncSession, lease: LeaseAgreement) -> None:
    if lease.signed_pdf_box_file_id or not lease.docusign_envelope_id:
        return
    pdf = await asyncio.to_thread(get_signed_pdf, lease.docusign_envelope_id)
    if not pdf:
        raise RuntimeError("DocuSign combined signed PDF is unavailable")
    cert = await asyncio.to_thread(lease_docusign.certificate, lease.docusign_envelope_id)
    values = await asyncio.to_thread(lease_docusign.form_data, lease.docusign_envelope_id)
    root = settings.box_rental_properties_folder_id
    if not root:
        raise RuntimeError("BOX_RENTAL_PROPERTIES_FOLDER_ID must point to PRIVI/Rentals")
    folder = root
    for part in (lease.context["unit_address"], "Leases"):
        folder = await asyncio.to_thread(get_or_create_subfolder, folder, part, raise_errors=True)
        if not folder:
            raise RuntimeError(f"Box folder unavailable: {part}")
    local_date = lease.completed_at.astimezone(ZoneInfo(settings.timezone)).date()
    name = f"{local_date.isoformat()} Tenancy Agreement – {lease.context['tenant_names']}"
    file_id, _ = await asyncio.to_thread(upload_file, folder, f"{name}.pdf", pdf, raise_errors=True)
    if not file_id:
        raise RuntimeError("Box signed lease upload returned no file ID")
    certificate_id, _ = await asyncio.to_thread(upload_file, folder, f"{name} – Certificate.pdf", cert, raise_errors=True)
    if not certificate_id:
        raise RuntimeError("Box certificate upload returned no file ID")
    lease.signed_pdf_box_file_id = file_id
    lease.contact_form_data = lease_docusign.structured_contacts(values, lease.context)
    db.add(LeaseAgreementTask(lease_agreement_id=lease.id,
                              title=f"Send Plooto PAD setup to {lease.context['tenant_names']} – {lease.context['unit_address']}"))
    await db.commit()


async def apply_contacts(db: AsyncSession, lease: LeaseAgreement, user_id: UUID | None,
                         updates: list[dict[str, Any]]) -> None:
    if lease.status != "completed" or not lease.contact_form_data:
        raise ValueError("Completed contact form data is required")
    allowed = set((await db.scalars(select(RentalLeaseTenant.tenant_id).where(
        RentalLeaseTenant.lease_id == lease.tenancy_id))).all()) if lease.tenancy_id else set()
    for update in updates:
        tenant_id = int(update["tenant_id"])
        if tenant_id not in allowed:
            raise ValueError("Tenant is not linked to this tenancy")
        tenant = await db.get(RentalTenant, tenant_id)
        if tenant is None:
            raise ValueError("Tenant record not found")
        if update.get("phone") is not None:
            tenant.phone = str(update["phone"])
        if update.get("email") is not None:
            tenant.email = str(update["email"])
    event(db, lease, "apply_contacts", user_id, {"tenant_ids": [u["tenant_id"] for u in updates]})
    await db.commit()
