# Phase 7 staging and worker readiness

Before production rollout, complete the [maintenance production go-live checklist](production-go-live-checklist.md).

Date: 2026-10-06  
Server: `officehub-MS-7D77`  
Branch: `feature/maintenance-ticketing`

## Production worker inventory

Before this work, both `systemctl status officehub-worker` and `systemctl status officehub-beat` returned `Unit ... could not be found`. The installed production application units were `officehub-backend.service` and `officehub-frontend.service`; the Cloudflare tunnel was also active. Production unit definitions are now versioned under `deploy/`, but installing them into `/etc/systemd/system` requires interactive sudo on this server. They were not installed or started during staging setup, and no production service or production database was changed.

Workers and beat are separate services. Workers do not use `-B`. Each environment has exactly one named beat unit, a unique pidfile, and a unique schedule-state path. Systemd therefore owns one scheduler process per environment and refuses a second instance with the same pidfile.

`deploy.sh` restarts and checks `officehub-worker` and `officehub-beat` in addition to the API/frontend. It allows up to 75 seconds for the first one-minute emergency scan to write its heartbeat before declaring backend health failure.

## Scheduler resilience

The emergency task writes its last successful scan timestamp to Redis. Production and staging use different Redis database indexes. `/health` returns HTTP 503 when the timestamp is absent, invalid, unavailable, or older than five minutes.

The API process runs an independent one-minute monitor. When the heartbeat is stale, it posts directly to the configured emergency Slack destination rather than enqueueing through the Celery worker. A Redis `SET NX` lock limits successful alerts to one per 30 minutes. If Slack delivery fails, the lock is released so the next API check can retry.

After an outage, escalation stage is calculated from the ticket creation time. Only the currently due stage is paged. Missing earlier stages are appended to `maint_events` as `emergency_paged` records with `skipped: true` and `caught_up_to`, preserving an honest timeline without burst-paging every stage.

Celery workers set `DATABASE_NULL_POOL=true`. This prevents asyncpg connections created under one task's `asyncio.run()` loop from being reused under a later loop. The staging live run exposed and verified this requirement.

## Staging instance

- Local frontend: `http://127.0.0.1:3001`
- Local API: `http://127.0.0.1:8001`
- Intended public URL: `https://officehub-staging.n10z.ca`
- Database: `officehub_staging`, using the non-superuser runtime role `officehub_staging`
- Redis: database index `1`
- MinIO: bucket `officehub-staging`, with a bucket-scoped credential that cannot access the production `documents` bucket
- Environment file: `/home/officehub/office-hub-maint/.env.staging` (mode 0600, ignored by Git)

The October 6 cluster backup was restored by selecting only the production `officehub` database section. Alembic advanced the restored data from `20260917_0045` to `20261005_0050`. All migrations completed. The maintenance phone backfill normalized 32 tenants and reported one pre-existing invalid phone for tenant ID 7.

The staging runtime role has DML access to the restored staging schemas but cannot read production `core` tables. Migration commands remain an explicit administrative operation and are not run by the application services.

Interactive sudo was unavailable, so staging currently runs as enabled user services under the already-lingering `officehub` user manager. Equivalent system-level staging units are committed under `deploy/` for later installation.

## Staging outbound safety

Every SMS provider calls `enforce_staging_sms_recipient()` before authentication or network I/O. In `ENVIRONMENT=staging`, any number absent from `STAGING_SMS_ALLOWLIST` raises `StagingSmsRecipientBlocked`; the sender marks the persisted message `cancelled` with `staging_recipient_blocked`, writes an `sms_staging_dropped` event, and never obtains a provider ID.

Every Slack post passes through `HttpSlackClient.post_message()`. In staging it rejects any destination other than `STAGING_SLACK_CHANNEL_ID`. Both ticket and emergency destinations resolve to that one channel, and staging suppresses emergency DMs.

The live worker was tested with a reserved non-allowlisted number. The row ended as `cancelled | staging_recipient_blocked` with an empty provider ID.

## Manual external setup

The server has only a remotely managed Cloudflare tunnel run token. It has no origin certificate or account API token, so it cannot create DNS/public-hostname or Access policy changes locally. In Cloudflare Zero Trust:

1. Add public hostname `officehub-staging.n10z.ca` to the existing tunnel, targeting `http://localhost:3001`.
2. Create/copy the production Access application and policies for that hostname.
3. If RingCentral webhooks will be tested, add a narrowly scoped Access bypass for `/api/webhooks/ringcentral/sms` (or use a separate webhook hostname). RingCentral must receive HTTP 200 and the echoed validation token within three seconds and cannot complete an interactive Access login.

Set `STAGING_SLACK_CHANNEL_ID` to the dedicated test channel ID. Set `STAGING_SMS_ALLOWLIST` to comma-separated E.164 test numbers only. Restart the four staging services after either change.

The designated production RingCentral SMS sending number is `+12042598093`. Staging uses this sender during the approved phone-flow test; `PRIVI_EMERGENCY_PHONE` remains a separate tenant-facing voice-line decision.

Once the public hostname and webhook bypass exist, create the RingCentral subscription explicitly with:

```sh
cd /home/officehub/office-hub-maint/backend
set -a
source ../.env.staging
set +a
.venv/bin/python scripts/create_ringcentral_sms_subscription.py
```

This creates an additional instant-SMS event subscription for the authenticated extension; it does not move the phone number or stop RingCentral clients from receiving messages. Any other active subscription may also receive the same event, so using the production number can cause both production and staging to ingest the same inbound text. Prefer a dedicated staging number/extension. With a shared number, keep the staging allowlist narrow: non-allowlisted inbound messages can still be recorded in staging, but all attempted staging replies are dropped.
