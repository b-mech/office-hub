from __future__ import annotations

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
from app.models.core import UserOrgMembership
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

# Routes that resolve the tenant themselves (app.core.tenancy). Every other
# authenticated /api route still serves legacy, org-less Connection Homes data
# and is limited to members of the default org (or superadmins).
TENANT_AWARE_PREFIXES = (
    "/api/v1/projects",
    "/api/v1/lots",
    "/api/v1/clients",
    "/api/v1/workspace",
    "/api/properties/",
    "/api/tender-packages",
    "/api/tender-documents",
    "/api/tender-document-markups",
    "/api/tender-bids",
    "/api/tender-bid-documents",
    "/api/contractor-categories",
    "/api/auth/",
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SIGN_IN_REQUIRED = "Office Hub sign-in is required"
SESSION_EXPIRED = "Your Office Hub session has expired. Sign in again."


def is_tenant_aware_path(path: str) -> bool:
    return path.startswith(TENANT_AWARE_PREFIXES)


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


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

        tenant_path = is_tenant_aware_path(path)
        legacy_cookie_path = tenant_path or path.startswith("/api/rentals/leases")

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
            if not user.is_superadmin and not tenant_path:
                legacy_member = await db.scalar(
                    select(UserOrgMembership.id).where(
                        UserOrgMembership.user_id == user.id,
                        UserOrgMembership.org_id == settings.default_org_id,
                    )
                )
                if legacy_member is None:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "This module is not available for your organization"},
                    )
            request.state.user = user
            request.state.auth_method = "cookie" if cookie_auth else "bearer"
            response = await call_next(request)  # type: ignore[operator]
        return response
