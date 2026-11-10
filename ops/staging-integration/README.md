# Combined lease + maintenance: controlled staging release runbook

**Approval boundary:** Nicholas authorized the corrected staging-only retry in card t109s458.
Stop and fully roll back on any failure; do not improvise around a new failure class.
Production is excluded. No Cloudflare change, SMS, DocuSign call or extra Slack post
is authorized. Earlier trial results below are historical evidence, not a live-deploy claim.

## Findings and canonical database

HTTP backend/frontend use `office-hub-lease-agreements` at `d8da652`, with
`.env.lease-test` and DB **officehub_lease_agreements_test**, revision **20261102_0055**.
Worker/beat use `office-hub-maint` at `c26e803`, with `.env.staging` and DB
**officehub_staging**, revision **20261009_0051**. These are genuinely different DBs,
not two names for one connection. The lease override changed the HTTP services but
left the maintenance worker on its original staging environment. The worker checkout
also has an unrelated edit to `backend/scripts/seed_maintenance_phone_test.py`; retain it.

| Table/data | HTTP DB before | Worker DB before | Combined trial |
|---|---:|---:|---:|
| lease_agreements | 3 | absent | 3 |
| lease_agreement_events | 12 | absent | 12 |
| lease_agreement_tasks | 1 | absent | 1 |
| rental_properties / rental_units | 1 / 1 | 21 / 27 | 22 / 28 |
| rental_tenants / rental_leases / links | 0 / 0 / 0 | 43 / 24 / 43 | 43 / 24 / 43 |
| inspections / inspection photos | 0 / 0 | 33 / 42 | 33 / 42 |
| inspection reports / items / comments | 0 / 0 / 0 | 25 / 41 / 3 | 25 / 41 / 3 |
| maint_tickets / work_orders | 0 / 0 | 2 / 3 | 2 / 3 |
| maint_events / SMS / attachments | 0 / 0 / 0 | 84 / 45 / 2 | 84 / 45 / 2 |
| intake tokens / unit tokens / on-call | 0 / 0 / 0 | 3 / 0 / 1 | 3 / 0 / 1 |
| maint_vendors | 0 | 0 | 0 |
| maint_slack_outbox | absent | 23 | 23 |

**Recommendation:** retain the current HTTP database as the operational canonical DB,
BUT carry over the worker's real rental/maintenance/inspection history. Pointing workers
to the lease test DB without this import would lose visible history and property context.
The original property belongs to `Lease Agreement Test`, not `PRIVI`; it is intentionally
not coalesced with the similarly addressed PRIVI property. Original lease references stay
unchanged. The two orgs and companies remain separate. Do not silently merge identities.

The databases have no overlapping staff user IDs/emails/org IDs. With explicit
`--import-disabled-actors`, the importer preserved the one historical actor as an
**inactive readonly identity** with no permissions, login binding, phone or Slack ID;
its org is retained. It never grants source privileges. The imported on-call row still
points at that inactive historical identity: **Nicholas must choose/approve the active
staging staff/on-call mapping before operational texting/emergency testing.** This is
not a complete authentication/organization consolidation.

The backend env was also missing worker-side allowlist, emergency-phone, Turnstile and
validation-token keys; sender/relay-hold values differ. `prepare_env.py` builds NEW
protected candidate envs retaining lease/DocuSign/mail configuration, taking maintenance,
Slack/channel guard, Redis and Celery settings from the worker, and giving BOTH processes
the HTTP DB URL. It does not edit any deployed env. Keep `ENVIRONMENT=staging` and the
existing allowlist/channel/outbound-only guards. Never copy a whole worker env over the
lease env. Generate fresh candidates after any credential rotation; do not reuse archived
trial candidate envs.

## Conflict resolution (11 files)

- maintenance router, SMS provider, subscription script and phase4_6 tests: retained the
  newer maintenance/throttling changes while preserving auto-merged lease additions.
- next.config.ts: retained configurable normalized BACKEND_INTERNAL_URL plus all three
  rewrites: /backend-api, /api/webhooks and /api/public.
- lots timeline test: kept lease behaviour and fixed its pre-existing nested asyncio.run
  inside an async test. Auth tests now explicitly enable enforcement; unauthenticated
  staff creation expects middleware 401 (not route-level 403).
- change-order gaps doc, two change-order pages, lots page and projects page: retained
  the lease implementation/layout. Removed the incoming duplicate shared component paths;
  existing `app/change-orders/components/ChangeOrderForm.tsx` and
  `app/lots/components/LotWorkspace.tsx` remain byte-identical to d8da652.
