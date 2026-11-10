# Staging RingCentral renewal alerts — prepared, not deployed

Do not run deployment/restart/provider commands until Nicholas approves deployment.
No PR, staging deploy/restart, Slack post, or RingCentral API call was performed
while preparing this fix. No production files, services, DBs, or Redis settings
were changed. All commands below run on the Ubuntu host via the approved Mac SSH
connection; no SSH credentials belong in this repository.

## Evidence and scope

* Callback host/path: `officehub-staging.n10z.ca/api/webhooks/ringcentral/sms`.
* Worker/beat use `/home/officehub/office-hub-maint`,
  `feature/maintenance-ticketing` at `4288debd1e3164f191876471176f13b9ae8a3dd7`.
  Fix branch `fix/ringcentral-staging-alerts` starts from that deployed worker
  branch, not the unrelated tenant-integration or production branches.
* Backend/frontend are overridden to `/home/officehub/office-hub-lease-agreements`,
  `feature/lease-agreements` at `1664f8502ae98a8aa49f2eca741a86bef06fedf0`.
  The `lease-test.conf` user-unit drop-ins date to November 4, 13:36
  Winnipeg (UTC-5); its frontend build is from 13:35 that day.
* Public and frontend `:3001` callback POSTs return Next.js HTTP 404. Backend
  `:8001` accepts an empty POST, HTTP 200, echoing a synthetic Validation-Token.
  GET backend is 405 (correct for a POST-only route). Root public GET is Access
  302, but callback requests are not intercepted by an Access login redirect.
* The deployed lease frontend **source and build** lack the webhook rewrite.
  Its only rewrite is `/backend-api/:path*` to `:8001/:path*`. Maintenance source
  already has a webhook rewrite (added October 6); the lease lineage does not.
  No November 7 route removal was found. Matching failures were present by
  November 6, 00:30 Winnipeg (UTC-5), earlier than the reported November 7 posts.
* Celery beat interval is 3600 seconds, not a cron minute. Beat startup/persisted
  schedule explains `:20`. Each failed run previously posted unconditionally.
* The old probe sent Verification-Token plus JSON and checked only HTTP status.
  The fixed probe sends a fresh, non-secret Validation-Token on an **empty POST**,
  requires HTTP 200 AND an exact echo, and does not follow redirects. The private
  token is still reconciled by the existing provider PUT, never sent by the
  public routing/registration probe.

The legacy lease backend also differs from maintenance in notification
Verification-Token handling. This change verifies the registration handshake,
NOT delivery of real inbound SMS. Actual notification/token compatibility needs
separate verification; do not claim the entire SMS integration is proven fixed.

## Persistent alert policy

`subscription_alerts.py` uses a no-TTL Redis hash scoped by environment and a
callback hash. One Lua operation atomically records status and reserves a
notification across concurrent Celery jobs/API monitors. First observed failure
alerts once; repeated failure is silent until 24h since the last failure/reminder;
recovery alerts once; a genuinely new failure after recovery alerts immediately.
The initial healthy observation is silent. Older overlapping observations cannot
undo newer results. The API's stale-subscription monitor uses this SAME policy,
not its previous independent 30-minute alert lock. Other escalation alerts are
unchanged. No DB migration or new production dependency is required.

Claims are persisted BEFORE Slack transport, intentionally at-most-once. A crash
between reservation and send, or an ambiguous transport timeout, can lose that
notification rather than duplicate it; a later failure reminder remains eligible
at 24h. Redis unavailable => fail closed for Slack, while renewal errors/health
remain visible. Missing Slack configuration does not consume an alert reservation.
Do not delete the hash to retry a notification.

Worker/API restart state is covered using new clients against retained fake Redis
server state, and the actual Lua is executed by fakeredis/lupa. No live worker or
Redis restart was performed. The existing `office-hub-redis-1` container has a
`/data` mount; appendonly is not explicitly set in its command. Broker crash
recovery/disk flush guarantees are those of existing Redis persistence, not changed
or tested here. Never restart/reconfigure a potentially shared Redis for this fix.

Production's active worker uses `/home/officehub/office-hub/backend`; inspected
production schedule/code do not contain this renewal task/helper, and no separate
production beat was found. It is not currently running this same hourly path.
Deploying the older unthrottled maintenance code there would introduce the risk.

## Tests (safe now)

Install `backend/requirements-test.txt` only in an isolated test environment, not
into a running service's virtualenv. On this host, test-only dependencies were
installed under `/tmp/officehub-ringcentral-test-deps`; the deployed venv was not
modified. Then:

```sh
cd /home/officehub/office-hub-ringcentral-staging-alerts
PYTHONPATH=/tmp/officehub-ringcentral-test-deps \
  /home/officehub/office-hub-maint/backend/.venv/bin/python \
  ops/staging-ringcentral/run_backend_tests.py tests -q
```

The runner supplies dummy configuration, isolated HOME and no deployed .env,
blocks all Python TCP sockets (including during collection), and permits only
local Unix socketpairs needed by asyncio. Tests use fake providers/Slack, HTTP
MockTransport/ASGITransport, and Lua-enabled fake Redis. Coverage includes 64-way
concurrent failure/reminder/recovery claims, new connections after simulated
worker/monitor restarts, exact 24-hour boundaries, environment/callback isolation,
older overlapping observations, fail-closed persistence, ambiguous delivery,
job/monitor coordination, the lease patch, and probe redirects/missing/bad echo.

## Deployment — AFTER APPROVAL ONLY

This is a **configuration change PLUS rebuild** of the existing lease-agreements
frontend, not merely a rebuild: its checked-in config is missing the rewrite.
The patch is kept here because that live frontend checkout is a different branch.
It was checked with `git apply --check` against the live source, but NOT applied.
Do not repoint either staging backend/frontend to the maintenance branch; that
would replace unrelated lease features. Do not touch ports 3058/8058 or QA.

First confirm the approved fix branch tip matches the commit in the handoff.
Preserve the existing modified maintenance seed script; do not reset or clean.
The lease checkout also has unrelated uncommitted DocuSign/config/test/docs
changes, including an already-modified `frontend/next.config.ts`; this task did
not edit them. Review/coordinate pending frontend/config changes before approving
ANY build: a rebuild includes the checkout's current frontend source, not just
this patch. Leave the pending backend changes alone and do not restart that
backend. The commands below assume this source review has been completed.

```sh
set -eu
FIX=/home/officehub/office-hub-ringcentral-staging-alerts
MAINT=/home/officehub/office-hub-maint
LEASE=/home/officehub/office-hub-lease-agreements
PY="$MAINT/backend/.venv/bin/python"
APPROVED_COMMIT=$(git -C "$FIX" rev-parse fix/ringcentral-staging-alerts)
git -C "$MAINT" fetch origin fix/ringcentral-staging-alerts
test "$(git -C "$MAINT" rev-parse FETCH_HEAD)" = "$APPROVED_COMMIT"
git -C "$MAINT" status --short
git -C "$LEASE" status --short
# STOP here if pending lease frontend/config changes have not been reviewed.
git -C "$MAINT" merge --ff-only "$APPROVED_COMMIT"
PATCH="$MAINT/ops/staging-ringcentral/lease-frontend-webhook-rewrite.patch"
if git -C "$LEASE" apply --check "$PATCH"; then
  git -C "$LEASE" apply "$PATCH"
elif git -C "$LEASE" apply --reverse --check "$PATCH"; then
  printf 'Webhook rewrite already applied; continuing with rebuild.\n'
else
  printf 'Lease config differs; stop and review.\n' >&2
  exit 1
fi
# Uses the same staging environment file as the frontend service, never prints it.
# /usr/bin/env explicitly selects 8001 even if an inherited setting differs.
systemd-run --user --wait --pipe --collect \
  --unit=officehub-staging-frontend-build \
  --property="WorkingDirectory=$LEASE/frontend" \
  --property="EnvironmentFile=$LEASE/.env.lease-test" \
  /usr/bin/env BACKEND_INTERNAL_URL=http://127.0.0.1:8001 /usr/bin/npm run build
(cd "$LEASE/frontend" && /usr/bin/node <<'JS'
const m = require('./.next/routes-manifest.json');
const r = Array.isArray(m.rewrites) ? m.rewrites : Object.values(m.rewrites || {}).flat();
if (!r.some(x => x.source === '/api/webhooks/:path*' &&
                 x.destination === 'http://127.0.0.1:8001/api/webhooks/:path*')) {
  throw new Error('Staging webhook rewrite missing or wrong destination; do not restart');
}
console.log('Verified staging webhook rewrite to 8001');
JS
)
systemctl --user restart officehub-staging-frontend.service officehub-staging-worker.service
systemctl --user is-active officehub-staging-frontend.service officehub-staging-worker.service
```

Do NOT restart the staging backend or beat (unchanged), production services, or
Redis. No schema migration is needed. The lease config patch will remain an
intentional local modification in that separate staging checkout; commit it on a
separately reviewed lease branch before a later lease deployment replaces it.

### Cloudflare/Tunnel

No Access/tunnel change is needed if the frontend rewrite fixes all three checks
below. Preserve Access on the rest of the application. If frontend succeeds but
public callback still does not, inspect remotely managed ingress before changing
it. An explicit narrow fallback would be a published-route/ingress rule BEFORE
the hostname catch-all: hostname `officehub-staging.n10z.ca`, path regex
`^/api/webhooks/ringcentral/sms/?$`, service `http://127.0.0.1:8001`. Preserve only
the existing callback-specific Access bypass; never bypass the whole hostname.
This proposed tunnel change has NOT been applied or tested.

## Post-deploy verification — AFTER APPROVAL ONLY

1. Check own endpoints (no RingCentral calls, configured tokens, or Slack posts):

```sh
"$PY" "$MAINT/ops/staging-ringcentral/verify_staging.py" --handshake
```

All three (backend, frontend, public) must report HTTP 200 and echo=True. A 302,
404, or missing/mismatched echo is failure. Do not run renewal until this passes.

2. Exactly one manual renewal, only with approval to call RingCentral and allow a
state-change Slack notification. systemd supplies the same environment as worker:

```sh
systemd-run --user --wait --pipe --collect \
  --unit=officehub-staging-renewal-check \
  --property="WorkingDirectory=$MAINT/backend" \
  --property="EnvironmentFile=$MAINT/.env.staging" \
  "$PY" "$MAINT/ops/staging-ringcentral/verify_staging.py" --run-renewal
systemd-run --user --wait --pipe --collect \
  --unit=officehub-staging-renewal-state \
  --property="WorkingDirectory=$MAINT/backend" \
  --property="EnvironmentFile=$MAINT/.env.staging" \
  "$PY" "$MAINT/ops/staging-ringcentral/verify_staging.py" --state
```

Expected: renewal succeeds with a verified public handshake; state `ok`, TTL -1.
A recovery alert occurs only if the new persistent state was already `failing`;
an initial successful run is intentionally silent. No unnecessary second manual
provider call is needed. The helper prints only controlled status/type information,
not provider error payloads, secrets, database URLs, or environment contents.

3. Use the isolated transition/concurrency/restart tests above for synthetic
failure/recovery; do NOT intentionally break live webhook routing or clear live
state to test Slack. After approval, a later isolated staging-worker restart may
verify retained status, but do not restart a service just to test this without
approval. Watch at least two successive scheduled :20 windows: no repeated failure
posts when healthy; while genuinely down, one initial failure and no reminder
until 24h, with one recovery on success. Observe Slack read-only; send nothing.

4. Do not dump raw worker journals (third-party exceptions can contain private
payloads). Inspect safe task outcome/timestamp filters, plus `--state` and the
HTTP/echo checks. Confirm actual inbound SMS separately; it was not exercised.
