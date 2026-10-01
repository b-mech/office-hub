# Maintenance Phases 4 and 6 verification

Date: 2026-10-01

## Outcome

Phase 4 tenant intake and the Phase 6 SMS layer are implemented on the existing maintenance worktree. `PUBLIC_BASE_URL` remains blank; no production hostname was guessed, nothing was deployed, no worker was installed or started, and the live database was not migrated. No file under `ops/` was changed for this work.

The checked-out Git branch is `feature/docusign`, and neither local nor remote branch listings contain a name matching `maintenance` or `ticket`. Because the worktree already contained the uncommitted Phase 1–3 maintenance implementation plus unrelated user changes, it was not safe to switch or create a branch implicitly. This work therefore continued in that existing worktree and leaves branch organization for the owner.

Celery is not new to Office Hub. The repository already had `app.workers.celery_app` and scheduled/background work (including QBO reconciliation) before maintenance. Maintenance extends that existing Celery app with the five-second due-SMS task. Test sessions force Celery eager mode in `backend/tests/conftest.py`.

## Blank-configuration startup

All maintenance environment variables were explicitly set to empty strings while the rest of the backend's required base configuration remained present.

- Uvicorn completed application startup.
- The startup log was: `PRIVI maintenance disabled: PUBLIC_BASE_URL is not configured`.
- `GET /health` returned HTTP 200 with `{"status":"ok","environment":"development","version":"0.1.0"}`.
- `GET /api/public/maintenance/config` returned HTTP 200 with `enabled=false` and the default public brand `Connect Properties`.
- Empty environment values now use typed defaults instead of causing Pydantic integer/time parse failures.
- In production, the feature gate additionally requires Turnstile, the public emergency phone, and complete configuration for the selected SMS provider. Development/test uses Cloudflare's official always-pass test keys and can fall back to a fake SMS provider.

## Implemented

### Tenant links and QR cards

- Active unit tokens are generated from 32 random bytes, persisted only as SHA-256 hashes, compared with `hmac.compare_digest`, and rotated under a row lock.
- The unit Maintenance QR panel shows active/recommended-rotation state and supports Generate/Rotate, a single printable PDF, and a property-wide multi-page PDF.
- Printable cards use `PUBLIC_BRAND_NAME`, the property/unit label, configured emergency number, and a QR/link derived only from `PUBLIC_BASE_URL`.
- Raw permanent tokens are returned only during generation. A single PDF therefore uses the just-generated raw token; the bulk operation generates and renders all raw tokens in one transaction without persisting them.
- Lease-import renewal/expiry flags the unit to consider rotating its QR and never rotates automatically.
- Known tenants who text with no open ticket receive a separate, short-lived, hash-only intake token. This avoids attempting to recover a permanent raw QR token from its hash.

### Public intake

- Added the mobile-first `/r/{token}` page with emergency categories first, camera upload, entry permission/notes, Turnstile, and the emergency fork before Submit.
- The gas-smell panel tells the user to leave, call 911 and Manitoba Hydro from outside, then call Connect Properties. Phone values and public-facing branding come from configuration.
- `GET /api/public/intake/{token}` returns only the property display name and unit label. Invalid and revoked links share the same response.
- `POST /api/public/intake/{token}` verifies Turnstile, applies Redis limits of 5/token/hour and 10/IP/hour, normalizes the phone, checks the current lease, creates verified or unverified tickets, validates and stores media, records events, calls the no-op Phase 7 notifier, and queues the confirmation SMS.
- Media is identified by magic bytes. JPEG, PNG, HEIC/HEIF, and WebP are resaved without EXIF; PDFs remain invoice-only. Intake is limited to 5 files and every file to 10 MB.
- Public attachment delivery uses an attachment-scoped, HMAC-signed token with a one-hour expiry.

### SMS

