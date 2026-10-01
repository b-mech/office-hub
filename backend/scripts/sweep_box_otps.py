#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from app.core.database import AsyncSessionLocal
from app.services.box_otp_sweep import BoxOtpSweepService
from app.services.box_otp_sweep import DEFAULT_QUERIES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory Box OTP candidates, persist every outcome, and optionally ingest selected Land OTP PDFs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ingest explicitly selected Land OTP files. Without this flag the sweep is read-only apart from its audit log.",
    )
    parser.add_argument(
        "--box-file-id",
        action="append",
        default=[],
        help="Box file ID to ingest. Repeat for multiple files; exact SHA-1 copies are collapsed.",
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Override the default Box search queries. Repeat to supply multiple queries.",
    )
    args = parser.parse_args()
    if args.apply and not args.box_file_id:
        parser.error("--apply requires at least one --box-file-id")
    return args


async def main() -> None:
    args = parse_args()
    print("starting Box OTP sweep", flush=True)
    async with AsyncSessionLocal() as db:
        result = await BoxOtpSweepService(db).run(
            apply=args.apply,
            target_file_ids=set(args.box_file_id),
            queries=tuple(args.query) if args.query else DEFAULT_QUERIES,
        )
    print(f"run_id={result.run_id}", flush=True)
    print(f"candidates_found={result.candidates_found}")
    print(f"ingested_document_ids={','.join(str(item) for item in result.ingested_document_ids)}")
    print(f"skipped={result.skipped}")
    print(f"failed={result.failed}")


if __name__ == "__main__":
    asyncio.run(main())
