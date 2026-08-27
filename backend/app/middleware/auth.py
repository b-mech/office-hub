from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.auth import decode_token
from app.core.database import AsyncSessionLocal
from app.models.core import User
from app.models.core import UserRole


PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/v1/change-orders/webhook/docusign",
    "/api/v1/change-orders/qbo/oauth/callback",
    "/api/v1/box/oauth/callback",
}
PUBLIC_PREFIXES = (
    "/api/rentals/reports/public/",
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or not path.startswith("/api")
            or path in PUBLIC_PATHS
            or path.startswith(PUBLIC_PREFIXES)
        ):
            return await call_next(request)  # type: ignore[operator]

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            return JSONResponse(status_code=401, content={"detail": "Bearer token is required"})
        try:
            payload = decode_token(token, "access")
            user_id = UUID(payload["sub"])
        except (HTTPException, ValueError):
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
            request.state.user = user
            response = await call_next(request)  # type: ignore[operator]
        return response
