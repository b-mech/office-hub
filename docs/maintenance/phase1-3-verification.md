# Maintenance Phases 1–3 verification

Date: 2026-10-01

## Database-copy migration

Source: `/home/officehub/officehub-before-0035.dump` (production-copy backup)

- Restored into isolated database `officehub_maint_verify_20261001`.
- Applied repository migrations from `20260811_0034` through `20261001_0046` successfully.
- Downgraded `20261001_0046` to `20260917_0045` successfully.
- Re-applied `20261001_0046` successfully.
- Confirmed Alembic head `20261001_0046`.
- Confirmed all nine `maint_*` tables exist.
- Confirmed an attempted `UPDATE` of `maint_events` is rejected by the append-only trigger.

Alembic's repository-wide `check` command is not currently a usable clean-schema signal: its environment does not enable cross-schema reflection and therefore reports existing `core`, `documents`, `land`, `sales`, `financing`, and `costbook` tables as additions. This predates maintenance and did not prevent the upgrade/downgrade execution test.

## Tenant phone backfill report

- Existing non-empty phone records inspected: 33
- Normalized successfully: 32
- Failed validation: 1
- Manual-review record: tenant ID `7`, phone ending `1980`

The migration leaves invalid values unchanged and reports tenant IDs only. Correct tenant ID 7 before applying the migration to live data, then rerun:

```bash
cd /home/officehub/office-hub/backend
set -a; source ../.env; set +a
PYTHONPATH=. .venv/bin/python scripts/maintenance_phone_backfill_report.py
```

## Automated checks

- Focused maintenance tests: 48 passed.
- Python compile check: passed.
- SQLAlchemy mapper configuration: passed.
- Python dependency integrity (`pip check`): passed.
- Alembic offline SQL generation for `0045 → 0046`: passed.

The focused suite covers every allowed ticket transition, representative invalid transitions, admin-only closed-ticket reopening, work-order-derived status decisions, phone normalization, entry-notice policy branches, EXIF removal, PDF gating, and signed-media expiry/signature validation.
