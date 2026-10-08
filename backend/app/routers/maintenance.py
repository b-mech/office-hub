from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.core import User
from app.models.maintenance import (
    MaintAttachment,
    MaintCategory,
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintPriority,
    MaintSmsMessage,
    MaintStatus,
    MaintTicket,
    MaintUnitToken,
    MaintVisibility,
)
from app.models.rentals import RentalLease, RentalLeaseTenant, RentalProperty, RentalTenant, RentalUnit
from app.services.maintenance.errors import InvalidMediaError
from app.services.maintenance.media import (
    download_attachment,
    store_attachment,
    validate_file_count,
    verify_signed_media_token,
)
from app.services.maintenance.notifier import get_maintenance_notifier
from app.services.maintenance.permissions import has_maintenance_permission
from app.services.maintenance.phones import normalize_phone
from app.services.maintenance.qr import (
    printable_pdf,
    public_url,
    resolve_intake_unit,
    rotate_for_unit,
    verify_print_token,
)
from app.services.maintenance.rate_limit import RateLimitExceeded, get_rate_limiter
from app.services.maintenance.sms.inbound import receive_sms, ringcentral_notification_form
from app.services.maintenance.sms.outbound import SmsOptedOutError, normalized_delivery_status, queue_sms
from app.services.maintenance.sms.providers import get_sms_provider
from app.services.maintenance.sms.templates import render_template
from app.services.maintenance.state_machine import ActorContext
from app.services.maintenance.tickets import TicketCreate, create_ticket
from app.services.maintenance.turnstile import TurnstileError, verify_turnstile
from app.services.maintenance.webhook_alerts import alert_ringcentral_webhook_failure
from app.services.maintenance.workspace import (
    acknowledge_ticket,
    actor_for,
    apply_more_action,
    apply_triage,
    assign_work,
    cancel_message,
    complete_order,
    list_ticket_views,
    post_message,
    resolve_ticket,
    retry_message,
    schedule_work,
    ticket_detail_view,
)
from app.schemas.maintenance import (
    AssignmentRequest,
    CompleteWorkOrderRequest,
    MoreActionRequest,
    ResolveRequest,
    ScheduleRequest,
    TriageRequest,
)


router = APIRouter(tags=["maintenance"])
logger = logging.getLogger("uvicorn.error")


def _invalid_link() -> str:
    return (
        "This maintenance link is invalid or has been replaced. "
        f"Please contact {settings.public_brand_name}."
    )


def _require_enabled() -> None:
    if not settings.maintenance_enabled:
        raise HTTPException(503, "Maintenance is not configured")


def _staff(request: Request, action: str) -> User | None:
    user = getattr(request.state, "user", None)
    if settings.auth_enforced and (user is None or not has_maintenance_permission(user, action)):
        raise HTTPException(403, "Maintenance permission required")
    return user


def _property_label(prop: RentalProperty) -> str:
    return prop.group_name or prop.street_address


def _unit_label(unit: RentalUnit) -> str:
    return unit.unit_label or "Main building"


