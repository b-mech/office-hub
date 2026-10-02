# PRIVI maintenance prerequisites audit

Audited on 2026-10-01 against the working tree on `officehub-MS-7D77`.

## Existing names and patterns

- Rentals data is in the public schema with integer primary keys: `rental_properties`, `rental_units`, `rental_leases`, `rental_tenants`, `rental_lease_tenants`, and `rental_inspections`. The maintenance foreign keys use these real names and types; no parallel property/unit/lease tables are introduced.
- Office Hub staff are `core.users` with UUID primary keys. Maintenance adds `slack_user_id` and `phone_e164` there.
- Permissions are stored in `core.users.permissions` as a flat JSON object using `none`, `viewer`, and `editor`, not in normalized role/action tables. The frontend currently has seven domains (`lots`, `costbook`, `change_orders`, `reports`, `documents`, `presales`, and `settings`), rather than the stated six. Maintenance is added as an eighth domain and supports optional action keys such as `maintenance.triage`; administrators retain an implicit full grant.
- Celery and Redis already exist in `app.workers.celery_app`. Maintenance must extend that worker rather than add arq. No Celery systemd unit was installed at audit time; a unit template is in `ops/systemd/officehub-worker.service`.
- Box integration is synchronous and service-based in `app.services.box`. Maintenance filing should call that service from Celery in Phase 10.
- Claude is wrapped by `app.services.extraction.claude_provider.ClaudeProvider`, with its model selection centralized there. Maintenance triage must reuse it.
- MinIO uses the `documents` bucket and S3 path-style access. Maintenance objects use the `maintenance/{ticket_id}/...` prefix in that bucket.

## Schema adaptations

- The spec's illustrative `properties`, `units`, and `leases` UUID foreign keys are integer foreign keys to the real `rental_*` tables.
- `inspection_id` is an integer foreign key to `rental_inspections.id`.
- Monetary work-order columns use `NUMERIC(15,2)`, following the repository-wide money rule, rather than the illustrative `NUMERIC(10,2)`.
- Tenant opt-out state belongs on `rental_tenants`, the contact table populated by the lease importer.
- Existing tenant phones are normalized in the migration with `phonenumbers` and the `CA` default region. Migration output reports normalized and failed counts and lists only failed tenant IDs.

## Public exposure

The Cloudflare service runs with a dashboard-managed tunnel token (`/etc/cloudflared/token`), so ingress path rules are not available in the repository or local config. The production deploy script tests `https://officehub.n10z.ca` as a public site and the tunnel fronts the full Next.js application today. API authentication is enforced separately by FastAPI middleware, with explicit public-path exceptions.

Before public intake goes live, confirm in the Cloudflare dashboard whether a dedicated Connect Properties hostname will expose only `/r/*`, `/w/*`, `/api/public/*`, and `/api/webhooks/twilio/*`. `PUBLIC_BASE_URL` remains blank because the permanent printed-card domain is an open business decision.

## Not yet safe to enable

- Do not install or start `officehub-slack.service` until the Phase 7 module and Slack credentials exist.
- Do not enable Twilio sending until the account owner, billing entity, local number, and webhook URLs are confirmed.
- `ENTRY_NOTICE_MIN_HOURS`, `ENTRY_WINDOW_START`, and `ENTRY_WINDOW_END` are configuration defaults only. Manitoba entry rules still require a current legal review before go-live.
- `PRIVI_EMERGENCY_PHONE` remains blank pending confirmation. The Manitoba Hydro gas emergency number must be verified from an authoritative current source during the public-intake phase.
- The on-call rotation, pilot property, vendor-payment handling, accounting integration, and permanent public domain remain open with Nicholas.
