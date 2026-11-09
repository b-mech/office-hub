# Dated facility draw history (PR #2, preview only)

Migration `20261109_0061` follows `20261109_0060`. Adds nullable `notes` (text),
`confirmed_by` (varchar 255), `percent_complete` (numeric 5,2, 0–100 check) on
`core.facility_transactions`. No balance changes/backfill. PR #3 has independent
0058: merge current heads **0061 + 20261106_0058** before combining deployments.
Never reparent already-applied revisions.

## DBip contract

Base for the Mac tunnel/frontend proxy:
`http://localhost:3058/backend-api/api/v1/financing/facilities/{facility_id}`.
Direct private backend: `http://127.0.0.1:8058/api/v1/financing/facilities/{facility_id}`.
Keep tenant/auth selection consistent with Office Hub; use `X-OfficeHub-Org` when
selecting the CH org. Legacy/org-less financing is CH-only. Readonly actors may
GET but cannot POST/DELETE. QA `AUTH_ENFORCED=false` uses the existing fallback
admin; this is not production authentication acceptance. `confirmed_by` is a bank
confirmation label supplied by the importer, NOT an authenticated actor claim.

### GET `/draws` — any facility, including PRO

200 body (decimal values are JSON strings):
```json
{
  "facility_id": "UUID", "lender_type": "SCU", "already_drawn": "150000.00",
  "sum_of_draws": "25000.25", "sum_of_repayments": "0.00", "net_draws": "25000.25",
  "difference_from_already_drawn": "124999.75",
  "items": [{
    "id": "UUID", "facility_id": "UUID", "txn_date": "2026-10-15",
    "txn_type": "draw", "amount": "25000.25", "reference": "SCU-1",
    "notes": "Bank progress confirmation", "confirmed_by": "Bank confirmation",
    "percent_complete": "35.50", "source": "scu_confirmation",
    "created_at": "ISO-8601 timestamp", "running_total": "25000.25", "can_delete": true
  }]
}
```
Items are oldest-first by txn_date, created_at, id. Running total is draws minus
repayments; original advance/land/interest are NOT invented as history entries.
`sum_of_draws` is the gross sum of ALL stored draw transactions for the facility,
not a current bank balance. `difference_from_already_drawn` is exactly bank balance
minus gross draws (not net); repayments/net totals are reported separately. If
bank balance is null, it and the comparison are null, never an invented zero.

### POST `/draws` — non-PRO facilities only

A single object OR a JSON array of 1–1000 objects (atomic batch):
```json
{
  "txn_date": "2026-10-15", "amount": "25000.25",
  "reference": "SCU-1", "notes": "Bank progress confirmation",
  "confirmed_by": "Bank confirmation", "percent_complete": "35.50",
  "txn_type": "draw", "source": "scu_confirmation"
}
```
Required: txn_date (ISO date), amount (positive, max 12 whole digits + 2 cents).
Optional: reference (max 1000; absent/null/blank canonicalized to empty string),
notes (max 10000; alias `confirmation_text` accepted instead, not both), confirmed_by
(max 255), percent_complete (0–100, max 2 decimals), txn_type (`draw` default or
`repayment`), source (`scu_confirmation` or `manual`). When source is omitted/null,
SCU defaults to scu_confirmation; other non-PRO lenders default to manual.
Unknown fields, excessive precision/ranges and invalid sources/types yield 422.

200 body:
```json
{
  "facility_id": "UUID", "created": 1, "skipped": 0,
  "results": [{"status": "created", "txn_id": "UUID"}],
  "history": {
    "facility_id": "UUID", "lender_type": "SCU", "already_drawn": "150000.00",
    "sum_of_draws": "25000.25", "sum_of_repayments": "0.00", "net_draws": "25000.25",
    "difference_from_already_drawn": "124999.75",
    "items": [{
      "id": "UUID", "facility_id": "UUID", "txn_date": "2026-10-15",
      "txn_type": "draw", "amount": "25000.25", "reference": "SCU-1",
      "notes": "Bank progress confirmation", "confirmed_by": "Bank confirmation",
      "percent_complete": "35.50", "source": "scu_confirmation",
      "created_at": "ISO-8601 timestamp", "running_total": "25000.25", "can_delete": true
    }]
  }
}
```
`results` preserves input order, each status is created or skipped. Duplicate
identity is the EXISTING key `(facility_id, txn_date, amount, reference)`, which
DOES NOT include txn_type, percent, notes, source or confirmer. Retries skip and
return the existing txn_id; metadata is never silently overwritten. Use distinct
references for legitimately separate equal-date/equal-amount entries (including
opposite transaction types). New missing references are `''`; legacy NULL refs
are also recognized. Facility row lock + ON CONFLICT protect concurrent retries.
No changes to already_drawn, current/outstanding balance, last_draw_* or facility
updated_at; DBip must keep bank balances separately.

### DELETE `/draws/{txn_id}` — undo an imported/manual row

200: `{ "deleted": true, "txn_id": "UUID", "history": FULL_GET_OBJECT }`.
The transaction MUST belong to the facility. Missing facility/transaction: 404.
Only manual/scu_confirmation sources without statement_id/funds_entry_id/
funds_notice_id links can be deleted. Integrated/lawyer/statement rows: 409;
manage them through their original workflow. Bank balances remain untouched.
All PRO POST/DELETE calls return 409; existing `/ledger` behavior/code is unchanged.
Wrong org / readonly write: 403. Existing auth guard remains in force.

## Frontend / QA

Non-PRO drawer shows summary, chronological table, running net total, a collapsed
Add draw/repayment form and inline confirmation before delete. Integrated rows
are read-only. Deep link `/financing?property_id={id}#draw-history` opens the drawer
and scrolls to history after load; this is not evidence of pointer interactions.

Before deployment, pg_dump ONLY officehub_workspace_qa_20261106. Apply 0061 to that
DB only; restart only QA backend/frontend (8058/3058), rebuild frontend and reapply
`.next/routes-manifest.json` /backend-api rewrite to 8058. Keep integrations disabled.
Smoke: capture before state, POST one clearly labelled QA draw for 106 Buffalo
Trail SCU, replay to confirm skip, screenshot the deep-linked drawer using Mac
headless Chrome, DELETE only the created test id in a finally cleanup, compare
history and bank/last_draw_* before/after. Never delete a pre-existing duplicate.

The initial endpoint tests use an isolated SQL-result store, NOT PostgreSQL or
real auth; a real preview round-trip and screenshot are separate acceptance steps.

Read-only preview target discovery (no test row created): 106 Buffalo Trail,
SCU facility `38ce0c77-1575-4be2-9f56-2baa37dde933`, master property
`501aa756-5765-47d7-98a9-28e1a90223bc`.
Drawer URL: `http://localhost:3058/financing?property_id=501aa756-5765-47d7-98a9-28e1a90223bc#draw-history`.

Implementation verification before deployment: complete backend suite 293 passed,
18 skipped, 2 subtests passed (35 new isolated endpoint tests). Frontend tsc,
production build and client API guard passed. Real PostgreSQL migration, auth,
HTTP create/delete roundtrip and rendered drawer are NOT covered by those tests.
