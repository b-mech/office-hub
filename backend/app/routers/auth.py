from __future__ import annotations

import logging
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
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import login_rate_limit
from app.core.auth import LEGACY_REFRESH_COOKIE
from app.core.auth import SESSION_COOKIE
from app.core.auth import create_access_token
from app.core.auth import create_oauth_state
from app.core.auth import create_refresh_token
from app.core.auth import create_session_token
from app.core.auth import decode_token
from app.core.config import settings
from app.core.database import get_db
from app.core.passwords import verify_password
from app.middleware.auth import request_origin_allowed
from app.models.core import Org
from app.models.core import User
from app.models.core import UserOrgMembership
from app.models.core import UserRole
from app.services import google_auth


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = LEGACY_REFRESH_COOKIE
OAUTH_STATE_COOKIE = "office_hub_oauth_state"
INVALID_CREDENTIALS = "Invalid email or password"


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


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class MembershipOut(BaseModel):
    org_id: UUID
    slug: str
    name: str
    role: str


class SessionUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_superadmin: bool


class AuthSessionOut(BaseModel):
    """Non-sensitive sign-in state for the frontend gate (no tokens)."""

    auth_enforced: bool
    authenticated: bool
    session_expired: bool = False
    password_login: bool = True
    user: SessionUserOut | None = None
    memberships: list[MembershipOut] = []
    expires_at: datetime | None = None


def _cookie_kwargs() -> dict[str, object]:
    return {"httponly": True, "secure": settings.auth_cookie_secure, "samesite": "lax", "path": "/"}


def _clear_auth_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, **_cookie_kwargs())  # type: ignore[arg-type]


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(settings.auth_session_hours * 60 * 60),
        **_cookie_kwargs(),  # type: ignore[arg-type]
    )


async def _memberships(db: AsyncSession, user: User) -> list[MembershipOut]:
    rows = (await db.execute(
        select(UserOrgMembership.role, Org.id, Org.slug, Org.name)
        .join(Org, Org.id == UserOrgMembership.org_id)
        .where(UserOrgMembership.user_id == user.id)
        .order_by(UserOrgMembership.created_at, UserOrgMembership.id)
    )).all()
    return [MembershipOut(org_id=org_id, slug=slug, name=name, role=str(getattr(role, "value", role)))
            for role, org_id, slug, name in rows]


def _session_user(user: User) -> SessionUserOut:
    return SessionUserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role,
                          is_superadmin=bool(user.is_superadmin))


async def _session_from_cookie(db: AsyncSession, token: str | None) -> tuple[User | None, datetime | None]:
    if not token:
        return None, None
    try:
        payload = decode_token(token, "session")
        user = await db.get(User, UUID(payload["sub"]))
    except (HTTPException, ValueError):
        return None, None
    if user is None or not user.is_active or payload.get("sv") != (user.session_version or 0):
        return None, None
    return user, datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)


@router.get("/login")
async def login() -> RedirectResponse:
    state = create_oauth_state()
    try:
        url = google_auth.authorization_url(state)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response = RedirectResponse(url)
    response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=10 * 60, **_cookie_kwargs())  # type: ignore[arg-type]
    return response


@router.post("/login", response_model=AuthSessionOut)
async def password_login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Email + password sign-in. Sets the HttpOnly session cookie; returns no token."""
    if (request.headers.get("origin") or request.headers.get("referer")) and not request_origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "Invalid request origin"})
    email = body.email.strip().casefold()
    ip = login_rate_limit.client_ip(request)
    retry_after = login_rate_limit.login_retry_after(ip, email)
    if retry_after:
        return JSONResponse(status_code=429, content={"detail": "Too many sign-in attempts. Try again later."},
                            headers={"Retry-After": str(retry_after)})

    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    valid = verify_password(body.password, user.password_hash if user is not None else None)
    if user is None or not valid or not user.is_active:
        login_rate_limit.record_failure(ip, email)
        logger.info("password sign-in failed ip=%s", ip)
        return JSONResponse(status_code=401, content={"detail": INVALID_CREDENTIALS})

    memberships = await _memberships(db, user)
    if not memberships and not user.is_superadmin:
        logger.warning("password sign-in denied: user=%s has no org membership", user.id)
        return JSONResponse(status_code=403,
                            content={"detail": "This account does not have access to any organization"})

    login_rate_limit.record_success(email)
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    token, expires_at = create_session_token(user.id, user.session_version or 0)
    out = AuthSessionOut(auth_enforced=settings.auth_enforced, authenticated=True, user=_session_user(user),
                         memberships=memberships, expires_at=expires_at)
    response = JSONResponse(content=out.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
    _set_session_cookie(response, token)
    logger.info("password sign-in user=%s", user.id)
    return response


@router.get("/session", response_model=AuthSessionOut)
async def session_state(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> Response:
    user, expires_at = await _session_from_cookie(db, session_token)
    expired = bool(session_token) and user is None
    out = AuthSessionOut(auth_enforced=settings.auth_enforced, authenticated=user is not None,
                         session_expired=expired)
    if user is not None:
        out.user = _session_user(user)
        out.memberships = await _memberships(db, user)
        out.expires_at = expires_at
    response = JSONResponse(content=out.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
    if expired:
        response.delete_cookie(SESSION_COOKIE, **_cookie_kwargs())  # type: ignore[arg-type]
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
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    _set_refresh_cookie(response, create_refresh_token(user.id))
    _set_session_cookie(response, create_session_token(user.id, user.session_version or 0)[0])
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
async def logout(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Clear the cookies and revoke the user's sessions server-side (session_version bump)."""
    if (request.headers.get("origin") or request.headers.get("referer")) and not request_origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "Invalid request origin"})
    user, _ = await _session_from_cookie(db, session_token)
    if user is not None:
        user.session_version = (user.session_version or 0) + 1
        await db.commit()
        logger.info("sign-out user=%s", user.id)
    response = Response(status_code=204)
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=CurrentUserOut)
async def me(request: Request) -> CurrentUserOut:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Office Hub sign-in is required")
    return CurrentUserOut.model_validate(user, from_attributes=True)


def _set_refresh_cookie(response: RedirectResponse, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.auth_refresh_token_days * 24 * 60 * 60,
        **_cookie_kwargs(),  # type: ignore[arg-type]
    )
