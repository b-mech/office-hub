# Production and maintenance branch split

Date: 2026-10-02 (America/Winnipeg)

## Result

The production snapshot at `0eeabf8` was separated into two branches without changing the checkout at `/home/officehub/office-hub`, restarting services, applying migrations, installing packages, or contacting application integrations.

- `production` retains all non-maintenance work from `0eeabf8`.
- `feature/maintenance-ticketing` starts from `production` and adds all maintenance work from `0eeabf8` and `wip/maintenance-2026-10-02` at `1abcc24`.
- The live database reported Alembic version `20260917_0045` through a read-only query to `office-hub-postgres-1` as user/database `officehub`.
- The `production` migration head is `20260917_0045`, matching the live database.
- The maintenance branch migration head is `20261001_0047`.

The split was constructed in isolated worktrees backed by `/home/officehub/branch-split-git`:

- `/home/officehub/office-hub-production`
- `/home/officehub/office-hub-maint`

## Moved to `feature/maintenance-ticketing`

The branch-only diff contains the maintenance ticketing work:

- Alembic migrations `0046` and `0047`.
- Maintenance ORM models, router, service package, Celery worker, phone-backfill and RingCentral subscription scripts.
- Maintenance tests and verification/audit documents.
- Tenant intake and QR pages, maintenance API client, rental-unit QR affordances, and maintenance permission/module registration.
- Maintenance settings and feature gating, public/webhook authentication exceptions, SMS providers and scheduling, tenant phone/opt-out and QR-rotation fields, dependencies, and shared-file registrations.
- The PRIVI Slack systemd unit template.

Shared files were split at hunk level. Presales registration, Box sweep models, costbook model registration, general rental-inspection save/recovery improvements, and the non-maintenance snapshot work remain in `production`.

`ops/systemd/officehub-worker.service` remains in `production`: Celery and its QBO and presales tasks are not maintenance-only. The maintenance branch extends the same worker with the maintenance task.

## Common branch changes

The existing Change Orders production-gap report from the WIP commit is retained on both branches under `docs/ops/` because it is operational documentation, not maintenance ticketing work.

The previously documented unmarked async test was changed to invoke its coroutine with `asyncio.run`. This avoids adding or installing a test plugin and lets the full backend suite provide a real pass/fail result on both branches.

## Verification

Tests ran with explicit dummy settings pointing at non-listening loopback ports. They did not load the production environment or contact PostgreSQL, Redis, MinIO, or external integrations.

- `production`: `87 passed`, with six existing Pydantic deprecation warnings.
- `feature/maintenance-ticketing`: `168 passed`, with the same six warnings.
- `git diff --check`: clean.
- Before adding this common report, the reconstructed maintenance tree matched `1abcc24` exactly except for the common async-test correction and the operations report.
- The final `git diff production feature/maintenance-ticketing` is limited to the maintenance paths and shared-file maintenance hunks listed above.

## Ambiguities and owner decisions

No code-placement ambiguity blocks the split. Two operational choices remain:

1. Checking out `production` changes files on disk but does not prove that an already-running Python process loaded exactly those bytes. Decide whether a separately scheduled, observed backend restart is required after the checkout. No restart was performed as part of this split.
2. `/home/officehub/office-hub-maint` is currently an isolated construction worktree backed by `/home/officehub/branch-split-git`. At cutover, either keep that backing repository or recreate the worktree from the canonical `/home/officehub/office-hub` repository after it fetches both branches.

## Proposed cutover — do not execute as part of this split

1. Confirm `/home/officehub/office-hub` is clean and that the pushed WIP and snapshot branches remain available.
2. Fetch `origin` in `/home/officehub/office-hub`.
3. Create or reset a local tracking branch for `origin/production`, then switch the checkout to it without restarting any service.
4. Verify the checkout is clean, its HEAD equals `origin/production`, its Alembic head is `20260917_0045`, and the live database still reports `20260917_0045`.
5. Keep the existing `/home/officehub/office-hub-maint` construction worktree, or remove it only after confirming it is clean and recreate it from the canonical repository at `feature/maintenance-ticketing`.
6. Do not apply migrations `0046` or `0047`, enable maintenance environment variables, install/start the Slack or maintenance worker behavior, or restart services until a separate maintenance rollout is approved.

The production checkout cutover itself remains unexecuted.
