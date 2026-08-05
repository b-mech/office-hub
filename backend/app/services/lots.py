from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Lot


async def set_lot_hold(db: AsyncSession, lot_id: UUID, *, on_hold: bool) -> Lot | None:
    lot = await db.scalar(select(Lot).where(Lot.id == lot_id).with_for_update())
    if lot is None:
        return None
    lot.on_hold = on_hold
    await db.commit()
    await db.refresh(lot)
    return lot


async def set_lot_cancelled(db: AsyncSession, lot_id: UUID, *, cancelled: bool) -> Lot | None:
    lot = await db.scalar(select(Lot).where(Lot.id == lot_id).with_for_update())
    if lot is None:
        return None
    lot.cancelled = cancelled
    await db.commit()
    await db.refresh(lot)
    return lot
