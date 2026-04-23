# Land OTP Promotion Map

## Document type: land_otp
## Based on: Parkview Pointe Phase 3, Waterside Development Corp.

## Transaction boundary
All promotion writes happen in a single database transaction.
Document status only moves to `approved` after full transaction succeeds.

## Order of operations on approval
1. Upsert core.contacts — vendor
2. Upsert core.developments — subdivision
3. Insert land.agreements — one row
4. For each lot row: upsert core.lots → insert land.lot_terms → insert land.deposit_schedule rows
5. Insert land.security_deposit — one row per agreement
6. Insert land.notable_clauses — flagged NB items
7. Auto-create core.reminders for all dated deposits
8. Write core.audit_log entries for every record created
9. Set documents.reviews.promoted_at = now()
10. Set documents.documents.status = approved

## Agreement-level fields → land.agreements
- agreement_date (REQ) — page 1 header date
- vendor_name (REQ) → core.contacts upsert
- vendor_address (OPT) → core.contacts.address
- purchaser_name (REQ) → core.contacts upsert
- development_name (REQ) → core.developments upsert
- lot_draw_label (OPT) → metadata JSONB
- interest_rate (REQ) — spread value e.g. 0.0300
- interest_type (REQ) — prime_plus_fixed or flat
- interest_terms_text (REQ) — verbatim from document
- balance_due_rule (REQ) — e.g. "12 months from start date"
- interest_free_from (REQ) — date interest-free period starts
- total_purchase_price (REQ) — must match sum of lot prices
- municipality (REQ) → core.developments.municipality
- gst_registration (OPT) → metadata JSONB

## Security deposit → land.security_deposit (NEW TABLE)
- rate_per_lot (REQ) — $3,000 per lot
- maximum_amount (REQ) — $30,000
- calculated_amount (AUTO) — rate × lot_count capped at maximum
- due_trigger (REQ) — on_signing
- paid_at (OPT) — null at promotion, set later

## Per-lot fields → core.lots + land.lot_terms
- block (REQ) → core.lots.block
- lot_number (REQ) → core.lots.lot_number
- plan (REQ) → core.lots.plan
- legal_description_normalized (AUTO) — "BLK {block} LT {lot} PLAN {plan}"
- legal_description_raw (AUTO) — exact chart text
- civic_address (REQ) → core.lots.civic_address
- lot_status (AUTO) — set to land_contracted on creation
- frontage_metres (OPT) → land.lot_terms.frontage_metres
- frontage_feet (OPT) → land.lot_terms.frontage_feet
- lot_notes (OPT) → land.lot_terms.lot_notes
- purchase_price (REQ) → land.lot_terms.purchase_price
- balance_due_date (AUTO) — calculated from deposit_2_date + 12 months

## Deposit fields → land.deposit_schedule (2 rows per lot)
- deposit_1_amount (REQ) — from chart per lot
- deposit_1_trigger (AUTO) — on_signing
- deposit_1_due_date (AUTO) — equals agreement_date
- deposit_2_amount (REQ) — from chart per lot
- deposit_2_due_date (REQ) — fixed date from document
- deposit_2_trigger (AUTO) — fixed_date
- reminder auto-created for deposit_2 due date (14 days advance)
- reminder auto-created for balance due date (30 days advance)

## Notable clauses → land.agreements.notable_clauses JSONB
- NB-1: No construction until paid in full (clause 2e) — construction_gate
- NB-2: Vendor plan approval before building permit (clause 5a) — approval_required
- NB-3: 18-month exterior completion deadline (clause 5b) — build_deadline
- NB-4: Stantec Consulting required for lot grading (clause 5d) — required_consultant
- NB-5: No lot sale without vendor written consent (clause 13) — resale_restriction
- NB-6: Security deposit $3,000/lot up to $30,000 (clause 10) — financial_obligation
- NB-7: Architectural guidelines compliance required (Schedule B) — build_standards
- NB-8: Soil conditions disclaimer (clause 7) — site_condition

## Conflict rules
- Lot exists: match on legal_description_normalized, link, do not duplicate
- Lot exists with different civic address: flag for reviewer, do not auto-update
- Duplicate document: check checksum_sha256 on intake, reject before OCR
- Vendor contact exists: match on normalized name, link, do not duplicate
- Chart total mismatch: flag as low-confidence, block approval until confirmed
- Schedule B missing: auto-create reminder, do not block approval
