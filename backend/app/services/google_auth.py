from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def authorization_url(state: str) -> str:
    _ensure_configured()
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode({
        'client_id': settings.google_auth_client_id,
        'redirect_uri': settings.google_auth_redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    })}"


async def exchange_code(code: str) -> dict[str, Any]:
    _ensure_configured()
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_auth_client_id,
                "client_secret": settings.google_auth_client_secret,
                "redirect_uri": settings.google_auth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise ValueError("Google did not return an access token")
        user_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_response.raise_for_status()
        return user_response.json()


def _ensure_configured() -> None:
    if not settings.google_auth_client_id or not settings.google_auth_client_secret:
        raise RuntimeError("Google login is not configured")
