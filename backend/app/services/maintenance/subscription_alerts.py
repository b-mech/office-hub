from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.config import settings
from app.services.maintenance.slack.client import HttpSlackClient, SlackClient


logger = logging.getLogger("uvicorn.error")
REMINDER_INTERVAL_SECONDS = 24 * 60 * 60

# One atomic read/transition/reservation, shared by all workers. There is no TTL:
# deployment/worker restarts must not turn an ongoing failure into a new outage.
# Reserve BEFORE sending: an ambiguous Slack timeout or process crash must not
# create an hourly retry storm. See the documented at-most-once delivery tradeoff.
CLAIM_TRANSITION_LUA = """
local previous = redis.call('HGET', KEYS[1], 'status')
local last_alert = tonumber(redis.call('HGET', KEYS[1], 'last_alert_at'))
local current = ARGV[1]
local now = tonumber(ARGV[2])
local interval = tonumber(ARGV[3])
local event = ''
local can_send = ARGV[4] == '1'
local checked_at = tonumber(redis.call('HGET', KEYS[1], 'checked_at'))
if checked_at and now < checked_at then
    return event
end
if current == 'failing' then
    if previous ~= 'failing' then
        if can_send then
            event = 'failure'
        else
            redis.call('HDEL', KEYS[1], 'last_alert_at')
        end
    elseif can_send and not last_alert then
        event = 'failure'
    elseif can_send and now - last_alert >= interval then
        event = 'reminder'
    end
elseif previous == 'failing' and can_send then
    event = 'recovery'
end
redis.call('HSET', KEYS[1], 'status', current, 'checked_at', ARGV[2])
if event ~= '' then
    redis.call('HSET', KEYS[1], 'last_alert_at', ARGV[2])
end
return event
"""


def subscription_alert_state_key(callback_url: str) -> str:
    callback_hash = hashlib.sha256(callback_url.rstrip("/").encode()).hexdigest()[:20]
    return (
        f"officehub:{settings.environment.casefold()}:maintenance:"
        f"ringcentral-renewal:alerts:v1:{callback_hash}"
    )


async def alert_subscription_renewal_status(
    *,
    healthy: bool,
    callback_url: str,
    detail: str,
    client: SlackClient | None = None,
    redis: Redis | None = None,
    now: datetime | None = None,
) -> bool:
    """Alert on first failure/recovery, or once per 24h while still failing.

    The first successful observation silently establishes the healthy baseline.
    Redis state is environment/callback scoped and intentionally has no expiry.
    If persistence is unavailable, suppress Slack rather than fail open and spam.
    Reservation-before-send means a crash/ambiguous send may lose one notification;
    the next reminder is still eligible after 24h. Never delete state to retry.
    """
    can_send = client is not None or settings.slack_configured
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    owned = redis is None
    store = redis
    try:
        if store is None:
            store = Redis.from_url(settings.redis_url, decode_responses=True)
        event = await store.eval(
            CLAIM_TRANSITION_LUA,
            1,
            subscription_alert_state_key(callback_url),
            "ok" if healthy else "failing",
            checked_at.timestamp(),
            REMINDER_INTERVAL_SECONDS,
            "1" if can_send else "0",
        )
        if isinstance(event, bytes):
            event = event.decode()
        if not event:
            if not can_send and not healthy:
                logger.error("RingCentral renewal alerting unavailable: Slack is not configured")
            return False
        if event == "failure":
            text = f"RingCentral subscription renewal failed in {settings.environment}: {detail}"
        elif event == "reminder":
            text = (
                f"RingCentral subscription renewal still failing in {settings.environment} "
                f"(24-hour reminder): {detail}"
            )
        elif event == "recovery":
            text = f"RingCentral subscription renewal recovered in {settings.environment}: {detail}"
        else:
            raise ValueError("unexpected renewal alert transition")
        await (client or HttpSlackClient()).post_message(settings.slack_emergency_destination, text)
        return True
    except Exception as exc:
        # Do not log exception contents: transport/provider errors may include
        # private headers or URLs. Do not release an ambiguous delivery claim.
        logger.error("RingCentral renewal alert suppressed or delivery uncertain (%s)", type(exc).__name__)
        return False
    finally:
        if owned and store is not None:
            try:
                await store.aclose()
            except Exception as exc:
                logger.error("Could not close renewal alert state client (%s)", type(exc).__name__)
