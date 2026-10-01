from __future__ import annotations

import httpx

from app.core.config import settings


VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileError(ValueError):
    pass


async def verify_turnstile(response_token: str, remote_ip: str | None = None) -> None:
    secret = settings.effective_turnstile_secret_key
    if not secret:
        raise TurnstileError("Turnstile is not configured")
    if not response_token:
        raise TurnstileError("Complete the anti-spam check")
    data = {"secret": secret, "response": response_token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            result = (await client.post(VERIFY_URL, data=data)).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TurnstileError("Could not verify the anti-spam check") from exc
    if not result.get("success"):
        raise TurnstileError("The anti-spam check failed; please try again")
