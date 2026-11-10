from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import uuid4

from redis.asyncio import Redis


TokenRefresher = Callable[[], Awaitable[tuple[str, int]]]


class RingCentralTokenCache(Protocol):
    async def get_or_refresh(self, refresh: TokenRefresher) -> str: ...

    async def invalidate(self, token: str) -> None: ...

    async def aclose(self) -> None: ...


class LocalRingCentralTokenCache:
    """Process-local cache used only by isolated provider tests."""

    def __init__(self) -> None:
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_or_refresh(self, refresh: TokenRefresher) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            token, expires_in = await refresh()
            self._token = token
            self._expires_at = time.monotonic() + max(expires_in - 60, 60)
            return token

    async def invalidate(self, token: str) -> None:
        async with self._lock:
            if self._token == token:
                self._token = ""
                self._expires_at = 0.0

    async def aclose(self) -> None:
        return None


class RedisRingCentralTokenCache:
    """One RingCentral access token and refresh lock shared by an environment."""

    _RELEASE_LOCK = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
    """
    _DELETE_MATCHING = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
    """

    def __init__(self, redis_url: str, environment: str) -> None:
        self.redis_url = redis_url
        self.redis: Redis | None = None
        prefix = f"officehub:{environment}:ringcentral:oauth"
        self.token_key = f"{prefix}:access-token"
        self.lock_key = f"{prefix}:refresh-lock"

    async def get_or_refresh(self, refresh: TokenRefresher) -> str:
        owned = self.redis is None
        redis = self.redis or Redis.from_url(self.redis_url, decode_responses=True)
        try:
            cached = await redis.get(self.token_key)
            if cached:
                return cached

            owner = uuid4().hex
            deadline = time.monotonic() + 20
            while not await redis.set(self.lock_key, owner, ex=30, nx=True):
                cached = await redis.get(self.token_key)
                if cached:
                    return cached
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out waiting for the RingCentral OAuth refresh lock")
                await asyncio.sleep(0.1)

            try:
                cached = await redis.get(self.token_key)
                if cached:
                    return cached
                token, expires_in = await refresh()
                await redis.set(
                    self.token_key,
                    token,
                    ex=max(expires_in - 60, 60),
                )
                return token
            finally:
                await redis.eval(self._RELEASE_LOCK, 1, self.lock_key, owner)
        finally:
            if owned:
                await redis.aclose()

    async def invalidate(self, token: str) -> None:
        owned = self.redis is None
        redis = self.redis or Redis.from_url(self.redis_url, decode_responses=True)
        try:
            await redis.eval(self._DELETE_MATCHING, 1, self.token_key, token)
        finally:
            if owned:
                await redis.aclose()

    async def aclose(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
