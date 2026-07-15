from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.addresses import normalize_address  # noqa: E402
from app.financing.engines.pro import ProFacility  # noqa: E402
from app.financing.engines.pro import ProTransaction  # noqa: E402
from app.financing.engines.pro import compute_ledger  # noqa: E402


DEFAULT_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "pro_seed_2026-06.json"


async def main() -> None:
    seed_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_SEED_PATH
    data = json.loads(seed_path.read_text(), parse_float=Decimal)

    async with AsyncSessionLocal() as db:
        rows: list[tuple[str, Decimal, Decimal, Decimal]] = []
        for item in data["facilities"]:
            facility_id = await _upsert_facility(db, item)
            await _upsert_draws(db, facility_id, item.get("draws", []))
            await _upsert_aliases(db, facility_id, item["property_name"])
            rows.append(_verification_row(item))

        await db.commit()

    print("facility_key                         computed       reported       delta")
    print("--------------------------------------------------------------------------")
    for facility_key, computed, reported, delta in rows:
        print(f"{facility_key:<34} {computed:>12} {reported:>12} {delta:>10}")

    total = sum((reported for _, _, reported, _ in rows), Decimal("0.00"))
    print("--------------------------------------------------------------------------")
    print(f"{'TOTAL':<34} {'':>12} {total:>12} {'':>10}")


async def _upsert_facility(db: AsyncSession, item: dict) -> UUID:
    canonical = normalize_address(item["property_name"])
    row = (
        await db.execute(
            text(
                """
                INSERT INTO core.lender_facilities (
                    lender_type, lender, lender_name, facility_key, property_name,
                    canonical_address_key, facility_scope, instrument, borrower, annual_rate,
                    original_advance_date, original_advance_amount, status, notes
                )
                VALUES (
                    'PRO', 'PRO', 'ProAuto', :facility_key, :property_name,
                    :canonical_address_key, :facility_scope, :instrument, :borrower, :annual_rate,
                    :original_advance_date, :original_advance_amount, 'active', :notes
                )
                ON CONFLICT (facility_key) DO UPDATE SET
                    lender_type = 'PRO',
                    lender = 'PRO',
                    lender_name = 'ProAuto',
                    property_name = EXCLUDED.property_name,
                    canonical_address_key = EXCLUDED.canonical_address_key,
                    facility_scope = EXCLUDED.facility_scope,
                    instrument = EXCLUDED.instrument,
                    borrower = EXCLUDED.borrower,
                    annual_rate = EXCLUDED.annual_rate,
                    original_advance_date = EXCLUDED.original_advance_date,
                    original_advance_amount = EXCLUDED.original_advance_amount,
                    status = EXCLUDED.status,
                    notes = EXCLUDED.notes,
                    updated_at = now()
                RETURNING id
                """
            ),
            {
                "facility_key": item["facility_key"],
                "property_name": item["property_name"],
                "canonical_address_key": canonical.canonical_key,
                "facility_scope": item.get("facility_scope", "lot"),
                "instrument": item.get("instrument"),
                "borrower": item["borrower"],
                "annual_rate": item["annual_rate"],
                "original_advance_date": date.fromisoformat(item["original_advance"]["date"]),
                "original_advance_amount": Decimal(item["original_advance"]["amount"]),
                "notes": "Seeded from PRO June 2026 statement fixture.",
            },
        )
    ).scalar_one()
    return row


async def _upsert_draws(db: AsyncSession, facility_id: UUID, draws: list[dict]) -> None:
    for draw in draws:
        await db.execute(
            text(
                """
                INSERT INTO core.facility_transactions (
                    facility_id, txn_date, txn_type, amount, reference, source
                )
                VALUES (
                    :facility_id, :txn_date, 'draw', :amount, :reference, 'seed'
                )
                ON CONFLICT ON CONSTRAINT uq_facility_transactions_identity DO UPDATE SET
                    source = EXCLUDED.source
                """
            ),
            {
                "facility_id": facility_id,
                "txn_date": date.fromisoformat(draw["date"]),
                "amount": Decimal(draw["amount"]),
                "reference": draw.get("reference"),
            },
        )


async def _upsert_aliases(db: AsyncSession, facility_id: UUID, property_name: str) -> None:
    aliases = {property_name, _normalize_alias(property_name), normalize_address(property_name).canonical_key}
    for alias in aliases:
        await db.execute(
            text(
                """
                INSERT INTO core.facility_aliases (facility_id, alias)
                VALUES (:facility_id, :alias)
                ON CONFLICT (alias) DO UPDATE SET facility_id = EXCLUDED.facility_id
                """
            ),
            {"facility_id": facility_id, "alias": alias},
        )


def _verification_row(item: dict) -> tuple[str, Decimal, Decimal, Decimal]:
    reported = item["reported_balances"][-1]
    facility = ProFacility(
        facility_key=item["facility_key"],
        property_name=item["property_name"],
        borrower=item["borrower"],
        annual_rate=item["annual_rate"],
        original_advance_date=date.fromisoformat(item["original_advance"]["date"]),
        original_advance_amount=Decimal(item["original_advance"]["amount"]),
    )
    transactions = [
        ProTransaction(
            txn_date=date.fromisoformat(draw["date"]),
            txn_type="draw",
            amount=Decimal(draw["amount"]),
            reference=draw.get("reference"),
        )
        for draw in item.get("draws", [])
    ]
    reported_balance = Decimal(reported["balance"]).quantize(Decimal("0.01"))
    computed = compute_ledger(facility, transactions, date.fromisoformat(reported["date"])).balance_as_of
    return item["facility_key"], computed, reported_balance, computed - reported_balance


def _normalize_alias(value: str) -> str:
    cleaned = re.sub(r"\bCONNECTION HOMES(?: INC\.?)?\b", "", value.upper())
    cleaned = re.sub(r"[^A-Z0-9]+", " ", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned)


if __name__ == "__main__":
    asyncio.run(main())
