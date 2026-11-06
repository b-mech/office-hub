# Office Hub sign-in (password + HttpOnly session cookie)

Branch `feature/workspace-login`, stacked on `feature/lease-tenant-integration`
(migration `20261106_0058` follows `0057`). `AUTH_ENFORCED` stays **false** by
default; nothing here turns enforcement on.

## What existed before

* `app/core/auth.py`: python-jose HS256 JWTs signed with `SECRET_KEY`
  (`access` 15 min bearer, `refresh` 14 days, `oauth_state`).
* `app/routers/auth.py`: Google OAuth only (`GET /api/auth/login` → Google →
  `/api/auth/callback` sets the HttpOnly `office_hub_refresh` cookie). Production
  has no `GOOGLE_AUTH_CLIENT_ID`, so nobody can actually sign in today.
* `AuthenticationMiddleware`: bearer tokens everywhere; the refresh cookie only
  on lease + tenant-aware routes; with `AUTH_ENFORCED=false` every request
  without a credential runs as the fallback actor (oldest active admin of the
  default org, pinned to that org).
* `core.users` had no password column. The frontend sent no credentials.

## What this adds

Backend
* `core.users.password_hash` (bcrypt `$2b$`, cost 12, via the maintained
  `bcrypt` package — passlib 1.7.4 is incompatible with bcrypt 5), plus
  `password_changed_at` and `session_version`.
* `POST /api/auth/login` `{email, password}` → sets `office_hub_session`
  (HttpOnly, `SameSite=Lax`, `Path=/`, `Secure` from `AUTH_COOKIE_SECURE`,
  lifetime `AUTH_SESSION_HOURS`, default 12). The body carries user + real
  memberships, never a token. Errors are a generic 401 *Invalid email or
  password* (unknown, wrong, inactive, and no-password users all look the same,
  with a dummy bcrypt check for unknown users); users with no org membership get
  403. Failed attempts are limited per client IP (20 / 15 min) and per email
  (10 / 15 min) in-process (single uvicorn worker) → 429 + `Retry-After`.
* `GET /api/auth/session` (public, no secrets): `auth_enforced`,
  `authenticated`, `session_expired`, user, memberships, expiry. A stale cookie
  is reported and cleared.
* `POST /api/auth/logout`: clears the cookies and bumps `session_version`,
  revoking **all** of that user's sessions server-side.
* `GET /api/auth/me` now returns 401 instead of a 500 when anonymous.
* Middleware: the session cookie authenticates every `/api` route (the legacy
  refresh cookie still works where it did). Cookie-authenticated writes need an
  `Origin` (or `Referer`) matching `PUBLIC_SITE_URL`, `CORS_ORIGINS`, the Host,
  or `X-Forwarded-Host` (CSRF), else 403; login/logout reject foreign origins
  too. Bearer tokens are unchanged. A credential that is present but invalid,
  expired, revoked (`sv` mismatch), or belongs to an inactive user is **always
  401 and never falls back** to the legacy actor, in either mode. 401 = not
  signed in; 403 = signed in but not allowed (readonly write, other tenant,
  legacy module, origin).
* `scripts/set_user_password.py`: interactive (getpass) set/clear; stores only
  the hash and revokes existing sessions.

Frontend
* `/login` page (email + password, `next` restricted to same-site relative
  paths, notices for expired / signed-out, *Continue without signing in* only
  when the backend reports `auth_enforced=false`).
* `AuthGate` in the root layout asks `/api/auth/session` once: enforced +
  anonymous → `/login?next=…`; expired session → `/login?reason=expired`;
  otherwise renders the shell. Public pages (`/login`, `/auth/callback`,
  `/r/<token>`, `/rentals/reports/<token>`) render without the gate or shell.
* `installAuthFetch` wraps `window.fetch` once: calls to the backend (the
  `/backend-api` proxy, an absolute `NEXT_PUBLIC_API_URL`, or same-origin Next
  `/api/*` routes) get `credentials: "include"`, and a 401 outside the auth and
  public endpoints sends the user to `/login` once. Existing API helpers are
  untouched. Nothing is stored in localStorage/sessionStorage except the
  existing org selector.
* Sidebar + mobile menu: *Sign out* when signed in; *Sign in* when the install
  is not enforced and the user is on the fallback actor.
* The server-side change-orders proxy (`/api/change-orders/*`) now forwards
  the browser's cookie, Origin/Referer, org selector, and host so it keeps
  working once enforcement is on.

## One-time rollout before `AUTH_ENFORCED=true`

1. Land PR #2 (integration) and this PR; deploy with `AUTH_ENFORCED=false`.
   Run `alembic upgrade head` (0055 → 0058) as part of that deploy after a backup.
2. Confirm `AUTH_COOKIE_SECURE=true` (already set) and `SECRET_KEY` is long and
   random (rotating it signs everyone out). `PUBLIC_SITE_URL` defaults to
   `https://officehub.n10z.ca`; add any other browser origin to `CORS_ORIGINS`.
3. For each person who will sign in, on the server, have them type their own
   password: `cd backend && .venv/bin/python -m scripts.set_user_password --email <their email>`.
   Their user must be active and hold a `core.user_org_memberships` row
   (superadmins excepted). Do not create new admin accounts for this.
4. QA (trial or prod in non-enforced mode): sign in through the Cloudflare URL,
   check the cookie is `HttpOnly; Secure; SameSite=Lax` and passes the Next
   rewrite, save something (Origin check through the proxy), open a change
   order (server proxy), sign out, and confirm the old cookie no longer works.
5. **Blocker to resolve first:** Chrome-extension routes that authenticate only
   with `X-API-Key` (`/api/v1/ingest`, `/api/v1/change-orders/extract`,
   `/api/financing/funds-notices/intake`,
   `/api/financing/funds-notices/extension/properties`) are not public paths,
   so the middleware would 401 them under enforcement (pre-existing gap).
6. Set `AUTH_ENFORCED=true`, restart the backend, verify anonymous `/api/*` is
   401, `/health` 200, and sign-in works. Rollback: set it back to `false` and
   restart; no schema change is needed to roll back.

Cloudflare Access (if used) is a separate perimeter in front of the site and
is not an Office Hub session.

## Tests

* `backend/tests/test_password_login.py` (needs `OFFICEHUB_INTEGRATION_DB`
  pointing at a migrated `*test*` database).
* `frontend/tests/auth-paths.test.mjs` — `npm test` (redirect safety, public
  pages, API detection).
