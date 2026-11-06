from __future__ import annotations

import secrets
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.auth import LEGACY_REFRESH_COOKIE
from app.core.auth import SESSION_COOKIE
from app.core.auth import decode_token
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.core import User
from app.models.core import UserRole


PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/auth/session",
    "/api/v1/change-orders/webhook/docusign",
    "/api/v1/change-orders/qbo/oauth/callback",
    "/api/v1/box/oauth/callback",
    "/api/presales/approval-letters/intake",
}
PUBLIC_PREFIXES = (
    "/api/public/",
    "/api/webhooks/ringcentral/",
    "/api/webhooks/twilio/",
    "/api/rentals/reports/public/",
    "/api/presales/extension/",
)

# Machine routes used by the Chrome extension and the Next.js change-orders
# proxy. They authenticate with ``X-API-Key`` (checked again by each route's
# own dependency), so under AUTH_ENFORCED=true a request that carries a valid
# key and no user credential is let through instead of getting a sign-in 401.
API_KEY_PATHS = {
    ("POST", "/api/v1/ingest"),
    ("GET", "/api/financing/funds-notices/extension/properties"),
    ("POST", "/api/financing/funds-notices/intake"),
    ("GET", "/api/v1/box/status"),
    ("POST", "/api/v1/box/appraisal-prep"),
}
API_KEY_PREFIXES = (
    "/api/v1/change-orders",
)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SIGN_IN_REQUIRED = "Office Hub sign-in is required"
SESSION_EXPIRED = "Your Office Hub session has expired. Sign in again."


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def is_api_key_path(method: str, path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if (method.upper(), normalized) in API_KEY_PATHS:
        return True
    return normalized == API_KEY_PREFIXES[0] or normalized.startswith(tuple(f"{p}/" for p in API_KEY_PREFIXES))


def valid_api_key(request: Request) -> bool:
    expected = settings.office_hub_api_key or ""
    presented = request.headers.get("x-api-key") or ""
    return bool(expected) and bool(presented) and secrets.compare_digest(presented.encode(), expected.encode())


def allowed_origin_hosts(request: Request) -> set[str]:
    allowed = {urlsplit(settings.public_site_url).netloc, request.headers.get("host", ""),
               request.headers.get("x-forwarded-host", "")}
    allowed.update(urlsplit(value).netloc for value in settings.cors_origin_list)
    allowed.discard("")
    return allowed


def request_origin_allowed(request: Request) -> bool:
    """CSRF guard for cookie-authenticated writes: Origin (or Referer) must be ours."""
    source = request.headers.get("origin") or request.headers.get("referer") or ""
    if not source or source == "null":
        return False
    return urlsplit(source).netloc in allowed_origin_hosts(request)


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail},
                        headers={"WWW-Authenticate": 'Bearer realm="office-hub"'})


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Resolve ``request.state.user`` from a bearer token or the session cookie.

    * ``Authorization: Bearer <access token>`` (API clients, tests).
    * ``office_hub_session`` HttpOnly cookie (browser sign-in), on every /api route.
    * Legacy ``office_hub_refresh`` cookie (Google flow), on lease/tenant routes only.

    A presented credential that is invalid, expired, revoked, or belongs to an
    inactive user is always 401 -- it never degrades to the AUTH_ENFORCED=false
    fallback actor. Only requests with no credential at all reach that fallback,
    and only when AUTH_ENFORCED is false.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api") or is_public_path(path):
            return await call_next(request)  # type: ignore[operator]

        legacy_cookie_path = path.startswith("/api/rentals/leases")

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        token_type = "access"
        cookie_auth = False
        if scheme.casefold() != "bearer" or not token:
            token = request.cookies.get(SESSION_COOKIE, "")
            token_type = "session"
            if not token and legacy_cookie_path:
                token = request.cookies.get(LEGACY_REFRESH_COOKIE, "")
                token_type = "refresh"
            cookie_auth = bool(token)
            if not token and is_api_key_path(request.method, path) and valid_api_key(request):
                request.state.auth_method = "api_key"
                return await call_next(request)  # type: ignore[operator]
            if not token:
                if not settings.auth_enforced:
                    return await call_next(request)  # type: ignore[operator]
                return _unauthorized(SIGN_IN_REQUIRED)
        if cookie_auth and request.method not in SAFE_METHODS and not request_origin_allowed(request):
            return JSONResponse(status_code=403, content={"detail": "Invalid request origin"})
        try:
            payload = decode_token(token, token_type)
            user_id = UUID(payload["sub"])
        except (HTTPException, ValueError):
            return _unauthorized(SESSION_EXPIRED if cookie_auth else "Invalid or expired authentication token")

        async with AsyncSessionLocal() as db:
            user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
            if user is None:
                return _unauthorized("User is inactive or no longer exists")
            if token_type == "session" and payload.get("sv") != (user.session_version or 0):
                return _unauthorized(SESSION_EXPIRED)
            if user.role == UserRole.READONLY and request.method not in SAFE_METHODS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Readonly users cannot modify Office Hub data"},
                )
            request.state.user = user
            request.state.auth_method = "cookie" if cookie_auth else "bearer"
            response = await call_next(request)  # type: ignore[operator]
        return response
