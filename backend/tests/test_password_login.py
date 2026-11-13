"""Password sign-in, session cookie, CSRF, and fallback semantics.

Unit tests (hashing) always run. API tests need a dedicated, migrated (20261113_0063+)
*test* database, exactly like test_workspace_tenancy_integration::

    OFFICEHUB_INTEGRATION_DB=officehub_login_test \
    DATABASE_URL=postgresql+asyncpg://.../officehub_login_test pytest

Passwords are generated per run; nothing is sent anywhere.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core import passwords


DB_NAME = os.environ.get("OFFICEHUB_INTEGRATION_DB", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ENABLED = bool(DB_NAME) and "test" in DB_NAME and DB_NAME != "officehub" and DATABASE_URL.rsplit("/", 1)[-1] == DB_NAME
db_only = pytest.mark.skipif(not ENABLED, reason="set OFFICEHUB_INTEGRATION_DB to a dedicated *test* database")

ORIGIN = "https://officehub.n10z.ca"


# ── unit: hashing ────────────────────────────────────────────────────────────

def test_hash_and_verify_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(passwords, "BCRYPT_ROUNDS", 4)
    secret = secrets.token_urlsafe(18)
    hashed = passwords.hash_password(secret)
    assert hashed.startswith("$2") and secret not in hashed
    assert passwords.verify_password(secret, hashed)
    assert not passwords.verify_password(secret + "x", hashed)
    assert not passwords.verify_password(secret, None)
    assert not passwords.verify_password(secret, "not-a-hash")


def test_password_policy() -> None:
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.hash_password("short")
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.hash_password("x" * 73)
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.hash_password(" leading-space-password")


def test_overlong_password_never_matches_truncated_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(passwords, "BCRYPT_ROUNDS", 4)
    base = "a" * 72
    hashed = passwords.hash_password(base)
    assert passwords.verify_password(base, hashed)
    assert not passwords.verify_password(base + "tail", hashed)


# ── API ──────────────────────────────────────────────────────────────────────

if ENABLED:
    from app.core import login_rate_limit
    from app.core.auth import SESSION_COOKIE
    from app.core.auth import _encode_token
    from app.core.auth import create_session_token
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app
    from app.middleware import auth as auth_middleware


@dataclass
class World:
    ch: UUID
    other: UUID
    users: dict[str, UUID]
    emails: dict[str, str]
    secret: str


async def _build() -> World:
    """Staging is single-org (``users.org_id``); there is no membership table here."""
    sfx = uuid4().hex[:8]
    secret = secrets.token_urlsafe(18)
    hashed = passwords.hash_password(secret)
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    users: dict[str, UUID] = {}
    emails: dict[str, str] = {}
    async with engine.begin() as conn:
        async def one(sql: str, **params: object) -> UUID:
            return (await conn.execute(text(sql + " RETURNING id"), params)).scalar_one()

        ch = await one("INSERT INTO core.orgs (name, slug) VALUES (:n, :s)", n=f"CH Login {sfx}", s=f"ch-login-{sfx}")
        other = await one("INSERT INTO core.orgs (name, slug) VALUES (:n, :s)", n=f"Other Login {sfx}", s=f"other-login-{sfx}")
        specs = [  # key, org, role, active
            ("ch_admin", ch, "admin", True),
            ("ch_readonly", ch, "readonly", True),
            ("ch_staff", ch, "staff", True),
            ("inactive", ch, "staff", False),
            ("no_password", ch, "staff", True),
        ]
        for index, (key, home, role, active) in enumerate(specs):
            emails[key] = f"{key}-{sfx}@Example.test"
            users[key] = await one(
                "INSERT INTO core.users (org_id, email, full_name, role, is_active, password_hash, created_at)"
                " VALUES (:o, :e, :f, :r, :a, :h, now() + make_interval(secs => :i))",
                o=home, e=emails[key], f=f"{key} {sfx}", r=role, a=active,
                h=None if key == "no_password" else hashed, i=index,
            )
    await engine.dispose()
    return World(ch, other, users, emails, secret)


@pytest.fixture(scope="module")
def world() -> World:
    passwords.BCRYPT_ROUNDS = 4
    return asyncio.run(_build())


@pytest.fixture
def wired(world: World, monkeypatch: pytest.MonkeyPatch):
    factory = async_sessionmaker(create_async_engine(DATABASE_URL, poolclass=NullPool), expire_on_commit=False)

    async def test_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    monkeypatch.setattr(auth_middleware, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "default_org_id", world.ch)
    monkeypatch.setattr(settings, "auth_enforced", True)
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    monkeypatch.setattr(settings, "public_site_url", ORIGIN)
    monkeypatch.setattr(settings, "office_hub_api_key", API_KEY)
    login_rate_limit.failures.clear()
    yield factory
    login_rate_limit.failures.clear()
    app.dependency_overrides.clear()


API_KEY = "test-extension-key-" + secrets.token_hex(8)
PROTECTED = "/api/v1/users"  # admin-only list on this branch
WRITE = "/api/v1/users/invite"  # admin-only write; {} -> 422 once auth + CSRF pass


async def call(method: str, path: str, cookie: str | None = None, **kwargs: object) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}) or {})  # type: ignore[arg-type]
    if cookie is not None:
        headers["Cookie"] = f"{SESSION_COOKIE}={cookie}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.request(method, path, headers=headers, **kwargs)


def session_cookie(response: httpx.Response) -> tuple[str, str]:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{SESSION_COOKIE}="):
            return header.split(";", 1)[0].split("=", 1)[1], header
    raise AssertionError(f"no session cookie in {response.headers.get_list('set-cookie')}")


async def login(world: World, key: str, password: str | None = None, **kwargs: object) -> httpx.Response:
    return await call("POST", "/api/auth/login", json={"email": world.emails[key], "password": password or world.secret},
                      headers={"Origin": ORIGIN}, **kwargs)


@db_only
@pytest.mark.asyncio
@pytest.mark.parametrize("secure", [True, False])
async def test_login_sets_hardened_cookie_and_returns_no_token(world: World, wired, monkeypatch, secure: bool) -> None:
    monkeypatch.setattr(settings, "auth_cookie_secure", secure)
    response = await login(world, "ch_admin")
    assert response.status_code == 200, response.text
    token, header = session_cookie(response)
    attrs = [part.strip().lower() for part in header.split(";")]
    assert "httponly" in attrs and "samesite=lax" in attrs and "path=/" in attrs
    assert ("secure" in attrs) is secure
    assert f"max-age={int(settings.auth_session_hours * 3600)}" in attrs
    body = response.json()
    assert token not in response.text and "token" not in body
    assert body["authenticated"] is True and body["user"]["id"] == str(world.users["ch_admin"])
    assert [m["org_id"] for m in body["memberships"]] == [str(world.ch)]
    assert response.headers["cache-control"] == "no-store"


@db_only
@pytest.mark.asyncio
async def test_email_is_case_insensitive(world: World, wired) -> None:
    response = await call("POST", "/api/auth/login", json={"email": f"  {world.emails['ch_admin'].upper()} ",
                                                          "password": world.secret})
    assert response.status_code == 200, response.text


@db_only
@pytest.mark.asyncio
async def test_failures_are_generic(world: World, wired) -> None:
    wrong = await login(world, "ch_admin", password=world.secret + "!")
    unknown = await call("POST", "/api/auth/login", json={"email": "nobody@example.test", "password": world.secret})
    inactive = await login(world, "inactive")
    no_password = await login(world, "no_password")
    for response in (wrong, unknown, inactive, no_password):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password"}
        assert not response.headers.get_list("set-cookie")


@db_only
@pytest.mark.asyncio
async def test_cookie_session_authenticates_when_enforced(world: World, wired) -> None:
    assert (await call("GET", PROTECTED)).status_code == 401
    assert (await call("GET", "/api/rentals/leases/units/1")).status_code == 401
    token, _ = session_cookie(await login(world, "ch_admin"))
    listed = await call("GET", PROTECTED, token)
    assert listed.status_code == 200, listed.text
    me = await call("GET", "/api/auth/me", token)
    assert me.status_code == 200 and me.json()["id"] == str(world.users["ch_admin"])
    staff, _ = session_cookie(await login(world, "ch_staff"))
    assert (await call("GET", PROTECTED, staff)).status_code == 403  # signed in, not an admin


@db_only
@pytest.mark.asyncio
async def test_deactivation_takes_effect_on_live_sessions(world: World, wired) -> None:
    factory = wired
    token, _ = session_cookie(await login(world, "ch_readonly"))
    assert (await call("GET", "/api/auth/me", token)).status_code == 200
    async with factory() as db:
        await db.execute(text("UPDATE core.users SET is_active = false WHERE id = :u"), {"u": world.users["ch_readonly"]})
        await db.commit()
    assert (await call("GET", "/api/auth/me", token)).status_code == 401
    async with factory() as db:
        await db.execute(text("UPDATE core.users SET is_active = true WHERE id = :u"), {"u": world.users["ch_readonly"]})
        await db.commit()


@db_only
@pytest.mark.asyncio
async def test_readonly_cookie_session_cannot_write(world: World, wired) -> None:
    token, _ = session_cookie(await login(world, "ch_readonly"))
    response = await call("POST", WRITE, token, json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 403


@db_only
@pytest.mark.asyncio
async def test_logout_clears_cookie_and_revokes_session(world: World, wired) -> None:
    token, _ = session_cookie(await login(world, "ch_admin"))
    response = await call("POST", "/api/auth/logout", token, headers={"Origin": ORIGIN})
    assert response.status_code == 204
    cleared = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{SESSION_COOKIE}=")]
    assert cleared and "max-age=0" in cleared[0].lower()
    assert (await call("GET", PROTECTED, token)).status_code == 401
    state = (await call("GET", "/api/auth/session", token)).json()
    assert state["authenticated"] is False and state["session_expired"] is True
    fresh, _ = session_cookie(await login(world, "ch_admin"))
    assert fresh != token
    assert (await call("GET", PROTECTED, fresh)).status_code == 200


@db_only
@pytest.mark.asyncio
@pytest.mark.parametrize("enforced", [True, False])
async def test_bad_cookies_are_rejected_never_fallback(world: World, wired, monkeypatch, enforced: bool) -> None:
    monkeypatch.setattr(settings, "auth_enforced", enforced)
    uid = world.users["ch_admin"]
    expired = _encode_token(str(uid), "session", timedelta(seconds=-5), {"sv": 0})
    wrong_type = _encode_token(str(uid), "access", timedelta(minutes=5))
    stale_version, _ = create_session_token(uid, 999)
    for token in ("garbage", expired, wrong_type, stale_version):
        for path in (PROTECTED, "/api/auth/me", "/api/rentals/leases/units/1"):
            response = await call("GET", path, token)
            assert response.status_code == 401, (path, token[:12], response.text)


@db_only
@pytest.mark.asyncio
async def test_session_cookie_used_when_auth_disabled(world: World, wired, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enforced", False)
    token, _ = session_cookie(await login(world, "ch_staff"))
    me = await call("GET", "/api/auth/me", token)
    assert me.status_code == 200 and me.json()["id"] == str(world.users["ch_staff"])
    assert (await call("GET", PROTECTED, token)).status_code == 403
    state = (await call("GET", "/api/auth/session")).json()
    assert state == {**state, "auth_enforced": False, "authenticated": False, "session_expired": False}
    assert (await call("GET", "/api/auth/me")).status_code == 401


@db_only
@pytest.mark.asyncio
async def test_cookie_writes_require_same_origin(world: World, wired) -> None:
    token, _ = session_cookie(await login(world, "ch_admin"))
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}, {"Referer": "https://evil.example/x"}):
        response = await call("POST", WRITE, token, json={}, headers=headers)
        assert response.status_code == 403 and response.json()["detail"] == "Invalid request origin", headers
    ok = await call("POST", WRITE, token, json={}, headers={"Origin": ORIGIN})
    assert ok.status_code == 422  # passed auth + CSRF, rejected by validation
    via_referer = await call("POST", WRITE, token, json={}, headers={"Referer": f"{ORIGIN}/settings"})
    assert via_referer.status_code == 422
    cross_login = await call("POST", "/api/auth/login", json={"email": world.emails["ch_admin"], "password": world.secret},
                             headers={"Origin": "https://evil.example"})
    assert cross_login.status_code == 403
    cross_logout = await call("POST", "/api/auth/logout", token, headers={"Origin": "https://evil.example"})
    assert cross_logout.status_code == 403
    assert (await call("GET", PROTECTED, token)).status_code == 200


@db_only
@pytest.mark.asyncio
async def test_failed_logins_are_rate_limited(world: World, wired, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_login_max_failures_per_email", 3)
    for _ in range(3):
        assert (await login(world, "ch_staff", password="wrong-password-xx")).status_code == 401
    limited = await login(world, "ch_staff")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    login_rate_limit.failures.clear()
    monkeypatch.setattr(settings, "auth_login_max_failures_per_ip", 2)
    for key in ("inactive", "no_password"):
        await login(world, key, password="wrong-password-xx")
    assert (await login(world, "ch_admin")).status_code == 429


@db_only
@pytest.mark.asyncio
async def test_session_endpoint_reports_state_without_secrets(world: World, wired) -> None:
    anonymous = await call("GET", "/api/auth/session")
    assert anonymous.status_code == 200
    assert anonymous.json()["auth_enforced"] is True and anonymous.json()["authenticated"] is False
    token, _ = session_cookie(await login(world, "ch_admin"))
    signed_in = (await call("GET", "/api/auth/session", token)).json()
    assert signed_in["authenticated"] is True and signed_in["user"]["email"] == world.emails["ch_admin"]
    assert "password_hash" not in str(signed_in) and token not in str(signed_in)
    stale = await call("GET", "/api/auth/session", "garbage")
    assert stale.json()["session_expired"] is True
    assert any(h.startswith(f"{SESSION_COOKIE}=") and "max-age=0" in h.lower()
               for h in stale.headers.get_list("set-cookie"))


# ── X-API-Key machine routes and public routes under AUTH_ENFORCED=true ──────

EXTENSION_ROUTES = [
    ("POST", "/api/v1/ingest"),
    ("POST", "/api/v1/change-orders/extract"),
    ("GET", "/api/financing/funds-notices/extension/properties"),
    ("POST", "/api/financing/funds-notices/intake"),
    ("GET", "/api/presales/extension/lots"),
]


@db_only
@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", EXTENSION_ROUTES)
async def test_api_key_routes_work_when_enforced(world: World, wired, method: str, path: str) -> None:
    missing = await call(method, path)
    assert missing.status_code == 401
    wrong = await call(method, path, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401
    keyed = await call(method, path, headers={"X-API-Key": API_KEY}, **({"json": {}} if method == "POST" else {}))
    # Past auth: either the route ran (200) or rejected the empty body (400/422). Never a sign-in 401/403.
    assert keyed.status_code not in {401, 403}, keyed.text


@db_only
@pytest.mark.asyncio
async def test_api_key_does_not_unlock_staff_routes(world: World, wired) -> None:
    for method, path in (("GET", PROTECTED), ("GET", "/api/rentals/leases/units/1"),
                         ("GET", "/api/financing/funds-notices"), ("GET", "/api/maintenance/tickets"),
                         # What the Next change-orders proxy sends for an anonymous browser:
                         ("GET", "/api/v1/change-orders"), ("POST", "/api/v1/change-orders/draft")):
        response = await call(method, path, headers={"X-API-Key": API_KEY})
        assert response.status_code == 401, (path, response.status_code)


@db_only
@pytest.mark.asyncio
async def test_proxied_change_orders_need_the_forwarded_session(world: World, wired) -> None:
    token, _ = session_cookie(await login(world, "ch_admin"))
    response = await call("GET", "/api/v1/change-orders", token, headers={"X-API-Key": API_KEY})
    assert response.status_code == 200, response.text


@db_only
@pytest.mark.asyncio
async def test_public_work_order_link_needs_no_login(world: World, wired) -> None:
    response = await call("GET", "/api/public/work-orders/not-a-real-token")
    assert response.status_code not in {401, 403}, response.text
