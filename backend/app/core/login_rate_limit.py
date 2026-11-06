"""Small in-process limiter for failed password sign-ins.

The backend runs as a single uvicorn process behind the Next.js proxy and
Cloudflare, so an in-memory sliding window is enough and adds no dependency.
Failures are counted per client IP and per normalised email; a success clears
the email bucket. Restarting the backend resets the counters.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import deque

from fastapi import Request

from app.core.config import settings


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float, window: float) -> deque[float]:
        bucket = self._hits.setdefault(key, deque())
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if not bucket:
            self._hits.pop(key, None)
            bucket = self._hits.setdefault(key, deque())
        return bucket

    def retry_after(self, key: str, limit: int, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now, window)
            if len(bucket) < limit:
                return 0
            return max(1, int(bucket[0] + window - now) + 1)

    def hit(self, key: str, window: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now, window).append(now)

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


failures = SlidingWindow()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    try:
        trusted_proxy = ipaddress.ip_address(peer).is_loopback or ipaddress.ip_address(peer).is_private
    except ValueError:
        trusted_proxy = False
    if trusted_proxy:
        forwarded = (request.headers.get("cf-connecting-ip") or "").strip()
        if not forwarded:
            forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer or "unknown"


def login_retry_after(ip: str, email: str) -> int:
    window = float(settings.auth_login_window_seconds)
    return max(
        failures.retry_after(f"ip:{ip}", settings.auth_login_max_failures_per_ip, window),
        failures.retry_after(f"email:{email}", settings.auth_login_max_failures_per_email, window),
    )


def record_failure(ip: str, email: str) -> None:
    window = float(settings.auth_login_window_seconds)
    failures.hit(f"ip:{ip}", window)
    failures.hit(f"email:{email}", window)


def record_success(email: str) -> None:
    failures.clear(f"email:{email}")