async def _ticket_or_404(db: AsyncSession, ticket_id: UUID) -> MaintTicket:
    ticket = await db.get(MaintTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Maintenance ticket not found")
    return ticket


async def _commit_workspace(db: AsyncSession) -> None:
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise


@router.get("/api/public/maintenance/config")
async def public_config() -> dict[str, object]:
    property_phone = settings.privi_emergency_phone or "the number below"
    return {
        "enabled": settings.maintenance_enabled,
        "brand_name": settings.public_brand_name,
        "emergency_phone": settings.privi_emergency_phone,
        "manitoba_hydro_emergency_phone": settings.manitoba_hydro_emergency_phone,
        "turnstile_site_key": settings.effective_turnstile_site_key,
        "emergency_messages": {
            "gas_smell": settings.maint_gas_emergency_message.format(
                hydro_phone=settings.manitoba_hydro_emergency_phone,
                emergency_phone=property_phone,
            ),
            "default": settings.maint_emergency_message.format(emergency_phone=property_phone),
        },
    }


@router.get("/api/public/intake/{token}")
async def intake_context(token: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    _require_enabled()
    resolved = await resolve_intake_unit(db, token)
    if not resolved:
        raise HTTPException(404, _invalid_link())
    unit, prop = resolved
    return {"property_display_name": _property_label(prop), "unit_label": _unit_label(unit)}


async def _current_lease_for_phone(
    db: AsyncSession, unit_id: int, phone_e164: str
) -> RentalLease | None:
    today = date.today()
    return await db.scalar(
        select(RentalLease)
        .join(RentalLeaseTenant, RentalLeaseTenant.lease_id == RentalLease.id)
        .join(RentalTenant, RentalTenant.id == RentalLeaseTenant.tenant_id)
        .where(
            RentalLease.unit_id == unit_id,
            RentalTenant.phone == phone_e164,
            RentalLease.status.in_(["active", "month_to_month"]),
            (RentalLease.lease_end.is_(None) | (RentalLease.lease_end >= today)),
        )
        .order_by(RentalLease.lease_start.desc().nullslast())
        .limit(1)
    )


@router.post("/api/public/intake/{token}", status_code=201)
async def submit_intake(
    token: str,
    request: Request,
    name: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    category: Annotated[MaintCategory, Form()],
    description: Annotated[str, Form(min_length=10)],
    entry_permission: Annotated[str, Form()],
    turnstile_response: Annotated[str, Form(alias="cf-turnstile-response")],
    entry_notes: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    _require_enabled()
    remote_ip = request.headers.get("CF-Connecting-IP") or (
        request.client.host if request.client else "unknown"
    )
    try:
        await verify_turnstile(turnstile_response, remote_ip)
        await get_rate_limiter().intake(hashlib.sha256(token.encode()).hexdigest(), remote_ip)
        if not name.strip():
            raise ValueError("Your name is required")
        normalized_phone = normalize_phone(phone)
        validate_file_count(len(photos or []), party=MaintParty.TENANT)
    except RateLimitExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    except (TurnstileError, ValueError, InvalidMediaError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(503, "Submission protection is temporarily unavailable") from exc
    resolved = await resolve_intake_unit(db, token)
    if not resolved:
        raise HTTPException(404, _invalid_link())
    unit, prop = resolved

    lease = await _current_lease_for_phone(db, unit.id, normalized_phone)
    actor = ActorContext(party=MaintParty.TENANT, phone_e164=normalized_phone)
    try:
        ticket = await create_ticket(
            db,
            TicketCreate(
                property_id=prop.id,
                unit_id=unit.id,
                lease_id=lease.id if lease else None,
                source="tenant_qr",
                reporter_party=MaintParty.TENANT,
                reporter_name=name,
                reporter_phone=normalized_phone,
                reporter_verified=lease is not None,
                title=f"{category.value.replace('_', ' ').title()} — {_unit_label(unit)}",
                description=description,
                category=category,
                entry_permission=entry_permission,
                entry_notes=entry_notes,
            ),
            actor,
            channel=MaintEventChannel.WEB,
            visibility=MaintVisibility.EXTERNAL,
            direction=MaintDirection.INBOUND,
        )
        for photo in photos or []:
            attachment = await store_attachment(
                db,
                ticket_id=ticket.id,
                content=await photo.read(),
                original_filename=photo.filename,
                uploaded_by_party=MaintParty.TENANT,
            )
            event = MaintEvent(
                ticket_id=ticket.id,
                event_type="attachment_added",
                channel=MaintEventChannel.WEB,
                visibility=MaintVisibility.EXTERNAL,
                direction=MaintDirection.INBOUND,
                actor_party=MaintParty.TENANT,
                actor_phone_e164=normalized_phone,
                payload={"attachment_id": str(attachment.id)},
            )
            db.add(event)
            await db.flush()
            attachment.event_id = event.id
        try:
            await queue_sms(
                db,
                to=normalized_phone,
                body=render_template(
                    "tenant_intake_confirm", number=ticket.number, unit=_unit_label(unit)
                ),
                ticket_id=ticket.id,
                automated=True,
                emergency=ticket.is_emergency,
            )
        except SmsOptedOutError:
            db.add(
                MaintEvent(
                    ticket_id=ticket.id,
                    event_type="sms_blocked_opt_out",
                    channel=MaintEventChannel.SYSTEM,
                    visibility=MaintVisibility.INTERNAL,
                    direction=MaintDirection.NONE,
                    actor_party=MaintParty.SYSTEM,
                    payload={"phone_last4": normalized_phone[-4:]},
                )
            )
            await get_maintenance_notifier().opted_out(
                db, normalized_phone, source_key=f"ticket:{ticket.id}"
            )
        await get_maintenance_notifier().ticket_created(db, ticket)
        await db.commit()
    except (InvalidMediaError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ticket_number": ticket.number, "phone": normalized_phone}


@router.get("/api/public/media/{signed_token}")
async def public_media(signed_token: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    try:
        attachment_id = verify_signed_media_token(signed_token, settings.secret_key)
    except InvalidMediaError as exc:
        raise HTTPException(404, "Media link is invalid or expired") from exc
    attachment = await db.get(MaintAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "Media not found")
    content = await asyncio.to_thread(download_attachment, attachment.minio_key)
    return StreamingResponse(BytesIO(content), media_type=attachment.content_type)


def _webhook_url(request: Request) -> str:
    if settings.maintenance_enabled:
        return f"{settings.public_base_url.rstrip('/')}{request.url.path}"
    return str(request.url)


@router.post("/api/webhooks/twilio/status")
async def twilio_status(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    form_data = await request.form()
    form = {key: str(value) for key, value in form_data.items()}
    provider = get_sms_provider()
    if not provider.validate_signature(
        _webhook_url(request), form, request.headers.get("X-Twilio-Signature", "")
    ):
        raise HTTPException(403, "Invalid Twilio signature")
    message = await db.scalar(
        select(MaintSmsMessage).where(MaintSmsMessage.provider_sid == form.get("MessageSid"))
    )
    if message:
        provider_status = normalized_delivery_status(form.get("MessageStatus", ""))
        message.status = provider_status or message.status
        message.error_code = form.get("ErrorCode") or None
        message.updated_at = datetime.now(timezone.utc)
        if message.ticket_id:
            db.add(
                MaintEvent(
                    ticket_id=message.ticket_id,
                    work_order_id=message.work_order_id,
                    event_type="sms_status_changed",
                    channel=MaintEventChannel.SYSTEM,
                    visibility=MaintVisibility.INTERNAL,
                    direction=MaintDirection.NONE,
                    actor_party=MaintParty.SYSTEM,
                    sms_message_id=message.id,
                    payload={"status": message.status, "error_code": message.error_code},
                )
            )
        await get_maintenance_notifier().sms_status_changed(db, message)
        await db.commit()
    return Response(status_code=204)


@router.post("/api/webhooks/twilio/sms")
async def twilio_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    form_data = await request.form()
    form = {key: str(value) for key, value in form_data.items()}
    provider = get_sms_provider()
    if not provider.validate_signature(
        _webhook_url(request), form, request.headers.get("X-Twilio-Signature", "")
    ):
        raise HTTPException(403, "Invalid Twilio signature")
    try:
        await receive_sms(db, provider, get_maintenance_notifier(), form)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")


@router.post("/api/webhooks/ringcentral/sms")
async def ringcentral_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    raw_body = await request.body()
    validation_challenge = request.headers.get("Validation-Token", "")

    # RingCentral validates a new callback URL with an empty POST and requires
    # the supplied challenge token to be echoed in a small JSON response.
    if not raw_body:
        if not validation_challenge:
            try:
                await alert_ringcentral_webhook_failure(400, "validation token missing")
            except Exception:
                logger.exception("Could not post RingCentral webhook rejection alert")
            raise HTTPException(400, "Validation-Token is required")
        return Response(
            status_code=200,
            headers={"Validation-Token": validation_challenge},
            media_type="application/json",
        )

    supplied_token = request.headers.get("Verification-Token", "") or validation_challenge
    configured_token = settings.ringcentral_webhook_validation_token.get_secret_value()
    if not supplied_token:
        try:
            await alert_ringcentral_webhook_failure(403, "validation token missing")
        except Exception:
            logger.exception("Could not post RingCentral webhook rejection alert")
        raise HTTPException(403, "Invalid RingCentral validation token")
    if not configured_token:
        try:
            await alert_ringcentral_webhook_failure(403, "validation token configuration missing")
        except Exception:
            logger.exception("Could not post RingCentral webhook rejection alert")
        raise HTTPException(403, "Invalid RingCentral validation token")
    if not hmac.compare_digest(configured_token, supplied_token):
        try:
            await alert_ringcentral_webhook_failure(403, "validation token mismatched")
        except Exception:
            logger.exception("Could not post RingCentral webhook rejection alert")
        raise HTTPException(403, "Invalid RingCentral validation token")
    if settings.sms_provider.casefold() != "ringcentral":
        raise HTTPException(503, "RingCentral is not the selected SMS provider")

    try:
        payload = json.loads(raw_body)
        if payload == {"officeHubProbe": True}:
            return Response(status_code=200, media_type="application/json")
        notifications = payload if isinstance(payload, list) else [payload]
        if not notifications or not all(isinstance(item, dict) for item in notifications):
            raise ValueError("RingCentral notification payload is invalid")
        provider = get_sms_provider()
        for notification in notifications:
            await receive_sms(
                db,
                provider,
                get_maintenance_notifier(),
                ringcentral_notification_form(notification),
            )
        await db.commit()
    except (json.JSONDecodeError, ValueError) as exc:
        await db.rollback()
        try:
            await alert_ringcentral_webhook_failure(422, "invalid notification payload")
        except Exception:
            logger.exception("Could not post RingCentral webhook rejection alert")
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=200, media_type="application/json")


class PrintToken(BaseModel):
    token: str


@router.get("/api/maintenance/units/{unit_id}/qr")
async def qr_status(unit_id: int, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    _staff(request, "view")
    unit = await db.get(RentalUnit, unit_id)
    if unit is None:
        raise HTTPException(404, "Unit not found")
    active = await db.scalar(
        select(MaintUnitToken).where(MaintUnitToken.unit_id == unit_id, MaintUnitToken.revoked_at.is_(None))
    )
    return {
        "unit_id": unit_id,
        "property_id": unit.property_id,
        "active": active is not None,
        "created_at": active.created_at if active else None,
        "rotation_recommended": unit.maintenance_qr_rotation_recommended_at is not None,
    }


@router.post("/api/maintenance/units/{unit_id}/qr")
async def generate_qr(unit_id: int, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    _require_enabled()
    user = _staff(request, "admin")
    unit = await db.get(RentalUnit, unit_id)
    if unit is None:
        raise HTTPException(404, "Unit not found")
    raw, _ = await rotate_for_unit(db, unit, user.id if user else None)
    await db.commit()
    return {"token": raw, "url": public_url(raw)}


@router.post("/api/maintenance/units/{unit_id}/qr/print")
async def print_qr(unit_id: int, data: PrintToken, request: Request, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    _require_enabled()
    _staff(request, "view")
    unit = await db.get(RentalUnit, unit_id)
    active = await db.scalar(
        select(MaintUnitToken).where(MaintUnitToken.unit_id == unit_id, MaintUnitToken.revoked_at.is_(None))
    )
    if unit is None or not verify_print_token(data.token, active):
        raise HTTPException(404, "QR token not found or has been rotated")
    prop = await db.get(RentalProperty, unit.property_id)
    content = printable_pdf([(data.token, _property_label(prop), _unit_label(unit))])
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="maintenance-unit-{unit_id}.pdf"'},
    )


@router.post("/api/maintenance/properties/{property_id}/qr/print")
async def print_property_qrs(property_id: int, request: Request, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    _require_enabled()
    user = _staff(request, "admin")
    prop = await db.get(RentalProperty, property_id)
    if prop is None:
        raise HTTPException(404, "Property not found")
    units = list(
        (await db.scalars(select(RentalUnit).where(RentalUnit.property_id == property_id).order_by(RentalUnit.unit_label))).all()
    )
    cards: list[tuple[str, str, str]] = []
    for unit in units:
        raw, _ = await rotate_for_unit(db, unit, user.id if user else None)
        cards.append((raw, _property_label(prop), _unit_label(unit)))
    content = printable_pdf(cards)
    await db.commit()
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="maintenance-property-{property_id}.pdf"'},
    )


@router.get("/api/maintenance/tickets")
async def maintenance_tickets(
    request: Request,
    include_terminal: bool = False,
    status: MaintStatus | None = None,
    priority: MaintPriority | None = None,
    property_id: int | None = None,
    needs_reply: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    _staff(request, "view")
    return await list_ticket_views(
        db,
        include_terminal=include_terminal,
        status=status,
        priority=priority,
        property_id=property_id,
        needs_reply_only=needs_reply,
    )


@router.get("/api/maintenance/tickets/{ticket_id}")
async def maintenance_ticket(
    ticket_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _staff(request, "view")
    detail = await ticket_detail_view(db, ticket_id)
    if detail is None:
        raise HTTPException(404, "Maintenance ticket not found")
    return detail


@router.get("/api/maintenance/attachments/{attachment_id}")
async def maintenance_attachment(
    attachment_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    _staff(request, "view")
    attachment = await db.get(MaintAttachment, attachment_id)
    if attachment is None or attachment.ticket_id is None:
        raise HTTPException(404, "Attachment not found")
    content = await asyncio.to_thread(download_attachment, attachment.minio_key)
    filename = attachment.original_filename or str(attachment.id)
    return StreamingResponse(
        BytesIO(content),
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'inline; filename="{filename.replace(chr(34), "")}"'},
    )


@router.post("/api/maintenance/tickets/{ticket_id}/messages")
async def maintenance_message(
    ticket_id: UUID,
    request: Request,
    target: Annotated[str, Form()],
    body: Annotated[str, Form()] = "",
    work_order_id: Annotated[UUID | None, Form()] = None,
    attachments: Annotated[list[UploadFile] | None, File()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    user = _staff(request, "message_external")
    ticket = await _ticket_or_404(db, ticket_id)
    files = [(item.filename, await item.read()) for item in attachments or []]
    try:
        message = await post_message(
            db,
            ticket,
            actor_for(user),
            target=target,
            body=body,
            work_order_id=work_order_id,
            files=files,
        )
        await _commit_workspace(db)
    except (InvalidMediaError, SmsOptedOutError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "message_id": message.id if message else None}


@router.post("/api/maintenance/tickets/{ticket_id}/messages/{message_id}/cancel")
async def maintenance_cancel_message(
    ticket_id: UUID,
    message_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "message_external")
    message = await db.get(MaintSmsMessage, message_id)
    if message is None or message.ticket_id != ticket_id:
        raise HTTPException(404, "Message not found")
    try:
        await cancel_message(db, message_id, actor_for(user))
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.post("/api/maintenance/tickets/{ticket_id}/messages/{message_id}/retry")
async def maintenance_retry_message(
    ticket_id: UUID,
    message_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "message_external")
    message = await db.get(MaintSmsMessage, message_id)
    if message is None or message.ticket_id != ticket_id:
        raise HTTPException(404, "Message not found")
    try:
        await retry_message(db, message_id, actor_for(user))
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.post("/api/maintenance/tickets/{ticket_id}/triage")
async def maintenance_triage(
    ticket_id: UUID,
    data: TriageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "triage")
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        await apply_triage(db, ticket, actor_for(user), **data.model_dump())
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.post("/api/maintenance/tickets/{ticket_id}/assign")
async def maintenance_assign(
    ticket_id: UUID,
    data: AssignmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    user = _staff(request, "assign")
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        order = await assign_work(db, ticket, actor_for(user), **data.model_dump())
        await _commit_workspace(db)
    except (SmsOptedOutError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "work_order_id": order.id}


@router.post("/api/maintenance/tickets/{ticket_id}/schedule")
async def maintenance_schedule(
    ticket_id: UUID,
    data: ScheduleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "assign")
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        await schedule_work(db, ticket, actor_for(user), **data.model_dump())
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.post("/api/maintenance/tickets/{ticket_id}/work-orders/{work_order_id}/complete")
async def maintenance_complete_work_order(
    ticket_id: UUID,
    work_order_id: UUID,
    data: CompleteWorkOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "assign")
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        all_complete = await complete_order(
            db,
            ticket,
            actor_for(user),
            work_order_id=work_order_id,
            **data.model_dump(),
        )
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "all_work_orders_complete": all_complete}


@router.post("/api/maintenance/tickets/{ticket_id}/resolve")
async def maintenance_resolve(
    ticket_id: UUID,
    data: ResolveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "triage")
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        await resolve_ticket(db, ticket, actor_for(user), note=data.note)
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.post("/api/maintenance/tickets/{ticket_id}/more")
async def maintenance_more_action(
    ticket_id: UUID,
    data: MoreActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    permission = "admin" if data.action == "reopen" else "triage"
    user = _staff(request, permission)
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        await apply_more_action(db, ticket, actor_for(user), **data.model_dump())
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.post("/api/maintenance/tickets/{ticket_id}/acknowledge")
async def maintenance_acknowledge(
    ticket_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = _staff(request, "triage")
    ticket = await _ticket_or_404(db, ticket_id)
    try:
        acknowledged = await acknowledge_ticket(db, ticket, actor_for(user))
        await _commit_workspace(db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "acknowledged": acknowledged}