- `services/docusign.py` and `services/lease_docusign.py` are byte-identical to d8da652.

## Migration and tested rollback

Merge **20261110_0062** joins **20261102_0055** and **20261009_0051**. No historical
migration was rewritten. On the HTTP trial, the maintenance 0048-0051 migrations applied
without DDL conflicts. Alembic config now escapes `%` for percent-encoded DB credentials.

A plain `downgrade 20261102_0055` ONLY removes the merge, leaving BOTH heads and the
maintenance tables. The tested **full lease-only rollback is two commands**:

```
alembic downgrade 20261102_0055
alembic downgrade 20261009_0051@20261001_0047
```

The second command selects exactly 0051, 0050, 0049 and 0048, leaving only 0055.
**Never use @base**: that also selects irreversible lease-data corrections. The trial
upgrade -> full downgrade -> upgrade preserved 3/12/1 lease rows and full-row digests.
After re-upgrade, `maint_slack_outbox` and `scheduled_visit_status` both exist.
Downgrade removes outbox/scheduling schema/data: for a real rollback also restore dumps.

## Trial evidence / reproduction

Private trial root: `/home/officehub/maintenance-integration-trials/20261110T105231-0500`.
Source dumps: `backend.dump`, `worker.dump`; copied databases:
- `officehub_staging_trial_20261110_105231`
- `officehub_worker_trial_20261110_105231`

A third NEW restore-probe DB, `officehub_restore_trial_20261110_111953`, also restored
the full post-import dump successfully with 3/12/1 lease rows, 2 tickets, 84 events,
23 outbox rows and head0062. The guarded dump/revision/migration/restore operators were
exercised on trials; none was run against a live target.

No existing trial database was dropped. Full history copy then idempotent rerun inserted
zero rows on rerun. Integer identities/foreign keys are remapped by natural keys; UUID
history identities are retained. Existing canonical rows are not overwritten; STOP consent
can only become stricter. Pending/held outbound SMS is cancelled and undelivered Slack
outbox rows are terminally quarantined. Current source had zero pending/held SMS and zero
pending Slack: its 20 `queued` SMS rows are already submitted history, not dispatchable
(the dispatcher selects only pending/held); 23 outbox rows are 9 delivered + 14 failed.
No worker or beat was started on the copies. External network is blocked in trial apps.

Backend command (dummy configuration, fresh HOME, TCP blocked, Unix sockets allowed):
```
PYTHONPATH=/tmp/officehub-ringcentral-test-deps \
 /home/officehub/office-hub/backend/.venv/bin/python \
 ops/staging-ringcentral/run_backend_tests.py tests -q --tb=short
```
Final full backend result: **394 passed, 2 subtests passed, no skipped tests or failures**;
7 warnings (Pydantic deprecation / pytest-socket import rewriting).
Frontend: `node node_modules/typescript/bin/tsc --noEmit --incremental false` passed.
Isolated production build: **passed (27/27 static pages generated)**;
`next build --webpack` + `scripts/check-client-api-urls.mjs`,
with `NODE_OPTIONS=--require .../build_no_network.cjs`, telemetry disabled. Do NOT build
in any live checkout. Trial ports 8071/3071; runtime guards allow only trial PostgreSQL
and frontend-to-trial-backend respectively. Read-only HTTP smoke passed health, queue,
new-ticket, vendor admin, unit/lease editor and existing three-agreement list; bogus vendor
capabilities return 404. No forms were submitted and no browser actions/send buttons clicked.
Screenshots (visually reviewed): `/workspace/ohqa/maint-trial-maintenance.png`,
`maint-trial-new-ticket.png`, `maint-trial-vendors.png`, `maint-trial-leases.png`.
The queue is correctly empty under the default open-only filter: its two imported tickets
are closed/resolved. The lease screenshot shows the existing agreement editor, not just
the rental unit maintenance tab.

## Proposed real staging deploy — DO NOT RUN UNTIL APPROVED

Use a NEW immutable release worktree and service overrides, rather than editing either
old live checkout. This also leaves the preserved seed-script edit completely untouched.
Allow about **15-30 minutes preparation with no outage; 2-5 minutes downtime**, reserve
15 minutes for verification/rollback. Trial timings are small, not a downtime guarantee.
Resolve the on-call identity decision and credential-rotation concern before deployment.

### 1. Prepare immutable code/dependencies/build (old services still running)

