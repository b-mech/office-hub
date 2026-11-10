from __future__ import annotations

import asyncio

import pytest

from app.services.maintenance.ringcentral_tokens import RedisRingCentralTokenCache


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script: str, _key_count: int, key: str, expected: str) -> int:
        if self.values.get(key) != expected:
            return 0
        del self.values[key]
        return 1


@pytest.mark.asyncio
async def test_redis_token_cache_refreshes_once_across_concurrent_callers() -> None:
    cache = RedisRingCentralTokenCache("redis://unused", "staging")
    cache.redis = FakeRedis()  # type: ignore[assignment]
    refresh_count = 0

    async def refresh() -> tuple[str, int]:
        nonlocal refresh_count
        refresh_count += 1
        await asyncio.sleep(0.01)
        return "shared-access-token", 3600

    tokens = await asyncio.gather(*(cache.get_or_refresh(refresh) for _ in range(10)))

    assert tokens == ["shared-access-token"] * 10
    assert refresh_count == 1


@pytest.mark.asyncio
async def test_redis_token_cache_only_invalidates_matching_token() -> None:
    cache = RedisRingCentralTokenCache("redis://unused", "staging")
    redis = FakeRedis()
    cache.redis = redis  # type: ignore[assignment]
    redis.values[cache.token_key] = "new-token"

    await cache.invalidate("stale-token")
    assert redis.values[cache.token_key] == "new-token"

    await cache.invalidate("new-token")
    assert cache.token_key not in redis.values
