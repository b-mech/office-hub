"""Explicit, secret-free staging verification actions. Never run renewal implicitly."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
STAGING_HOST = "officehub-staging.n10z.ca"
CALLBACK_PATH = "/api/webhooks/ringcentral/sms"
USER_ZONE = timezone(timedelta(hours=-5))


async def handshakes() -> bool:
    import httpx

    ok = True
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for label, base in [
            ("backend", "http://127.0.0.1:8001"),
            ("frontend", "http://127.0.0.1:3001"),
            ("public", "https://" + STAGING_HOST),
        ]:
            challenge = secrets.token_urlsafe(24)
            try:
                response = await client.post(
                    base + CALLBACK_PATH, headers={"Validation-Token": challenge}, content=b"",
                )
                echoed = response.headers.get("Validation-Token") == challenge
                print(f"{label}: HTTP {response.status_code}; Validation-Token echo={echoed}")
                ok = ok and response.status_code == 200 and echoed
            except Exception as exc:
                print(f"{label}: failed ({type(exc).__name__})")
                ok = False
    return ok


def staging_settings():
    from app.core.config import settings

    if settings.environment.casefold() != "staging" or urlsplit(settings.public_base_url).hostname != STAGING_HOST:
        raise RuntimeError("staging environment and callback host required")
    return settings


async def state() -> bool:
    from redis.asyncio import Redis
    from app.services.maintenance.subscription_alerts import subscription_alert_state_key

    settings = staging_settings()
    async with Redis.from_url(settings.redis_url, decode_responses=True) as store:
        key = subscription_alert_state_key(settings.public_base_url.rstrip("/") + CALLBACK_PATH)
        values = await store.hgetall(key)
        status = values.get("status", "absent")
        print("status:", status if status in {"ok", "failing", "absent"} else "invalid")
        print("TTL:", await store.ttl(key), "(-1 means persistent, -2 means absent)")
        for field in ["checked_at", "last_alert_at"]:
            try:
                formatted = datetime.fromtimestamp(float(values[field]), USER_ZONE).strftime("%Y-%m-%d %H:%M:%S")
                print(field + ":", formatted, "Winnipeg (UTC-5)")
            except (KeyError, ValueError, OverflowError, OSError):
                print(field + ": absent/invalid")
    return bool(values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--handshake", action="store_true", help="Only check own callback endpoints; no provider/Slack calls")
    action.add_argument("--state", action="store_true", help="Read the staging alert state; no provider/Slack calls")
    action.add_argument("--run-renewal", action="store_true", help="AFTER APPROVAL ONLY: calls RingCentral and may post one transition alert")
    args = parser.parse_args()
    # This command reports only controlled status information, never provider errors.
    logging.disable(logging.CRITICAL)
    try:
        if args.handshake:
            return 0 if asyncio.run(handshakes()) else 1
        if args.state:
            return 0 if asyncio.run(state()) else 1
        staging_settings()
        from app.services.maintenance.subscription_renewal import run_subscription_renewal_sync
        run_subscription_renewal_sync()
        print("Renewal succeeded; public HTTP 200 and Validation-Token echo verified")
        return 0
    except Exception as exc:
        print("Verification failed (" + type(exc).__name__ + ")")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
