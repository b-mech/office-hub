from __future__ import annotations

from uuid import UUID
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

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


def is_tenant_aware_path(path: str) -> bool:
    return path.startswith(TENANT_AWARE_PREFIXES)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        path = request.url.path
        lease_path = path.startswith("/api/rentals/leases")
        tenant_path = is_tenant_aware_path(path)
        cookie_session_path = lease_path or tenant_path
        if (
            request.method == "OPTIONS"
            or not path.startswith("/api")
            or path in PUBLIC_PATHS
            or path.startswith(PUBLIC_PREFIXES)
            or (not settings.auth_enforced and not cookie_session_path)
        ):
            return await call_next(request)  # type: ignore[operator]

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        cookie_auth = False
        if scheme.casefold() != "bearer" or not token:
            if cookie_session_path:
                token = request.cookies.get("office_hub_refresh", "")
                cookie_auth = bool(token)
            if not token:
                if not settings.auth_enforced:
                    return await call_next(request)  # type: ignore[operator]
                return JSONResponse(status_code=401, content={"detail": "Office Hub sign-in is required"})
        if cookie_auth and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin", "")
            allowed = {urlsplit(settings.public_site_url).netloc, request.headers.get("host", ""),
                       request.headers.get("x-forwarded-host", "")}
            allowed.update(urlsplit(value).netloc for value in settings.cors_origin_list)
            if not origin or urlsplit(origin).netloc not in allowed:
                return JSONResponse(status_code=403, content={"detail": "Invalid request origin"})
        try:
            payload = decode_token(token, "refresh" if cookie_auth else "access")
            user_id = UUID(payload["sub"])
        except (HTTPException, ValueError):
            if cookie_auth and tenant_path and not settings.auth_enforced:
                # Stale session cookie on a single-user install: treat as anonymous.
                return await call_next(request)  # type: ignore[operator]
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired authentication token"})

        async with AsyncSessionLocal() as db:
            user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
            if user is None:
                return JSONResponse(status_code=401, content={"detail": "User is inactive or no longer exists"})
            if user.role == UserRole.READONLY and request.method not in {"GET", "HEAD", "OPTIONS"}:
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
            response = await call_next(request)  # type: ignore[operator]
        return response