Replace COMBINED_SHA with the reviewed/pushed commit in the handoff, then:
```
PLAN=/home/officehub/office-hub-lease-maint-staging
COMBINED_SHA=<approved-full-sha>
RELEASE=/home/officehub/releases/lease-maint-${COMBINED_SHA:0:12}
RB=/home/officehub/staging-rollbacks/lease-maint-$(date +%Y%m%dT%H%M%S%z)
mkdir -m 700 "$RB"
git -C "$PLAN" worktree add --detach "$RELEASE" "$COMBINED_SHA"
/home/officehub/.pyenv/versions/3.12.11/bin/python -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/pip" install -r "$RELEASE/backend/requirements.txt"
(cd "$RELEASE/frontend" && npm ci)
(cd "$RELEASE/frontend" && NEXT_TELEMETRY_DISABLED=1 \
 BACKEND_INTERNAL_URL=http://127.0.0.1:8001 NEXT_PUBLIC_API_URL=/backend-api \
 NODE_OPTIONS="--require $RELEASE/ops/staging-integration/build_no_network.cjs" \
 node node_modules/next/dist/bin/next build --webpack && node scripts/check-client-api-urls.mjs)
```
Run `"$RELEASE/.venv/bin/python" "$RELEASE/ops/staging-integration/release_checks.py" transport` BEFORE any service stop. It checks reviewed package pins and invokes Kombu's actual Redis version guard without opening a connection.
Run tsc/tests again with isolated test deps as above, and assert generated routes-manifest
contains `/api/webhooks/:path*` -> `http://127.0.0.1:8001/api/webhooks/:path*`. Stop on any
failure; do not migrate/restart. No source maps/envs/secrets should be committed.

### 2. Back up BEFORE service/env/DB changes

```
umask 077
LEASE=/home/officehub/office-hub-lease-agreements
MAINT=/home/officehub/office-hub-maint
PY="$RELEASE/.venv/bin/python"
OPS="$RELEASE/ops/staging-integration"
cp -a "$LEASE/frontend/.next" "$RB/next"
cp -a "$LEASE/.env.lease-test" "$RB/backend.env"
cp -a "$MAINT/.env.staging" "$RB/worker.env"
cp -a "$MAINT/backend/scripts/seed_maintenance_phone_test.py" "$RB/preserved-seed.py"
cp -a "$HOME/.config/systemd/user" "$RB/systemd-user"
for s in backend frontend worker beat; do
 systemctl --user show "officehub-staging-$s.service" -p MainPID -p WorkingDirectory -p EnvironmentFiles >> "$RB/services.txt"
done
git -C "$LEASE" rev-parse HEAD > "$RB/lease.sha"
git -C "$MAINT" rev-parse HEAD > "$RB/worker.sha"
sha256sum "$LEASE/frontend/.next/routes-manifest.json" > "$RB/routes.sha256"
"$PY" "$OPS/db_ops.py" revision --env "$LEASE/.env.lease-test" --expect-db officehub_lease_agreements_test
"$PY" "$OPS/db_ops.py" revision --env "$MAINT/.env.staging" --expect-db officehub_staging
"$PY" "$OPS/db_ops.py" dump --env "$LEASE/.env.lease-test" --expect-db officehub_lease_agreements_test --file "$RB/backend-prestop.dump"
"$PY" "$OPS/db_ops.py" dump --env "$MAINT/.env.staging" --expect-db officehub_staging --file "$RB/worker-prestop.dump"
```
These wrappers execute `docker exec -e PGPASSWORD office-hub-postgres-1 pg_dump ... -Fc`
with password inherited privately, not on argv. Backups never overwrite existing files.
Confirm source revisions still 0055/0051 and expected counts before proceeding.

### 3. Freeze writes, take FINAL dumps, migrate and import

Operational finding from the first real attempt: the combined Settings validator rejects
`$LEASE/.env.lease-test` because its RingCentral webhook validation token is absent.
The worker env has that token. This failed BEFORE Alembic/DDL; import/overrides were not
reached. The canonical DB was restored from its final dump and all original staging units
were restarted; original data digests, health and public validation echo were verified.
The outage/recovery window was 8.32 seconds. Production was untouched.

The corrected order below prepares the merged protected env BEFORE invoking Alembic and
uses it for both migration and import. Read-only validation confirmed that candidate env
passes all Settings guards; the corrected ordering passed migration/import on the second attempt, which then
rolled back because of override precedence and incompatible Kombu dependencies.
Do not remove the token guard or paste token values into commands/logs. The explicit guarded
Webpack build passed; only the original environment ordering blocked migration.

