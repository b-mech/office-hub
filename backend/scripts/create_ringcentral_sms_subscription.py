"""Create the RingCentral inbound SMS webhook subscription.

This is deliberately an explicit operations command: importing the API or
starting a worker must never create an external subscription as a side effect.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(REPOSITORY_ROOT / ".env")

from app.core.config import settings  # noqa: E402
from app.services.maintenance.sms.providers import (  # noqa: E402
    RingCentralProvider,
    get_sms_provider,
)


async def create_subscription() -> None:
    if settings.sms_provider.casefold() != "ringcentral":
        raise SystemExit("SMS_PROVIDER must be ringcentral")
    if not settings.public_base_url.strip():
        raise SystemExit("PUBLIC_BASE_URL must be configured first")
    validation_token = settings.ringcentral_webhook_validation_token.get_secret_value()
    if not validation_token:
        raise SystemExit("RINGCENTRAL_WEBHOOK_VALIDATION_TOKEN must be configured first")

    provider = get_sms_provider()
    if not isinstance(provider, RingCentralProvider):
        raise SystemExit("RingCentral provider is not available")
    address = f"{settings.public_base_url.rstrip('/')}/api/webhooks/ringcentral/sms"
    result = await provider.create_sms_webhook_subscription(address, validation_token)
    print(f"Subscription ID: {result.get('id', 'unknown')}")
    print(f"Status: {result.get('status', 'unknown')}")
    print(f"Expiration: {result.get('expirationTime', 'unknown')}")


if __name__ == "__main__":
    asyncio.run(create_subscription())
