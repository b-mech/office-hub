"""Import the nine-page July 2026 PRO PDF through the normal statement pipeline.

This creates statement reviews only. It never approves facility transactions.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.box import download_file  # noqa: E402
from app.services.financing import get_statement, parse_and_reconcile_statement, record_statement  # noqa: E402
from app.services.minio_financing import upload_financing_document  # noqa: E402


BOX_FILE_ID = "2419483499912"
FILENAME = "11 - Connection_07312026171851.PDF"
PERIOD = "2026-07"
KEY = f"financing/pro/statements/{PERIOD}/{FILENAME}"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(text("""
            SELECT id FROM documents.lender_statements WHERE lender='PRO' AND period=:period
        """), {"period": PERIOD})).scalars().all()
        if existing:
            raise RuntimeError(f"July PRO statement already exists: {existing}")
        content = download_file(BOX_FILE_ID)
        if not content.startswith(b"%PDF"):
            raise RuntimeError("Box file is not a PDF")
        upload_financing_document(key=KEY, content=content, content_type="application/pdf")
        statement_id = await record_statement(
            db, lender="PRO", period=PERIOD, minio_object_key=KEY,
            original_filename=FILENAME,
        )
        await parse_and_reconcile_statement(db, statement_id, content)
        statement = await get_statement(db, statement_id)
        if statement is None or len(statement.snapshots) != 9:
            raise RuntimeError(f"July PRO import expected nine snapshots: {statement_id}")
        failures = [s.matched_property_name for s in statement.snapshots if s.reconciliation_status == "parse_error"]
        if failures:
            raise RuntimeError(f"July PRO parser errors: {failures}")
        print(f"statement_id={statement_id} period={PERIOD} pages={len(statement.snapshots)} status={statement.status}")
        for snapshot in statement.snapshots:
            print(
                f"{snapshot.matched_property_name}: {snapshot.reconciliation_status} "
                f"delta={snapshot.delta} draws={snapshot.new_draws_detected}"
            )


if __name__ == "__main__":
    asyncio.run(main())
