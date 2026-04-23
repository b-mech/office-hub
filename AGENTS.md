# Office Hub — Codex Agent Instructions

## Project
Office Hub is a real estate development operating system built for a residential home builder.
Backend: Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Celery, Redis.
Frontend: Next.js 14 (app router), TypeScript, Tailwind CSS.
Database: PostgreSQL 16, multiple schemas (core, documents, land, sales).
File storage: MinIO (S3-compatible).

## Domain context
The system processes land purchase agreements (OTP Land) and home sale agreements (OTP Sale).
Every lot is identified by an internal UUID and anchored by a normalized legal description.
The civic address is a mutable display field only.
All document data flows through a staging pipeline before being promoted to operational tables.

## Code conventions
- Python: use async/await throughout. Type hints on all functions.
- Money: NUMERIC(15,2) in DB, Python Decimal type in code. Never float.
- UUIDs as primary keys everywhere using gen_random_uuid().
- PostgreSQL schemas: core, documents, land, sales. Keep models in separate files per schema.
- State transitions enforced in service layer only, never in route handlers.
- Staging tables (documents schema) are never written to from operational promotion code.
- Promotion happens only via PromotionService in backend/app/services/promotion.py.
- All promotion writes happen in a single database transaction.

## File locations
- SQLAlchemy models: backend/app/models/
- Pydantic schemas: backend/app/schemas/
- Route handlers: backend/app/api/v1/endpoints/
- Business logic: backend/app/services/
- Background tasks: backend/app/workers/
- DB migrations: backend/alembic/versions/
- Codex prompts library: docs/prompts/
- Promotion maps: docs/promotion-maps/

## Never do
- Never use float for money
- Never write directly to land.* or sales.* tables from document processing code
- Never skip the staging to promotion boundary
- Never hardcode model provider names outside of backend/app/services/extraction/
- Never commit .env files
- Never put business logic in route handlers
