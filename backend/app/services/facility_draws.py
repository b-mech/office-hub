"""Supplemental history only: never updates lender_facilities or PRO balances."""
from decimal import Decimal
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.facility_draws import (
    FacilityDrawCreate, FacilityDrawOut, FacilityDrawHistory,
    FacilityDrawImportOut, FacilityDrawDeleteOut, DrawImportResult,
)

MANUAL_SOURCES = {"scu_confirmation", "manual"}


def can_delete_transaction(row) -> bool:
    return row["source"] in MANUAL_SOURCES and not any(row.get(key) for key in ("statement_id", "funds_entry_id", "funds_notice_id"))


async def _facility(db: AsyncSession, facility_id: UUID, *, write=False):
    row = (await db.execute(text(
        "SELECT id, lender_type, lender, already_drawn FROM core.lender_facilities WHERE id=:facility_id"
        + (" FOR UPDATE" if write else "")
    ), {"facility_id": facility_id})).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Facility not found")
    if write and "PRO" in {row["lender_type"], row["lender"]}:
        raise HTTPException(409, "Use the existing PRO reconciliation workflow; manual history writes are non-PRO only")
    return row


async def _history(db: AsyncSession, facility) -> FacilityDrawHistory:
    rows = (await db.execute(text("""
        SELECT id, facility_id, txn_date, txn_type, amount, reference, source,
               notes, confirmed_by, percent_complete, created_at,
               statement_id, funds_entry_id, funds_notice_id
        FROM core.facility_transactions
        WHERE facility_id=:facility_id AND txn_type IN ('draw','repayment')
        ORDER BY txn_date, created_at, id
    """), {"facility_id": facility["id"]})).mappings().all()
    draws = repayments = running = Decimal("0.00")
    items = []
    for row in rows:
        amount = Decimal(row["amount"])
        if row["txn_type"] == "draw":
            draws += amount
            running += amount
        else:
            repayments += amount
            running -= amount
        items.append(FacilityDrawOut(**dict(row), running_total=running, can_delete=can_delete_transaction(row)))
    bank = facility["already_drawn"]
    return FacilityDrawHistory(
        facility_id=facility["id"], lender_type=facility["lender_type"], already_drawn=bank,
        sum_of_draws=draws, sum_of_repayments=repayments, net_draws=running,
        difference_from_already_drawn=None if bank is None else Decimal(bank)-draws,
        items=items,
    )


async def get_history(db: AsyncSession, facility_id: UUID) -> FacilityDrawHistory:
    return await _history(db, await _facility(db, facility_id))


async def _existing_id(db, params):
    # PostgreSQL's existing unique key treats NULL references as distinct. New
    # writes canonicalize missing references to '', and also recognize legacy NULL.
    return (await db.execute(text("""
        SELECT id FROM core.facility_transactions
        WHERE facility_id=:facility_id AND txn_date=:txn_date AND amount=:amount
          AND COALESCE(reference, '')=:reference
        ORDER BY created_at, id LIMIT 1
    """), params)).scalar_one_or_none()


async def create_history(db: AsyncSession, facility_id: UUID, records: list[FacilityDrawCreate]) -> FacilityDrawImportOut:
    try:
        # Serializes manual batches, including optional-reference retries.
        facility = await _facility(db, facility_id, write=True)
        results = []
        for record in records:
            params = record.model_dump()
            params.update(id=uuid4(), facility_id=facility_id,
                          source=record.source or ("scu_confirmation" if facility["lender_type"] == "SCU" else "manual"))
            existing = await _existing_id(db, params)
            if existing:
                results.append(DrawImportResult(status="skipped", txn_id=existing))
                continue
            inserted = (await db.execute(text("""
                INSERT INTO core.facility_transactions
                    (id, facility_id, txn_date, txn_type, amount, reference, source, notes, confirmed_by, percent_complete)
                VALUES (:id, :facility_id, :txn_date, :txn_type, :amount, :reference, :source, :notes, :confirmed_by, :percent_complete)
                ON CONFLICT ON CONSTRAINT uq_facility_transactions_identity DO NOTHING
                RETURNING id
            """), params)).scalar_one_or_none()
            txn_id = inserted or await _existing_id(db, params)
            if txn_id is None:
                raise HTTPException(409, "Transaction identity changed during import; retry the batch")
            results.append(DrawImportResult(status="created" if inserted else "skipped", txn_id=txn_id))
        history = await _history(db, facility)
        await db.commit()
        created = sum(item.status == "created" for item in results)
        return FacilityDrawImportOut(facility_id=facility_id, created=created, skipped=len(results)-created, results=results, history=history)
    except Exception:
        await db.rollback()
        raise


async def delete_history(db: AsyncSession, facility_id: UUID, txn_id: UUID) -> FacilityDrawDeleteOut:
    try:
        facility = await _facility(db, facility_id, write=True)
        row = (await db.execute(text("""
            SELECT id, source, statement_id, funds_entry_id, funds_notice_id
            FROM core.facility_transactions WHERE facility_id=:facility_id AND id=:txn_id
        """), {"facility_id": facility_id, "txn_id": txn_id})).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "Draw transaction not found in this facility")
        if not can_delete_transaction(row):
            raise HTTPException(409, "Imported statement/lawyer transactions must be managed in their original workflow")
        await db.execute(text("DELETE FROM core.facility_transactions WHERE facility_id=:facility_id AND id=:txn_id"), {"facility_id": facility_id, "txn_id": txn_id})
        history = await _history(db, facility)
        await db.commit()
        return FacilityDrawDeleteOut(deleted=True, txn_id=txn_id, history=history)
    except Exception:
        await db.rollback()
        raise
