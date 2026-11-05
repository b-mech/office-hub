from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.addresses import normalize_address
from app.models.core import Lot
from app.models.core import LotTriggerType
from app.models.financing import Property
from app.models.sales import SalesAgreement


def construction_trigger(sold_or_spec: str | None, address: str) -> LotTriggerType | None:
    """Read the construction tracker labels before address annotations are stripped."""
    labels = f"{sold_or_spec or ''} {address}".upper()
    if re.search(r"\bSHOW\s*HOME\b", labels):
        return LotTriggerType.SHOWHOME
    if re.search(r"\bSPEC\b", labels):
        return LotTriggerType.SPEC
    return None


def maybe_activate_lot(lot: Lot, trigger: LotTriggerType) -> bool:
    if lot.trigger_type is not None or lot.cancelled or lot.property_id is None:
        return False
    lot.trigger_type = trigger
    return True


async def activate_from_construction_stage(
    db: AsyncSession,
    *,
    property_id: UUID | None,
    address: str,
    sold_or_spec: str | None,
) -> bool:
    trigger = construction_trigger(sold_or_spec, address)
    if trigger is None or property_id is None:
        return False

    normalized = normalize_address(address)
    if not normalized.canonical_key or not normalized.street_number:
        return False

    # A tracker address is a display field. Require one canonical lot match.
    possible_lots = list((await db.scalars(
        select(Lot).where(or_(
            Lot.property_id == property_id,
            Lot.civic_address.ilike(f"{normalized.street_number}%"),
        ))
    )).all())
    lots = [
        lot for lot in possible_lots
        if lot.civic_address
        and normalize_address(lot.civic_address).canonical_key == normalized.canonical_key
    ]
    if len(lots) != 1:
        return False

    lot = (await db.scalars(select(Lot).where(Lot.id == lots[0].id).with_for_update())).one()
    if lot.trigger_type is not None or lot.cancelled:
        return False

    # An existing sale agreement belongs to the OTP promotion path.
    sale_id = await db.scalar(select(SalesAgreement.id).where(SalesAgreement.lot_id == lot.id).limit(1))
    if sale_id is not None:
        return False

    if lot.property_id is None:
        possible_properties = list((await db.scalars(
            select(Property).where(or_(
                Property.canonical_address_key == normalized.canonical_key,
                Property.address.ilike(f"{normalized.street_number}%"),
            ))
        )).all())
        properties = {
            item.id: item for item in possible_properties
            if normalize_address(item.address).canonical_key == normalized.canonical_key
        }
        if len(properties) != 1 or property_id not in properties:
            return False
        linked_lot_id = await db.scalar(
            select(Lot.id).where(Lot.property_id == property_id).limit(1)
        )
        if linked_lot_id is not None and linked_lot_id != lot.id:
            return False
        lot.property_id = property_id
    elif lot.property_id != property_id:
        return False

    return maybe_activate_lot(lot, trigger)
