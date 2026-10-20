"""One-shot production funds checks for systemd timers."""
from __future__ import annotations

import argparse
import asyncio

from app.core.database import AsyncSessionLocal
from app.services.funds_monitor import run_gap_checks, scan_closing_folders


async def main(kind: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await (run_gap_checks(db) if kind == "gaps" else scan_closing_folders(db))
        print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["gaps", "watch"])
    args = parser.parse_args()
    asyncio.run(main(args.kind))
