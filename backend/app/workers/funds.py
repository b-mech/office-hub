from __future__ import annotations

import asyncio

from app.core.database import AsyncSessionLocal
from app.services.funds_monitor import run_gap_checks, scan_closing_folders
from app.workers.celery_app import celery_app


@celery_app.task(name="funds.daily_gap_checks")
def daily_gap_checks() -> dict[str, int]:
    async def run() -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            return await run_gap_checks(db)
    return asyncio.run(run())


@celery_app.task(name="funds.watch_closing_folders")
def watch_closing_folders() -> dict[str, int]:
    async def run() -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            return await scan_closing_folders(db)
    return asyncio.run(run())
