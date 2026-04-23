# Database Schema Decisions

## Why PostgreSQL schemas instead of separate databases
Cross-module joins are required. Separate databases would prevent
land.lot_terms joining to sales.agreements on the same lot.

## Schema layout
- core — orgs, users, contacts, developments, lots, reminders, audit_log
- documents — documents, ingestions, extractions, reviews
- land — agreements, lot_terms, deposit_schedule, milestones, security_deposit
- sales — agreements, parties, deposit_schedule

## Identity model
- core.lots.id (UUID) — internal identity, never changes
- core.lots.legal_description_normalized — cross-document matching key
- core.lots.civic_address — mutable display field only

## Staging to promotion boundary
Extraction layer = what the machine thinks (documents schema)
Operational layer = what the business accepts as true (land, sales schemas)
These must never be blurred. Promotion reads reviewed_payload from
documents.reviews, never re-reads AI extraction output.

## Money convention
NUMERIC(15,2) everywhere. Python Decimal type in application code.
Never float. No exceptions.

## State machines
- document.status: received → classifying → extracting → in_review → approved | rejected
- core.lots.status: land_contracted → land_purchased → serviced → sale_signed → build_active → possession → warranty
- sales.agreements.status: received → conditions_pending → firm → build_started → possession_complete | collapsed
- land.deposit_schedule status: scheduled → due → paid | overdue
