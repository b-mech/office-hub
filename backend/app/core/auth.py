from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from jose import JWTError
from jose import jwt

from app.core.config import settings


ALGORITHM = "HS256"
ISSUER = "office-hub"


def create_access_token(user_id: UUID) -> str:
    return _encode_token(
        subject=str(user_id),
        token_type="access",
        expires_delta=timedelta(minutes=settings.auth_access_token_minutes),
    )


def create_refresh_token(user_id: UUID) -> str:
    return _encode_token(
        subject=str(user_id),
        token_type="refresh",
        expires_delta=timedelta(days=settings.auth_refresh_token_days),
    )


def create_oauth_state() -> str:
    return _encode_token(
        subject="google-login",
        token_type="oauth_state",
        expires_delta=timedelta(minutes=10),
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token") from exc
    if payload.get("type") != expected_type or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return payload


def _encode_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "type": token_type,
            "iss": ISSUER,
            "iat": now,
            "exp": now + expires_delta,
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )
