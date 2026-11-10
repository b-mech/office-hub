# Maintenance Phase 7 verification

Date: 2026-10-05

## Outcome

Office Hub is now the maintenance conversation workspace. Slack is outbound notification-only; it does not accept maintenance replies, actions, modals, slash commands, or Socket Mode events.

The superseded interactive Slack implementation was preserved before the direction change:

- branch: `archive/phase7-slack-relay`
- commit: `b54d7a2` (`Archive interactive maintenance Slack relay`)
- remote: `origin/archive/phase7-slack-relay`

Implementation continued on `feature/maintenance-ticketing` in `/home/officehub/office-hub-maint`. Backend commands used only `/home/officehub/office-hub-maint/backend/.venv`. No command used the `/home/officehub/office-hub` worktree.

## Slack notification design

The transactional `maint_slack_outbox` remains the only Slack delivery boundary. Enqueueing occurs in the same database transaction as the maintenance change. Stable idempotency keys protect ticket creation, ten-minute reply buckets, one-time SLA warning/breach events, emergency escalation stages, and the date-keyed morning digest. Workers claim due records with row locking, retry transient failures with capped exponential backoff, honor Slack `Retry-After` on HTTP 429, and retain a terminal non-sensitive error code after the retry limit.

Notifications contain only:

- ticket number;
- property/unit label;
- category;
- priority;
- Office Hub ticket link; and
- applicable staff `@` mentions.

They do not contain tenant/vendor names, phone numbers, descriptions, note bodies, or SMS text. Slack link and media unfurling are disabled. Ticket creation, tenant/vendor reply, SLA warning, SLA breach, and morning digest notifications go to the configured `#privi-tickets` channel ID. Reply notifications use one idempotency bucket per ticket per ten minutes. Assigned staff are mentioned, with `core.users.slack_user_id` reused when present and populated through `users.lookupByEmail` otherwise.

Emergency stages notify the configured `#privi-emergency` channel, mention the current on-call target, and open a Slack DM to that target. The same stage sends an SMS page containing the Office Hub link and `Reply ACK`. An inbound SMS whose normalized sender matches an active staff user's phone acknowledges the newest unacknowledged emergency only when that staff member is currently on call or is an admin. If no acknowledgement arrives after `MAINT_EMERGENCY_ACK_MINUTES`, the backup is paged; after one further interval (two intervals from the original page), admins are paged. Office Hub acknowledgement uses the same idempotent domain service.

There is no operational reason to retain a Slack Acknowledge button: both supported acknowledgement paths identify a staff user, run the same domain guard, and preserve the audit event without reintroducing interactive Slack state. The Socket Mode service file and relay/card persistence were removed. Migration `20261005_0050` keeps the notification outbox and `users.slack_user_id`, while dropping `maint_slack_cards` and inbound relay identity columns.

### Final Slack OAuth scopes

The final bot-token scope set is:

- `chat:write` — post channel and DM notifications;
- `im:write` — open the on-call DM conversation;
- `users:read` and `users:read.email` — resolve and auto-link assignees by their Office Hub email;
- `channels:read` — validate/discover the public `#privi-tickets` and `#privi-emergency` channel IDs; and
- `groups:read` — the corresponding lookup if either notification channel is private.

No app-level token is needed. Remove `connections:write`, `commands`, message-history scopes, reaction scopes, file scopes, and all interactivity/event subscriptions from the maintenance Slack app.

## Office Hub ticket workspace

The Rentals navigation now includes `/rentals/maintenance` and a mobile-friendly open-ticket queue. Filters cover status, priority, needs-reply, and terminal tickets. Each row shows its SLA state and whether the latest external message is an unanswered inbound message.

The ticket page provides:

- a texting-style chronological timeline for messages, internal notes, attachments, state changes, scheduling, and work-order events;
- tenant, vendor, and internal-note composer modes;
- vendor selection through vendor work orders only (staff work orders have no external party);
- image attachments and the existing media validation/storage path;
- visible held-message countdown and Cancel during the 30-second hold;
- UI message states normalized to `held`, `sent`, `failed`, or `cancelled`—a provider's `delivered` state is deliberately displayed as `sent`;
- triage, staff/vendor assignment, scheduling through the entry-notice policy, emergency acknowledgement, resolution, cancellation, duplicate, chargeback, and admin reopen flows; and
- work-order completion that returns `all_work_orders_complete` and prompts `Mark resolved` without changing ticket status automatically.

Resolved tickets remain messageable. Closed, cancelled, and duplicate tickets block external messages and internal notes until an admin reopens them. Admin reopen applies to every terminal state and clears a stale duplicate link when applicable.

## Verification results

All automated tests used fakes or an isolated test database. No Slack API, SMS provider, production database, production MinIO, deployment command, or service restart was invoked.

- Full backend suite with `SMS_PROVIDER=fake`: **192 passed**, with six existing Pydantic v2 deprecation warnings.
- Focused maintenance suite: **101 passed**.
- Python compilation: passed.
- Alembic head: `20261005_0050`.
- Phase 7 offline SQL generation (`0049 → 0050`): passed. Repository-wide offline generation still stops in the older data migration `20260805_0025` because offline execution does not provide `rowcount`; this is unrelated to Phase 7.
- Frontend ESLint: **0 errors**, with two pre-existing `no-img-element` warnings in inspection/report pages.
- Frontend TypeScript: passed.
- Next.js production build and client-API URL check: passed, including `/rentals/maintenance` and `/rentals/maintenance/[ticketId]`.

### Isolated database migration test

PostgreSQL 16 ran in a disposable container with its data directory on tmpfs. The existing pre-maintenance test dump `/home/officehub/officehub-before-0035.dump` was restored into `officehub_phase7_verify`. The dump emitted its known PostgreSQL-version warning for unsupported `transaction_timeout`; the restore otherwise completed.

Repository migrations upgraded the restored copy from `20260811_0034` through `20261005_0050`. Phase 7 was then downgraded to `20261002_0049` and reapplied successfully. Final checks confirmed:

- Alembic version `20261005_0050`;
- `maint_slack_outbox` exists;
- `maint_slack_cards` does not exist;
- `maint_sms_messages` has no Slack relay columns; and
- `core.users.slack_user_id` still exists.

The test container was stopped and removed after verification, so the test database is not retained.

## Staging-database proposal for live integration testing

1. Restore a newly sanitized production backup into an isolated database named `officehub_maint_phase7_staging_<date>`. Give the staging backend a dedicated role that cannot connect to the production database, and block production database routing at the network layer.
2. Run the complete Alembic chain, the Phase 7 downgrade/re-upgrade check, schema assertions, and a phone-backfill report. Replace tenant/vendor contact values with reserved test numbers and seed named staff/on-call users with test-only email and phone identities.
3. Point the staging backend at a separate MinIO bucket/prefix, Redis database, and Celery queue. Start with `SMS_PROVIDER=fake` and a recording fake Slack client; verify the outbox payload allowlist and ten-minute reply coalescing from recorded calls.
4. Exercise the Office Hub scenarios: tenant and vendor inbound replies, held/cancelled/failed messages, attachments, needs-reply clearing, each SLA state, entry-notice rejection and admin override, resolved messaging, terminal blocking/admin reopen, staff work orders, and the all-work-orders-complete prompt.
5. After recorded-call approval, use dedicated Slack channels (for example `#privi-tickets-staging` and `#privi-emergency-staging`) and an app installation limited to the final scopes above. Use only approved staging SMS numbers and explicitly allowlisted staff phones for ACK tests.
6. Run the emergency clock with a shortened staging interval and verify primary, backup, and admin stages; acknowledge once through Office Hub and once through SMS. Confirm later stages cease after acknowledgement and that Slack contains none of the prohibited fields.
7. Export an evidence bundle containing test IDs, redacted outbox rows, event timelines, worker results, and screenshots. Delete the staging database and object-store artifacts under an agreed retention policy. Promotion to production should require a separate approval, configuration review, migration backup, and rollback plan.

## Logical commits

- `782bebc` — Replace Slack relay with outbound maintenance alerts.
- `6db048a` — Add Office Hub maintenance ticket workspace API.
- `266337b` — Add mobile maintenance ticket workspace.

This report and final cleanup are committed separately after the verification results are recorded.