```
systemctl --user stop officehub-staging-beat officehub-staging-worker officehub-staging-backend officehub-staging-frontend
"$PY" "$OPS/db_ops.py" dump --env "$LEASE/.env.lease-test" --expect-db officehub_lease_agreements_test --file "$RB/backend-final.dump"
"$PY" "$OPS/db_ops.py" dump --env "$MAINT/.env.staging" --expect-db officehub_staging --file "$RB/worker-final.dump"
"$PY" "$OPS/prepare_env.py" --lease-env "$LEASE/.env.lease-test" --worker-env "$MAINT/.env.staging" --out-dir "$RB/new-env"
"$PY" "$OPS/db_ops.py" migrate --env "$RB/new-env/backend.env" --expect-db officehub_lease_agreements_test --revision head --allow-live-target
"$PY" "$OPS/copy_worker_history.py" --source-env "$MAINT/.env.staging" --target-env "$RB/new-env/backend.env" --target-db officehub_lease_agreements_test --allow-live-target --import-disabled-actors
```
The worker source DB is READ ONLY and is NOT migrated. Repeat the count/digest checks,
confirm only head0062, and verify no dispatchable imported SMS/pending Slack. No new
operational records are created for verification. Review the disabled on-call identity;
do not activate/copy privileges or grant texting permission as an implicit migration step.

### 4. Point ONLY the four staging units at the release

Create a new `zz-lease-maint.conf` in each staging unit's `.service.d` directory. Do NOT
change base units, production units, Cloudflare, Redis data or either old checkout.
Backend contents (expand $RELEASE and $RB when writing):
```
[Service]
WorkingDirectory=$RELEASE/backend
EnvironmentFile=
EnvironmentFile=$RB/new-env/backend.env
ExecStart=
ExecStart=$RELEASE/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```
Frontend: set WorkingDirectory=$RELEASE/frontend and explicitly set
`Environment=BACKEND_INTERNAL_URL=http://127.0.0.1:8001` for server-rendered vendor pages;
use the generated frontend.env (cloned lease settings with the staging URL pinned) and
existing `/usr/bin/npm start -- --hostname 127.0.0.1 --port 3001` ExecStart.
Worker/beat: WorkingDirectory=$RELEASE/backend; reset EnvironmentFile to
$RB/new-env/worker.env and reset ExecStart to:
```
# worker
$RELEASE/.venv/bin/celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --concurrency=2
# beat (in a unit file, retain these systemd specifiers literally)
$RELEASE/.venv/bin/celery -A app.workers.celery_app:celery_app beat --loglevel=INFO --pidfile=%t/officehub-staging-beat/celerybeat.pid --schedule=%S/officehub-staging/celerybeat-schedule
```
Generate and install these four exact overrides (after approval):
```
"$PY" "$OPS/make_overrides.py" --release "$RELEASE" --env-dir "$RB/new-env" --out-dir "$RB/overrides"
for s in backend frontend worker beat; do
 d="$HOME/.config/systemd/user/officehub-staging-$s.service.d"
 mkdir -p "$d"
 test ! -e "$d/zz-lease-maint.conf" || { echo "Existing override: STOP"; exit 1; }
 install -m 600 "$RB/overrides/$s.conf" "$d/zz-lease-maint.conf"
done
systemctl --user daemon-reload
"$PY" "$OPS/release_checks.py" effective --release "$RELEASE" --env-dir "$RB/new-env"
systemctl --user restart officehub-staging-backend officehub-staging-frontend officehub-staging-worker officehub-staging-beat
```
This restarts ONLY staging backend, frontend, worker,
beat. All code/dependencies now match one release; env values/allowlist/channel guards
are retained privately. No migration runs against officehub_staging or production.

### 5. Verification, without sends

Run `"$PY" "$OPS/release_checks.py" stable --release "$RELEASE" --env-dir "$RB/new-env" --seconds 10` after HTTP readiness. This verifies all four running process cwd values, stable worker/beat PID/invocation/restart counts, and current-invocation worker/beat readiness logs. Abort and roll back on failure.


- GET `http://127.0.0.1:8001/health` ->200; scheduler heartbeats may need their first tick.
- GET `http://127.0.0.1:3001/rentals/maintenance` ->200 and New ticket visible.
- Vendor admin and existing lease editor load; GET
  `/backend-api/api/rentals/leases/units/1` still returns three agreements.
- GET `/w/bogus` and `/api/public/work-orders/bogus` ->404 locally.
- Validation echo (POST, NOT GET; dummy probe string is not a saved token):
  `curl -si -X POST -H 'Validation-Token: staging-route-check' https://officehub-staging.n10z.ca/api/webhooks/ringcentral/sms`
  ->200 and matching header. It does not call RingCentral APIs.
- Check DB name/revision privately for both service configurations; same canonical DB,
  single0062. Recheck source worker DB still0051, unchanged counts.
- Observe next :20 beat logs and existing Redis recovery state; do not manually send a
  renewal/Slack/SMS or clear persistent alert state as part of this plan.
- No ticket/vendor creation, test texts, DocuSign actions or other integration probes.

### 6. Rollback on ANY verification failure

Keep all four staging units stopped during rollback. **Dump restore overwrites all writes
since final backup**; freeze first and explicitly agree how any new records will be retained.
Capture a separate failed-release dump if new writes need investigation. Restore only the
canonical backend DB; original worker DB was not modified by migration/import.

```
"$PY" "$OPS/db_ops.py" migrate --env "$RB/new-env/backend.env" --expect-db officehub_lease_agreements_test --direction downgrade --revision 20261102_0055 --allow-live-target
"$PY" "$OPS/db_ops.py" migrate --env "$RB/new-env/backend.env" --expect-db officehub_lease_agreements_test --direction downgrade --revision 20261009_0051@20261001_0047 --allow-live-target
"$PY" "$OPS/db_ops.py" restore --env "$RB/backend.env" --expect-db officehub_lease_agreements_test --file "$RB/backend-final.dump" --allow-live-target
```
Restore the saved four staging unit/drop-in configurations from `$RB/systemd-user` (do
not blanket-replace unrelated units). Remove only the newly created zz-lease-maint.conf
files, daemon-reload, and restart those four staging units with their old code/envs. Old
checkouts and .next were never changed; the extra .next copy remains available if needed.
Verify backend0055, worker0051, old health/lease API/public validation echo and original
routes hash. Do not drop databases or delete rollback backups. No production operations.

## Remaining approvals / limitations

- Current corrected staging retry is specifically approved; no production operation is approved.
- Staging Turnstile uses Cloudflare official PUBLIC test keys; this is intentional staging
  configuration, not a private-key leak. Reviewed against
  https://developers.cloudflare.com/turnstile/troubleshooting/testing/. Real protection
  would need real keys before a public/non-allowlisted rollout; none were changed.
- Historical staff/on-call identity mapping needs a deliberate decision; no new privileges
  or texts were enabled. Vendor list and specifically approved allowlisted test numbers are needed.
- Public `/w/*` and `/api/public/work-orders/*` Cloudflare Access bypass rules must be
  reviewed/applied separately for vendors; current public `/w/bogus` is Access302. No changes made.
- Existing credential appeared in an earlier migration ConfigParser exception. It is not
  repeated or committed here. Redact that output and rotate the affected credential before
  deployment; diagnostic wrappers now suppress unsafe driver/settings tracebacks.
- Screenshots prove rendering, not real mouse interaction, vendor scheduling, upload or
  actual external delivery. All external integrations stayed blocked during tests/trial use.

## Retry fixes reviewed 2026-11-10

The second real attempt migrated/imported correctly, then rolled back completely.
Its frontend remained on the old build because `lease-test.conf` sorts AFTER the old
`90-lease-maint.conf`. Use `zz-lease-maint.conf` (not a numeric prefix), explicit
frontend ExecStart, and the effective-config gate BEFORE restarting.
Fresh dependencies had Kombu5.7.0 with pinned redis5.2.0, raising VersionMismatch.
Pin Kombu5.6.2, matching the working worker; do not upgrade shared environments in place.
The release gate checks exact versions before freeze and stable worker/beat readiness.
The correct loopback maintenance probe needs no Cloudflare login; require200 and
New ticket. Log only status/redirect/timing on failures, not response bodies/secrets.
Isolation with corrected dependency succeeded for pages, two tickets, three leases and
a harmless private-queue beat/worker sentinel. Isolated health503 reflects missing
real renewal/scheduler metadata in fresh Redis; do not disable the staging health guard.
Fresh verified prestop dumps must be taken immediately before stopping the four units,
then take frozen final dumps. Generate merged protected envs before migrating.
Staging deployment requires the owner's specific approval; production remains excluded.
