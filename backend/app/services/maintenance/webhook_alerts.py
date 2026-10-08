from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.core.config import settings
from app.services.maintenance.slack.client import HttpSlackClient, SlackClient


logger = logging.getLogger("uvicorn.error")
WEBHOOK_FAILURE_ALERT_INTERVAL_SECONDS = 5 * 60


def _redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def alert_ringcentral_webhook_failure(
    status_code: int,
    reason: str,
    *,
    redis: Redis | None = None,
    client: SlackClient | None = None,
) -> bool:
    """Post at most one safe webhook-rejection alert per five-minute window."""
    logger.warning(
        "Rejected RingCentral webhook: status=%d reason=%s",
        status_code,
        reason,
    )
    if not settings.slack_configured:
        logger.error(
            "RingCentral webhook alert could not be posted because Slack is not configured"
        )
        return False

    owned = redis is None
    redis = redis or _redis_client()
    key = f"officehub:{settings.environment}:maintenance:ringcentral-webhook-failure-alert"
    try:
        claimed = await redis.set(
            key,
            f"http_{status_code}:{reason}",
            ex=WEBHOOK_FAILURE_ALERT_INTERVAL_SECONDS,
            nx=True,
        )
        if not claimed:
            return False
        try:
            await (client or HttpSlackClient()).post_message(
                settings.slack_emergency_destination,
                (
                    f"RingCentral webhook rejected in {settings.environment}: "
                    f"HTTP {status_code} ({reason}). Check the webhook subscription and "
                    "run message-store reconciliation."
                ),
            )
        except Exception:
            await redis.delete(key)
            raise
        return True
    finally:
        if owned:
            await redis.aclose()
