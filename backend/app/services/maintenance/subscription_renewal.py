from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx
from redis.asyncio import Redis

from app.core.config import settings
from app.services.maintenance.scheduler_health import (
    SUBSCRIPTION_STALE_ALERT_LOCK_KEY,
    record_subscription_scheduler_heartbeat,
)
from app.services.maintenance.slack.client import HttpSlackClient, SlackClient
from app.services.maintenance.sms.providers import (
    RingCentralProvider,
    SmsProviderHttpError,
    get_sms_provider,
)


logger = logging.getLogger("uvicorn.error")


class SubscriptionProvider(Protocol):
    async def list_subscriptions(self) -> list[Mapping[str, object]]: ...

    async def update_sms_webhook_subscription(
        self,
        subscription_id: str,
        address: str,
    ) -> Mapping[str, object]: ...


class RingCentralSubscriptionError(RuntimeError):
    """Safe operational failure for the subscription renewal job."""


class NoActiveRingCentralSubscription(RingCentralSubscriptionError):
    pass


class MultipleActiveRingCentralSubscriptions(RingCentralSubscriptionError):
    pass


@dataclass(frozen=True)
class SubscriptionRenewalResult:
    subscription_id: str
    expires_at: datetime
    renewed: bool
    active_match_count: int


async def verify_public_webhook_token(callback_url: str, validation_token: str) -> None:
    """Verify the public route accepts the same private token written to RingCentral."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            callback_url,
            headers={"Verification-Token": validation_token},
            json={"officeHubProbe": True},
        )
    if response.status_code != 200:
        raise RingCentralSubscriptionError(
            f"public webhook validation-token probe returned HTTP {response.status_code}"
        )


def _parse_expiration(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise RingCentralSubscriptionError("active subscription has no expiration time")
    try:
        expiration = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RingCentralSubscriptionError("active subscription has an invalid expiration time") from exc
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    return expiration.astimezone(timezone.utc)


def _is_sms_event_filter(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.path.endswith("/message-store/instant") and any(
        item.casefold() == "sms" for item in parse_qs(parsed.query).get("type", [])
    )


def _matching_active_subscriptions(
    records: list[Mapping[str, object]], callback_url: str
) -> list[tuple[Mapping[str, object], datetime]]:
    matches: list[tuple[Mapping[str, object], datetime]] = []
    for record in records:
        delivery = record.get("deliveryMode")
        filters = record.get("eventFilters")
        if (
            str(record.get("status", "")).casefold() != "active"
            or not isinstance(delivery, Mapping)
            or str(delivery.get("transportType", "")).casefold() != "webhook"
            or str(delivery.get("address", "")).rstrip("/") != callback_url.rstrip("/")
            or not isinstance(filters, list)
            or not any(_is_sms_event_filter(item) for item in filters)
        ):
            continue
        matches.append((record, _parse_expiration(record.get("expirationTime"))))
    return matches


async def _post_failure_alert(
    detail: str,
    *,
    client: SlackClient | None,
) -> None:
    if client is None and not settings.slack_configured:
        logger.error("RingCentral subscription renewal failed: %s", detail)
        return
    await (client or HttpSlackClient()).post_message(
        settings.slack_emergency_destination,
        f"RingCentral subscription renewal failed in {settings.environment}: {detail}",
    )


async def maintain_ringcentral_subscription(
    *,
    provider: SubscriptionProvider | None = None,
    client: SlackClient | None = None,
    redis: Redis | None = None,
    now: datetime | None = None,
    probe: Callable[[str, str], Awaitable[None]] = verify_public_webhook_token,
) -> SubscriptionRenewalResult:
    """Reconcile one active webhook and its private token; never create a subscription."""
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    callback_url = f"{settings.public_base_url.rstrip('/')}/api/webhooks/ringcentral/sms"
    expires_at: datetime | None = None
    try:
        selected_provider = provider
        if selected_provider is None:
            configured = get_sms_provider()
            if not isinstance(configured, RingCentralProvider):
                raise RingCentralSubscriptionError("RingCentral is not the configured SMS provider")
            selected_provider = configured

        matches = _matching_active_subscriptions(
            await selected_provider.list_subscriptions(), callback_url
        )
        if not matches:
            raise NoActiveRingCentralSubscription(
                "no active SMS webhook subscription exists for this environment"
            )
        if len(matches) != 1:
            raise MultipleActiveRingCentralSubscriptions(
                f"expected one active SMS webhook subscription; found {len(matches)}"
            )

        record, expires_at = matches[0]
        subscription_id = str(record.get("id", "")).strip()
        if not subscription_id:
            raise RingCentralSubscriptionError("active subscription has no ID")
        validation_token = settings.ringcentral_webhook_validation_token.get_secret_value()
        if not validation_token:
            raise RingCentralSubscriptionError(
                "RingCentral webhook validation token is not configured"
            )

        # RingCentral does not return the private verification token from reads.
        # A full PUT is therefore the only deterministic reconciliation: it
        # renews the existing ID and overwrites the live token on every run.
        renewed_payload = await selected_provider.update_sms_webhook_subscription(
            subscription_id,
            callback_url,
        )
        expires_at = _parse_expiration(renewed_payload.get("expirationTime"))
        await probe(callback_url, validation_token)

        await record_subscription_scheduler_heartbeat(
            expires_at=expires_at,
            healthy=True,
            detail="validation token reconciled and public probe passed",
            redis=redis,
            now=checked_at,
        )
        if redis is not None:
            await redis.delete(SUBSCRIPTION_STALE_ALERT_LOCK_KEY)
        return SubscriptionRenewalResult(
            subscription_id=subscription_id,
            expires_at=expires_at,
            renewed=True,
            active_match_count=len(matches),
        )
    except Exception as exc:
        detail = (
            str(exc)
            if isinstance(exc, (RingCentralSubscriptionError, SmsProviderHttpError))
            else type(exc).__name__
        )
        try:
            await record_subscription_scheduler_heartbeat(
                expires_at=expires_at,
                healthy=False,
                detail=detail,
                redis=redis,
                now=checked_at,
            )
        except Exception:
            logger.exception("Could not record failed RingCentral renewal heartbeat")
        try:
            await _post_failure_alert(detail, client=client)
        except Exception:
            logger.exception("Could not post RingCentral renewal failure alert")
        raise


def run_subscription_renewal_sync() -> SubscriptionRenewalResult:
    return asyncio.run(maintain_ringcentral_subscription())
