from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.maintenance.slack.client import HttpSlackClient, SlackClient


HEARTBEAT_KEY = "officehub:maintenance:escalation:last-run"
STALE_ALERT_LOCK_KEY = "officehub:maintenance:escalation:stale-alert"
SUBSCRIPTION_HEARTBEAT_KEY = "officehub:maintenance:ringcentral-renewal:last-run"
SUBSCRIPTION_STALE_ALERT_LOCK_KEY = "officehub:maintenance:ringcentral-renewal:stale-alert"
MAX_HEARTBEAT_AGE = timedelta(minutes=5)
MAX_SUBSCRIPTION_HEARTBEAT_AGE = timedelta(hours=2)
STALE_ALERT_INTERVAL_SECONDS = 30 * 60


@dataclass(frozen=True)
class SchedulerHealth:
    healthy: bool
    last_run: datetime | None
    detail: str
    expires_at: datetime | None = None


def _client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def record_scheduler_heartbeat(
    *, redis: Redis | None = None, now: datetime | None = None
) -> datetime:
    recorded_at = now or datetime.now(timezone.utc)
    owned = redis is None
    redis = redis or _client()
    try:
        await redis.set(HEARTBEAT_KEY, recorded_at.isoformat())
    finally:
        if owned:
            await redis.aclose()
    return recorded_at


async def scheduler_health(
    *, redis: Redis | None = None, now: datetime | None = None
) -> SchedulerHealth:
    checked_at = now or datetime.now(timezone.utc)
    owned = redis is None
    redis = redis or _client()
    try:
        raw = await redis.get(HEARTBEAT_KEY)
    except RedisError as exc:
        return SchedulerHealth(False, None, f"heartbeat store unavailable: {type(exc).__name__}")
    finally:
        if owned:
            await redis.aclose()
    if not raw:
        return SchedulerHealth(False, None, "escalation scheduler has not recorded a heartbeat")
    try:
        last_run = datetime.fromisoformat(str(raw))
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
    except ValueError:
        return SchedulerHealth(False, None, "escalation scheduler heartbeat is invalid")
    age = checked_at - last_run
    if age > MAX_HEARTBEAT_AGE:
        return SchedulerHealth(False, last_run, f"escalation scheduler heartbeat is {int(age.total_seconds())} seconds old")
    return SchedulerHealth(True, last_run, "ok")


async def record_subscription_scheduler_heartbeat(
    *,
    expires_at: datetime | None,
    healthy: bool,
    detail: str,
    redis: Redis | None = None,
    now: datetime | None = None,
) -> datetime:
    recorded_at = now or datetime.now(timezone.utc)
    owned = redis is None
    redis = redis or _client()
    payload = {
        "recorded_at": recorded_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "healthy": healthy,
        "detail": detail,
    }
    try:
        await redis.set(SUBSCRIPTION_HEARTBEAT_KEY, json.dumps(payload, separators=(",", ":")))
    finally:
        if owned:
            await redis.aclose()
    return recorded_at


async def subscription_scheduler_health(
    *, redis: Redis | None = None, now: datetime | None = None
) -> SchedulerHealth:
    checked_at = now or datetime.now(timezone.utc)
    owned = redis is None
    redis = redis or _client()
    try:
        raw = await redis.get(SUBSCRIPTION_HEARTBEAT_KEY)
    except RedisError as exc:
        return SchedulerHealth(False, None, f"heartbeat store unavailable: {type(exc).__name__}")
    finally:
        if owned:
            await redis.aclose()
    if not raw:
        return SchedulerHealth(False, None, "RingCentral renewal job has not recorded a heartbeat")
    try:
        payload = json.loads(str(raw))
        last_run = datetime.fromisoformat(str(payload["recorded_at"]))
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        raw_expiry = payload.get("expires_at")
        expires_at = datetime.fromisoformat(str(raw_expiry)) if raw_expiry else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        healthy = payload.get("healthy") is True
        detail = str(payload.get("detail") or "unknown RingCentral renewal state")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return SchedulerHealth(False, None, "RingCentral renewal heartbeat is invalid")
    age = checked_at - last_run
    if age > MAX_SUBSCRIPTION_HEARTBEAT_AGE:
        return SchedulerHealth(
            False,
            last_run,
            f"RingCentral renewal heartbeat is {int(age.total_seconds())} seconds old",
            expires_at,
        )
    if not healthy:
        return SchedulerHealth(False, last_run, detail, expires_at)
    if expires_at is None or expires_at <= checked_at:
        return SchedulerHealth(False, last_run, "RingCentral subscription is expired", expires_at)
    return SchedulerHealth(True, last_run, detail, expires_at)


async def alert_if_scheduler_stale(
    *,
    redis: Redis | None = None,
    client: SlackClient | None = None,
    now: datetime | None = None,
) -> bool:
    if not settings.slack_configured:
        return False
    checked_at = now or datetime.now(timezone.utc)
    owned = redis is None
    redis = redis or _client()
    try:
        health = await scheduler_health(redis=redis, now=checked_at)
        if health.healthy:
            return False
        claimed = await redis.set(
            STALE_ALERT_LOCK_KEY,
            checked_at.isoformat(),
            ex=STALE_ALERT_INTERVAL_SECONDS,
            nx=True,
        )
        if not claimed:
            return False
        since = health.last_run.isoformat() if health.last_run else "never"
        try:
            await (client or HttpSlackClient()).post_message(
                settings.slack_emergency_destination,
                f"Maintenance escalation scheduler has not run since {since}",
            )
        except Exception:
            await redis.delete(STALE_ALERT_LOCK_KEY)
            raise
        return True
    finally:
        if owned:
            await redis.aclose()


async def alert_if_subscription_scheduler_stale(
    *,
    redis: Redis | None = None,
    client: SlackClient | None = None,
    now: datetime | None = None,
) -> bool:
    if not settings.slack_configured:
        return False
    checked_at = now or datetime.now(timezone.utc)
    owned = redis is None
    redis = redis or _client()
    try:
        health = await subscription_scheduler_health(redis=redis, now=checked_at)
        if health.healthy:
            return False
        claimed = await redis.set(
            SUBSCRIPTION_STALE_ALERT_LOCK_KEY,
            checked_at.isoformat(),
            ex=STALE_ALERT_INTERVAL_SECONDS,
            nx=True,
        )
        if not claimed:
            return False
        try:
            await (client or HttpSlackClient()).post_message(
                settings.slack_emergency_destination,
                f"RingCentral subscription renewal scheduler is unhealthy: {health.detail}",
            )
        except Exception:
            await redis.delete(SUBSCRIPTION_STALE_ALERT_LOCK_KEY)
            raise
        return True
    finally:
        if owned:
            await redis.aclose()
