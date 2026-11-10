# Maintenance UX P0 — development only

Base: `c26e803` (maintenance-ticketing, including the persistent RingCentral alert fix).
Develop in `/home/officehub/office-hub-maint-ux`, branch `feature/maintenance-ux`.
Do not deploy/restart services or migrate a shared DB without Nicholas's approval.
The live maintenance checkout has an unrelated seed-phone-test edit; preserve it.

## Schema

No new migration: `maint_vendors` already contains trades, insurance/WCB dates,
notes and active state plus partial unique index `uq_maint_vendors_active_phone`.
`maint_work_orders` already has token hash and expiry. No shared DB was migrated.

## Staff intake

- UI: `/rentals/maintenance/new`, linked by **New ticket** from the queue.
- `GET /api/maintenance/create-options`: property/unit search options, triage permission.
- `POST /api/maintenance/tickets`: multipart `data` containing JSON
  `{property_id,unit_id?,title,description,category,priority,is_emergency?,reporter_name?,reporter_phone?,sms_opt_in?,entry_permission,entry_notes?}`;
  optional repeated `photos` files (10 total, 10 MB each, image validation/EXIF stripping).
- Returns `{id,number,status,sla_due_at,needs_reply:false,confirmation}`.
  Confirmation values: not_requested/no_phone/blocked_staging/blocked_opt_out/queued.
- Source is always staff. Web created event records explicit confirmation consent.
  Staff classification triages the ticket and starts SLA. Emergency marking does
  NOT acknowledge an emergency. Phone consent does not override existing STOP.
  Staging allowlist is checked before queueing, in addition to provider guards.
- No new inbound message is fabricated for staff intake. Existing needs-reply
  calculation remains latest external message direction.

## Vendor capabilities

- UI: `/w/[token]`; invalid/expired/revoked links render a 404. `/r/` and `/w/`
  use public chrome and never require a staff login. The existing `/api/public/`
  authentication exception covers the API; no broad auth bypass was added.
- Runtime `BACKEND_INTERNAL_URL` must target the intended backend, as for Next
  rewrites (default localhost:8000). This is also used for SSR link validation.
- `GET /api/public/work-orders/{token}`: deliberately restricted work-order view.
  No tenant contact fields or private event payloads. Phone-like free text is
  redacted. Only vendor-owned photos are visible; no original filenames leak.
- `POST .../{token}/actions`: JSON `{action,notes?,start?,end?}`.
  Actions accept/decline/propose_schedule/confirm_schedule/start/complete.
  Decline and complete require notes; proposals require timezone-aware times.
- Vendor proposals do NOT schedule visits or send entry notices. They must obey
  the routine notice window; staff coordinates documented lawful exemptions in
  the existing schedule workflow. Vendors confirm only an existing staff slot,
  start only inside that slot and after staff emergency acknowledgement, and
  complete only in-progress work. Only staff resolves the ticket.
- Every action records an inbound web MaintEvent (actor vendor), preserving the
  existing needs-reply queue. Row locks serialize work-order/ticket writes.
- `POST .../{token}/photos`: repeated image files, up to 10 total per work order.
  `GET .../{token}/photos/{id}` checks the live capability and ownership again.
- Token lifetime is 30 days, including rotations. Legacy null expiry falls back
  to created_at + 30 days. Decline revokes the link; inactive vendors are denied.
- `POST /api/maintenance/work-orders/{id}/revoke-link`: staff assign permission.
- Public APIs are rate-limited and use private/no-store, no-referrer headers.

## Vendor admin

- UI `/rentals/maintenance/vendors`, linked from the queue.
- `GET /api/maintenance/vendors?include_inactive=false` defaults to active only.
- `POST /api/maintenance/vendors`: name, phone_e164, trades, insurance_expiry,
  wcb_expiry, notes, is_active. `PATCH /api/maintenance/vendors/{id}` is partial.
- All require manage_vendors permission. Phones normalize to E.164. Duplicate
  active phone is HTTP 409, including unique-index races and reactivation.
- Deactivation hides assignment options and revokes outstanding capability links
  with an audit event, so reactivation cannot resurrect old links. No text is
  sent by creating/editing a vendor.

## Safe verification

Backend runner blocks TCP, uses dummy settings/temp HOME, and eagerly executes
Celery only in tests. New tests replace all notification/media boundaries.

```sh
PYTHONPATH=/tmp/officehub-ringcentral-test-deps \
 /home/officehub/office-hub-maint/backend/.venv/bin/python \
 ops/staging-ringcentral/run_backend_tests.py tests -q
cd frontend
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

Build only in an env-free isolated copy with its own `.next`, dummy backend URL,
telemetry disabled and the no-network preload. Never build the live staging
frontend to test this branch. No live SMS/Slack/mail/DocuSign is needed for tests.

Before any staging rollout: obtain Nicholas's approval, choose vendor seed data,
confirm the allowlisted test recipients and approve any real test texts. Tests
with fake sessions do not replace a fresh trial-DB/browser acceptance pass.

## External access prerequisite (not applied)

An application-level public route does not bypass Cloudflare Access. Before
rollout, check anonymous access to `/w/*` and the public work-order API through
its actual frontend proxy path (`/backend-api/api/public/work-orders/*`, or
`/api/public/work-orders/*` when using the existing direct public rewrite).
They need the same narrowly scoped public-access treatment as `/r/*` and its
intake API. Keep all staff `/api/maintenance/*` and admin pages protected. No
Cloudflare/tunnel settings were changed during this development task.

The isolated Next build exposed two pre-existing invalid named Page exports.
Reusable ChangeOrderForm and LotWorkspace were moved into components without
behavior changes, keeping their Page entry points export-compatible with Next.

Vendor admin exposes SMS opt-out read-only. Replacement records inherit a prior
STOP for the same phone, including inactive records. An opted-out vendor's phone
cannot be overwritten (deactivate/create instead), preserving the old contact's
opt-out history. Admin cannot clear opt-out; only the existing SMS START flow can.
