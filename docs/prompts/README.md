# Codex CLI Prompts Library

Prompts are numbered and run in order. Each prompt is self-contained.
Run from the root of the office-hub directory.

## Usage
cd ~/Library/Mobile\ Documents/com~apple~CloudDocs/Projects/office-hub
codex "paste prompt content here"

## Prompt index
01-docker-compose.md        — Infrastructure services
02-init-sql.md              — PostgreSQL schema all four schemas
03-fastapi-skeleton.md      — App entry point, config, db connection
04-alembic-setup.md         — Migration environment
05-sqlalchemy-models.md     — ORM models mirroring schema
06-ocr-service.md           — pdfplumber + Tesseract pipeline
07-extraction-service.md    — AI provider abstraction + Claude prompt
08-email-watcher.md         — IMAP poller and queue dispatch
09-review-api.md            — Approval workflow endpoints
10-review-ui.md             — Split screen PDF and fields editor
