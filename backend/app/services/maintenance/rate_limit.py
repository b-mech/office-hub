from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import settings


class RateLimitExceeded(ValueError):
    pass


@dataclass(frozen=True)
class RateLimit:
    name: str
    key: str
    maximum: int


class RedisRateLimiter:
    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)

    async def intake(self, token_hash: str, ip_address: str) -> None:
        await self._check(
            RateLimit("intake link", f"maint:intake:token:{token_hash}", 5),
            RateLimit("IP address", f"maint:intake:ip:{ip_address}", 10),
        )

    async def _check(self, *limits: RateLimit) -> None:
        pipe = self.redis.pipeline(transaction=True)
        for limit in limits:
            pipe.incr(limit.key)
            pipe.expire(limit.key, 3600, nx=True)
        results = await pipe.execute()
        for index, limit in enumerate(limits):
            if int(results[index * 2]) > limit.maximum:
                raise RateLimitExceeded(f"Too many submissions for this {limit.name}; try again later")


_limiter: RedisRateLimiter | None = None


def get_rate_limiter() -> RedisRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RedisRateLimiter()
    return _limiter
