# Office Hub

Real estate development operating system for residential home builders.

## Modules
- Document ingestion — land OTP and sale OTP PDF processing
- Lot management — address-anchored project records
- Construction PM — per-lot build tracking
- AP / Invoice processing
- Cash flow analysis
- Legal document tracking

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy, Alembic, Celery
- Frontend: Next.js 14, TypeScript, Tailwind CSS
- Database: PostgreSQL 16
- Storage: MinIO
- AI: Claude (swappable via ModelProvider abstraction)

## Setup
See docs/architecture/ for schema decisions and promotion maps.
See docs/prompts/ for Codex CLI prompt library.
