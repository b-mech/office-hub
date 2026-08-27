from __future__ import annotations

from datetime import datetime
from datetime import timezone
from uuid import UUID

import httpx
from fastapi import APIRouter
from fastapi import Cookie
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token
from app.core.auth import create_oauth_state
from app.core.auth import create_refresh_token
from app.core.auth import decode_token
from app.core.config import settings
from app.core.database import get_db
from app.models.core import User
from app.models.core import UserRole
from app.services import google_auth


router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "office_hub_refresh"
OAUTH_STATE_COOKIE = "office_hub_oauth_state"


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    permissions: dict[str, str]


@router.get("/login")
async def login() -> RedirectResponse:
    state = create_oauth_state()
    try:
        url = google_auth.authorization_url(state)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response = RedirectResponse(url)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=10 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/api/auth/callback",
    )
    return response


@router.get("/callback")
async def callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not state_cookie or state_cookie != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    decode_token(state, "oauth_state")
    try:
        profile = await google_auth.exchange_code(code)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Google login could not be completed") from exc

    email = str(profile.get("email", "")).strip().casefold()
    subject = str(profile.get("sub", "")).strip()
    if not email or not subject or profile.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="A verified Google email is required")

    user = await db.scalar(
        select(User).where(
            or_(User.google_subject == subject, func.lower(User.email) == email)
        )
    )
    if user is None:
        user = User(
            org_id=settings.default_org_id,
            email=email,
            google_subject=subject,
            full_name=str(profile.get("name") or email),
            role=UserRole.READONLY,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    elif user.google_subject and user.google_subject != subject:
        raise HTTPException(status_code=409, detail="This email is linked to another Google account")
    else:
        user.google_subject = subject
        user.full_name = str(profile.get("name") or user.full_name)
        user.is_active = True

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    response = RedirectResponse(settings.frontend_auth_callback_url)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/auth/callback")
    _set_refresh_cookie(response, create_refresh_token(user.id))
    return response


@router.post("/refresh", response_model=SessionOut)
async def refresh(
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token is missing")
    payload = decode_token(refresh_token, "refresh")
    user = await db.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive or no longer exists")
    return SessionOut(
        access_token=create_access_token(user.id),
        expires_in=settings.auth_access_token_minutes * 60,
    )


@router.post("/logout", status_code=204)
async def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return response


@router.get("/me", response_model=CurrentUserOut)
async def me(request: Request) -> CurrentUserOut:
    user = request.state.user
    return CurrentUserOut.model_validate(user, from_attributes=True)


def _set_refresh_cookie(response: RedirectResponse, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.auth_refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )
