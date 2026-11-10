# Rentals map incident: prepared fix, NOT deployed

Incident window2026-11-10 16:40–16:46 Winnipeg session UTC-5.
The release94f28de rentals page is byte-identical to previous lease and maint-ux
checkouts. Google Maps is still used at /rentals; Leaflet /rentals/map belongs to
the separate lease-tenant-integration feature and was not removed by this merge.
The real API is GET /api/rentals/properties/map (not /api/rentals/map):200,
22 properties,21 located. The page does not invoke a geocoder.
The browser key exists in runtime frontend.env and the old build, but not the
new built JS; HTML displays the missing-key banner and has no Google SDK URL.
Next PUBLIC variables must be supplied at build time. No CSP header was present.

## Preparation validation

Run backend tests with dummy settings/TCP disabled, frontend tsc and an isolated
explicit Webpack build. A non-live browser-key fixture proves compile-time
inlining without applying a real environment fix. That artifact is NOT a
deployable release; no real Google tile rendering is claimed by that test.

## Exact frontend-only deployment, AFTER Nicholas approves

1. First create mode0700 NEW-BACKUP at /home/officehub/staging-rollbacks/rentals-map-<timestamp>.
   Resolve this reviewed fix SHA. Create a NEW detached immutable release worktree
   /home/officehub/releases/rentals-map-<sha12>; never rebuild the serving .next.
2. npm ci in its frontend. Use existing94f28de venv Python (dotenv installed)
   to invoke the NEW build_frontend.py with --frontend NEW/frontend,
   --env /home/officehub/staging-rollbacks/lease-maint-fixed-20261110T133426-0500/new-env/frontend.env,
   --log NEW-BACKUP/frontend-build.log. This reads the existing browser
   key privately, changes no env file, and runs guarded `next build --webpack`.
   Require browser_map_key_inlined=true, missing_key_banner=false, tsc and
   /api/webhooks rewrite targeting8001. Do not use the fixture build.
3. Immediately before service changes, record all four staging PIDs/working dirs
   in NEW-BACKUP. Copy current frontend
   zz-lease-maint.conf and frontend .next to that directory. No DB migration
   or write is needed; backend/worker/beat stay on94f28de and are NOT restarted.
4. Replace ONLY staging frontend zz-lease-maint.conf with the following
   (expand NEW/frontend to the immutable candidate's actual absolute path):
   [Service]
   WorkingDirectory=NEW/frontend
   EnvironmentFile=
   EnvironmentFile=/home/officehub/staging-rollbacks/lease-maint-fixed-20261110T133426-0500/new-env/frontend.env
   Environment=BACKEND_INTERNAL_URL=http://127.0.0.1:8001
   ExecStart=
   ExecStart=/usr/bin/npm start -- --hostname 127.0.0.1 --port 3001
5. systemctl --user daemon-reload. Assert frontend WorkingDirectory,
   EnvironmentFiles and ExecStart match candidate BEFORE restarting.
   Use release_checks.assert_effective for FRONTEND ONLY: other three units
   intentionally remain on94f28de, so the all-four uniform-release CLI is not
   appropriate for this frontend-only patch.
6. systemctl --user restart officehub-staging-frontend.service ONLY.
   Require /rentals200 with no missing-key banner, actual map API200/22/21,
   backend health200, /w/bogus404, public webhook validation echo200, unchanged
   backend/worker/beat PIDs. Verify map/markers and browser console through
   real staging hostname with normal Access session; localhost may not
   satisfy Google browser-key referrer restrictions. No geocoder or sends.

## Rollback on any failure

Restore ONLY saved frontend zz drop-in, daemon-reload, restart ONLY
officehub-staging-frontend.service. Original94f28de .next was never changed.
Confirm frontend200/backend health200/public webhook echo200 and unchanged
backend/worker/beat PIDs. No DB restore, downgrade or migration is involved.
Expected frontend outage5–15 seconds; preparation/build causes no outage.
No production, Cloudflare, SMS, Slack or DocuSign changes/calls.


## Command sequence for the approved future frontend-only change

Replace APPROVED_FIX_SHA before running; this block is documentation, not approval.

```bash
set -euo pipefail
umask 077
SOURCE=/home/officehub/office-hub-rentals-map-build-fix
SHA=APPROVED_FIX_SHA
NEW=/home/officehub/releases/rentals-map-${SHA:0:12}
RB=/home/officehub/staging-rollbacks/rentals-map-$(date +%Y%m%dT%H%M%S%z)
OLD=/home/officehub/releases/lease-maint-94f28de686e3
PY="$OLD/.venv/bin/python"
ENVDIR=/home/officehub/staging-rollbacks/lease-maint-fixed-20261110T133426-0500/new-env
UNITDIR="$HOME/.config/systemd/user/officehub-staging-frontend.service.d"
mkdir -m 700 "$RB"
git -C "$SOURCE" worktree add --detach "$NEW" "$SHA"
(cd "$NEW/frontend" && npm ci)
"$PY" "$NEW/ops/staging-integration/build_frontend.py" --frontend "$NEW/frontend" --env "$ENVDIR/frontend.env" --log "$RB/frontend-build.log"
(cd "$NEW/frontend" && node node_modules/typescript/bin/tsc --noEmit --incremental false)
cp -a "$UNITDIR/zz-lease-maint.conf" "$RB/frontend-original.conf"
cp -a "$OLD/frontend/.next" "$RB/next"
for s in backend frontend worker beat; do systemctl --user show "officehub-staging-$s.service" -p MainPID -p WorkingDirectory >> "$RB/services-before.txt"; done
"$PY" - "$NEW" "$RB" "$ENVDIR" <<'PYCONFIG'
from pathlib import Path
import importlib.util,sys
new,rb,envdir=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('candidate',new/'ops/staging-integration/make_overrides.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
p=rb/'frontend-candidate.conf';p.write_text(mod.contents('frontend',new,envdir));p.chmod(0o600)
PYCONFIG
install -m 600 "$RB/frontend-candidate.conf" "$UNITDIR/zz-lease-maint.conf"
systemctl --user daemon-reload
systemd-analyze --user verify officehub-staging-frontend.service 2> "$RB/systemd-verify.log"
"$PY" - "$NEW" "$ENVDIR" <<'PYCHECK'
from pathlib import Path
import importlib.util,sys
new,envdir=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('checks',new/'ops/staging-integration/release_checks.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
mod.assert_effective('frontend',{k:mod.show('frontend',k) for k in ('WorkingDirectory','EnvironmentFiles','ExecStart')},new,envdir)
print('Frontend effective configuration verified; values hidden')
PYCHECK
systemctl --user restart officehub-staging-frontend.service
# Wait up to30s for frontend readiness; do not treat its initial startup gap as failure.
# Then verify all step6 checks and real staging-host map rendering before success.
# On ANY config/build/verification failure after override installation, restore:
# install -m 600 "$RB/frontend-original.conf" "$UNITDIR/zz-lease-maint.conf"
# systemctl --user daemon-reload
# systemctl --user restart officehub-staging-frontend.service
# Confirm original frontend200, backend health200, public validation echo200.
```

No rollback commands above are executed by the build helper. An operator must run
rollback on failure; `set -e` alone is NOT an automatic rollback implementation.
