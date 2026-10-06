from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.maintenance.slack.client import HttpSlackClient, SlackClient


HEARTBEAT_KEY = "officehub:maintenance:escalation:last-run"
STALE_ALERT_LOCK_KEY = "officehub:maintenance:escalation:stale-alert"
MAX_HEARTBEAT_AGE = timedelta(minutes=5)
STALE_ALERT_INTERVAL_SECONDS = 30 * 60


@dataclass(frozen=True)
class SchedulerHealth:
    healthy: bool
    last_run: datetime | None
    detail: str


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
