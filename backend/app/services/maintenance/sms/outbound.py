from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.maintenance import (
    MaintDirection,
    MaintEvent,
    MaintEventChannel,
    MaintParty,
    MaintSmsMessage,
    MaintVendor,
    MaintVisibility,
)
from app.models.rentals import RentalTenant
from app.services.maintenance.media import create_signed_media_token
from app.services.maintenance.notifier import MaintenanceNotifier
from app.services.maintenance.sms.providers import SmsProvider


class SmsOptedOutError(ValueError):
    pass


def normalized_delivery_status(provider_status: str) -> str | None:
    status = provider_status.casefold()
    if status in {"accepted", "scheduled", "queued", "sending"}:
        return "queued"
    if status == "sent":
        return "sent"
    if status in {"delivered", "read"}:
        return "delivered"
    if status in {"failed", "undelivered"}:
        return "failed"
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    return None


def quiet_hours_release(now: datetime) -> datetime | None:
    local = now.astimezone(ZoneInfo(settings.timezone))
    start, end = settings.sms_automated_quiet_start, settings.sms_automated_quiet_end
    in_quiet = local.time() >= start or local.time() < end if start > end else start <= local.time() < end
    if not in_quiet:
        return None
    release_date = local.date() + timedelta(days=1) if local.time() >= start and start > end else local.date()
    release = datetime.combine(release_date, end, tzinfo=local.tzinfo)
    return release.astimezone(timezone.utc)


async def is_opted_out(db: AsyncSession, phone_e164: str) -> bool:
    vendor = await db.scalar(
        select(MaintVendor.id).where(
            MaintVendor.phone_e164 == phone_e164,
            MaintVendor.is_active.is_(True),
            MaintVendor.sms_opted_out.is_(True),
        ).limit(1)
    )
    if vendor:
        return True
    tenant = await db.scalar(
        select(RentalTenant.id).where(
            RentalTenant.phone == phone_e164,
            RentalTenant.sms_opted_out.is_(True),
        ).limit(1)
    )
    return tenant is not None


async def queue_sms(
    db: AsyncSession,
    *,
    to: str,
    body: str,
    ticket_id: UUID | None = None,
    work_order_id: UUID | None = None,
    media_attachment_ids: list[UUID] | None = None,
    automated: bool,
    emergency: bool = False,
    actor_party: MaintParty = MaintParty.SYSTEM,
    now: datetime | None = None,
    slack_channel_id: str | None = None,
    slack_ts: str | None = None,
) -> MaintSmsMessage:
    if await is_opted_out(db, to):
        raise SmsOptedOutError("Recipient has opted out of text messages")
    now = now or datetime.now(timezone.utc)
    outgoing = body.strip()
    hold_until = None
    status = "pending"
    if automated:
        if not emergency:
            hold_until = quiet_hours_release(now)
            if hold_until:
                status = "held"
    else:
        recent = await db.scalar(
            select(MaintSmsMessage.id).where(
                MaintSmsMessage.direction == MaintDirection.OUTBOUND,
                MaintSmsMessage.to_e164 == to,
                MaintSmsMessage.is_automated.is_(False),
                MaintSmsMessage.created_at >= now - timedelta(hours=24),
                MaintSmsMessage.cancelled_at.is_(None),
                MaintSmsMessage.status.notin_(["cancelled", "failed"]),
            ).limit(1)
        )
        if recent is None and settings.sms_signature.strip():
            outgoing = f"{outgoing} {settings.sms_signature.strip()}"
        if settings.sms_relay_hold_seconds:
            hold_until = now + timedelta(seconds=settings.sms_relay_hold_seconds)
            status = "held"
    message = MaintSmsMessage(
        direction=MaintDirection.OUTBOUND,
        from_e164=settings.sms_from_number or "",
        to_e164=to,
        body=outgoing,
        media_attachment_ids=media_attachment_ids or [],
        ticket_id=ticket_id,
        work_order_id=work_order_id,
        is_automated=automated,
        hold_until=hold_until,
        status=status,
        slack_channel_id=slack_channel_id,
        slack_ts=slack_ts,
        created_at=now,
        updated_at=now,
    )
    db.add(message)
    await db.flush()
    if ticket_id:
        db.add(
            MaintEvent(
                ticket_id=ticket_id,
                work_order_id=work_order_id,
                event_type="message",
                channel=MaintEventChannel.SMS if automated else MaintEventChannel.SLACK,
                visibility=MaintVisibility.EXTERNAL,
                direction=MaintDirection.OUTBOUND,
                actor_party=actor_party,
                body=outgoing,
                sms_message_id=message.id,
                created_at=now,
            )
        )
        await db.flush()
    return message


async def send_due_messages(
    db: AsyncSession,
    provider: SmsProvider,
    notifier: MaintenanceNotifier,
    *,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    messages = list(
        (
            await db.scalars(
                select(MaintSmsMessage).where(
                    MaintSmsMessage.direction == MaintDirection.OUTBOUND,
                    MaintSmsMessage.status.in_(["pending", "held"]),
                    MaintSmsMessage.cancelled_at.is_(None),
                    or_(MaintSmsMessage.hold_until.is_(None), MaintSmsMessage.hold_until <= now),
                ).with_for_update(skip_locked=True)
            )
        ).all()
    )
    processed = 0
    for message in messages:
        if message.cancelled_at is not None or (message.hold_until and message.hold_until > now):
            continue
        processed += 1
        media_urls = [
            f"{settings.public_base_url.rstrip('/')}/api/public/media/"
            f"{create_signed_media_token(item, settings.secret_key)}"
            for item in message.media_attachment_ids
        ]
        try:
            message.provider_sid = await provider.send(message.to_e164, message.body or "", media_urls)
            message.status = "queued"
            message.error_code = None
        except Exception as exc:
            message.status = "failed"
            message.error_code = type(exc).__name__
        message.updated_at = now
        if message.ticket_id:
            db.add(
                MaintEvent(
                    ticket_id=message.ticket_id,
                    work_order_id=message.work_order_id,
                    event_type="sms_send_failed" if message.status == "failed" else "sms_send_queued",
                    channel=MaintEventChannel.SYSTEM,
                    visibility=MaintVisibility.INTERNAL,
                    direction=MaintDirection.NONE,
                    actor_party=MaintParty.SYSTEM,
                    sms_message_id=message.id,
                    payload={"status": message.status, "error_code": message.error_code},
                    created_at=now,
                )
            )
        await notifier.sms_status_changed(message)
    await db.flush()
    return processed


async def run_sender_once() -> int:
    from app.core.database import AsyncSessionLocal
    from app.services.maintenance.notifier import get_maintenance_notifier
    from app.services.maintenance.sms.providers import get_sms_provider

    async with AsyncSessionLocal() as db:
        count = await send_due_messages(db, get_sms_provider(), get_maintenance_notifier())
        await db.commit()
        return count


def run_sender_sync() -> int:
    return asyncio.run(run_sender_once())