- Added the `SmsProvider` boundary, recording `FakeProvider`, HTTP-based `TwilioProvider`, and JWT-authenticated `RingCentralProvider`. The configured RingCentral server, client, secret, JWT, and sending number are read through typed settings; all RingCentral fields are excluded from settings representations, HTTP client request logging is suppressed, and none of their values are printed or logged. No live authentication or message send was attempted.
- The RingCentral provider reuses short-lived OAuth access tokens and sends SMS through the extension SMS endpoint. Outbound media uses RingCentral's multipart MMS endpoint.
- Twilio webhook signatures are validated in every environment; the fake provider uses the same signature algorithm for tests.
- Every outbound message is persisted first. Staff relays use the configured hold, the first relay in 24 hours gets the configured signature, and automated non-emergency messages defer through quiet hours. Staff relays and emergencies bypass quiet-hour deferral.
- The existing Celery scheduler scans due pending/held rows every five seconds. Failed sends retain a non-sensitive error class and notifier callback.
- Status callbacks normalize Twilio's states to the persisted queued/sent/delivered/failed/cancelled states.
- Inbound SMS/MMS is stored idempotently by provider SID, media is fetched with provider authentication, and routing covers active vendor work orders, tenant open tickets, recently resolved tickets, known tenants without tickets, and unknown numbers.
- Multiple-open-ticket routing records the other ticket numbers. `YES`, `Y`, `FIXED`, and `DONE` close a recently resolved ticket with `tenant_confirmed`; other replies remain relayed for staff review.
- STOP and START are mirrored onto all matching active vendor/tenant records. Automated sends to opted-out recipients are blocked.
- Slack calls go through `MaintenanceNotifier`; its current implementation is intentionally a no-op for Phase 7 to replace.

## Schema and migration verification

Migration `20261001_0047_maintenance_intake_sms.py` chains directly after `0046`. It:

- adds the per-unit QR-rotation recommendation timestamp;
- adds short-lived, hash-only intake tokens; and
- permits an inbound MMS attachment to be temporarily unlinked while an unknown sender is being resolved.

The pre-0035 production-copy backup was restored to a new isolated database named `officehub_maint_p46_verify_20261001`. The backup emitted one client/server compatibility warning for unsupported `transaction_timeout`; restore otherwise completed. Repository migrations then ran to `0047`, downgraded to `0046`, and re-applied `0047` successfully. The live database URL was never used as a migration target.

## Verification results

- Focused maintenance suite: **77 passed**.
- Full backend suite: **163 passed, 1 failed**. The sole failure is the unrelated existing unmarked async test `tests/test_lots_timeline.py::test_timeline_excludes_paid_land_and_sale_deposits`; pytest reports that the async function has no async marker. Maintenance tests are all green.
- SQLAlchemy mapper configuration: passed.
- Python compilation: passed.
- `pip check`: no broken requirements.
- Frontend TypeScript (`npx tsc --noEmit`): passed.
- Focused frontend ESLint: 0 errors, 1 pre-existing `no-img-element` warning in the rental-inspection photo gallery.
- A production frontend build/deploy was not run because it must go through the deployment wrapper that supplies `NEXT_PUBLIC_API_URL`.

The focused suite covers the Phase 4/6 portions of §12: Turnstile rejection, token/IP rate limits, unverified reporters, HEIC conversion, EXIF removal, oversize and file-count rejection, phone normalization, signed media, every inbound-routing branch including multiple open tickets and recent resolution, close keywords, STOP/START, opt-out blocking, quiet-hour deferral, held-to-queued sending, cancellation exclusion, provider signatures, Twilio status normalization, and printable QR generation.

## External facts verified

- Cloudflare's official always-pass Turnstile keys are used only in development/test: <https://developers.cloudflare.com/turnstile/troubleshooting/testing/>.
- Manitoba Hydro currently lists the natural-gas emergency line as **1-888-624-9376** and instructs people who smell gas to leave immediately and call 911 or Manitoba Hydro from a safe place: <https://www.hydro.mb.ca/safety/indoor/natural-gas/>.
- RingCentral JWT credentials are exchanged for a reusable OAuth access token as documented at <https://developers.ringcentral.com/guide/authentication/jwt-flow>, and SMS is sent through RingCentral's documented extension endpoint: <https://developers.ringcentral.com/guide/messaging/sms/sending-sms>.

## Deliberately outstanding

- A real-phone QR/intake/SMS round trip cannot be performed until the permanent `PUBLIC_BASE_URL`, Connect Properties emergency number, and production Turnstile keys are confirmed.
- The RingCentral variables are currently present in `backend/.env`, while the installed backend service and the checked-in worker unit point at the repository-root `.env`; that root file still selects Twilio. In keeping with the instruction that the ops branch owns systemd and that secret values must not be copied or exposed, neither environment file nor any unit was modified here. The ops branch must align the service `EnvironmentFile` or securely place the RingCentral variables in the root environment before RingCentral can be selected by the running services.
- RingCentral inbound SMS requires a RingCentral notification subscription and validation-token-protected webhook (or WebSocket subscription). Those subscription details are not present in configuration, so this change does not pretend the existing Twilio webhook is a RingCentral inbound endpoint.
- Slack card/thread delivery remains the no-op notifier by design until Phase 7.
- SMS template editing in Office Hub remains part of the Phase 9 Maintenance Settings screen; templates are centralized now so that storage-backed overrides can replace them there.
