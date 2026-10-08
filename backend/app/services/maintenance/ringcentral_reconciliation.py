from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.maintenance import MaintSmsMessage
from app.services.maintenance.notifier import MaintenanceNotifier, get_maintenance_notifier
from app.services.maintenance.sms.inbound import receive_sms, ringcentral_notification_form
from app.services.maintenance.sms.providers import RingCentralProvider, SmsProvider, get_sms_provider


logger = logging.getLogger("uvicorn.error")
RECONCILIATION_LOOKBACK = timedelta(hours=24)


class RingCentralMessageStore(Protocol):
    async def list_inbound_messages(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> list[Mapping[str, object]]: ...


@dataclass(frozen=True)
class ReconciliationResult:
    scanned: int
    ingested: int
    existing: int
    ignored: int


def _creation_time(record: Mapping[str, object]) -> datetime:
    raw = record.get("creationTime")
    if not isinstance(raw, str) or not raw:
        raise ValueError("RingCentral message has no creation time")
    created_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc)


def _targets_configured_number(record: Mapping[str, object]) -> bool:
    recipients = record.get("to")
    return isinstance(recipients, list) and any(
        isinstance(item, Mapping)
        and str(item.get("phoneNumber", "")) == settings.ringcentral_from_number
        for item in recipients
    )


async def reconcile_ringcentral_messages(
    db: AsyncSession,
    provider: RingCentralMessageStore,
    notifier: MaintenanceNotifier,
    *,
    media_provider: SmsProvider | None = None,
    now: datetime | None = None,
) -> ReconciliationResult:
    """Ingest inbound message-store records that the webhook did not persist."""
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    records = await provider.list_inbound_messages(
        checked_at - RECONCILIATION_LOOKBACK,
        checked_at,
    )
    records.sort(key=_creation_time)

    candidate_ids = {
        str(record.get("id", ""))
        for record in records
        if record.get("id") is not None and _targets_configured_number(record)
    }
    existing_ids: set[str] = set()
    if candidate_ids:
        existing_ids = {
            str(value)
            for value in (
                await db.scalars(
                    select(MaintSmsMessage.provider_sid).where(
                        MaintSmsMessage.provider_sid.in_(candidate_ids)
                    )
                )
            ).all()
            if value is not None
        }

    ingested = 0
    ignored = 0
    selected_media_provider = media_provider
    if selected_media_provider is None:
        if not isinstance(provider, RingCentralProvider):
            raise TypeError("A media provider is required for a non-RingCentral message store")
        selected_media_provider = provider

    for record in records:
        message_id = str(record.get("id", ""))
        if (
            not message_id
            or str(record.get("direction", "")).casefold() != "inbound"
            or str(record.get("type", "")).casefold() not in {"sms", "mms"}
            or not _targets_configured_number(record)
        ):
            ignored += 1
            continue
        if message_id in existing_ids:
            continue
        await receive_sms(
            db,
            selected_media_provider,
            notifier,
            ringcentral_notification_form({"body": record}),
            now=_creation_time(record),
        )
        existing_ids.add(message_id)
        ingested += 1

    await db.flush()
    return ReconciliationResult(
        scanned=len(records),
        ingested=ingested,
        existing=len(candidate_ids & existing_ids) - ingested,
        ignored=ignored,
    )


async def run_reconciliation_once() -> ReconciliationResult:
    from app.core.database import AsyncSessionLocal

    provider = get_sms_provider()
    if not isinstance(provider, RingCentralProvider):
        raise RuntimeError("RingCentral is not the configured SMS provider")
    async with AsyncSessionLocal() as db:
        result = await reconcile_ringcentral_messages(
            db,
            provider,
            get_maintenance_notifier(),
            media_provider=provider,
        )
        await db.commit()
        return result


def run_reconciliation_sync() -> ReconciliationResult:
    return asyncio.run(run_reconciliation_once())
