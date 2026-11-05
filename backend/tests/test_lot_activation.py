from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models.core import LotTriggerType
from app.services.lot_activation import activate_from_construction_stage
from app.services.lot_activation import construction_trigger


class _Rows:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def all(self) -> list[object]:
        return self.items

    def one(self) -> object:
        return self.items[0]


class LotActivationTests(unittest.IsolatedAsyncioTestCase):
    async def _activate(
        self,
        *,
        trigger_type: LotTriggerType | None = None,
        cancelled: bool = False,
        linked: bool = True,
        properties: int = 1,
        sale_agreement: bool = False,
        sold_or_spec: str = "SPEC",
        address: str = "52 Ash Cove",
    ) -> tuple[bool, SimpleNamespace, SimpleNamespace]:
        property_id = uuid4()
        lot = SimpleNamespace(
            id=uuid4(),
            civic_address="52 Ash Cove",
            property_id=property_id if linked else None,
            trigger_type=trigger_type,
            cancelled=cancelled,
        )
        candidates = [
            SimpleNamespace(id=property_id if index == 0 else uuid4(), address="52 Ash Cove")
            for index in range(properties)
        ]
        db = SimpleNamespace(
            scalars=AsyncMock(side_effect=[_Rows([lot]), _Rows([lot]), _Rows(candidates)]),
            scalar=AsyncMock(side_effect=[uuid4() if sale_agreement else None, None]),
        )
        result = await activate_from_construction_stage(
            db, property_id=property_id, address=address, sold_or_spec=sold_or_spec,
        )
        return result, lot, db

    async def test_null_trigger_becomes_spec(self) -> None:
        changed, lot, _ = await self._activate()
        self.assertTrue(changed)
        self.assertEqual(LotTriggerType.SPEC, lot.trigger_type)

    async def test_null_trigger_becomes_showhome_from_address(self) -> None:
        changed, lot, _ = await self._activate(
            sold_or_spec="SOLD/SPEC", address="52 Ash Cove - SHOW HOME",
        )
        self.assertTrue(changed)
        self.assertEqual(LotTriggerType.SHOWHOME, lot.trigger_type)

    async def test_showhome_from_tracker_label_takes_precedence(self) -> None:
        changed, lot, _ = await self._activate(sold_or_spec="SPEC / SHOWHOME")
        self.assertTrue(changed)
        self.assertEqual(LotTriggerType.SHOWHOME, lot.trigger_type)

    async def test_existing_otp_is_unchanged(self) -> None:
        changed, lot, _ = await self._activate(trigger_type=LotTriggerType.OTP)
        self.assertFalse(changed)
        self.assertEqual(LotTriggerType.OTP, lot.trigger_type)

    async def test_cancelled_lot_is_skipped(self) -> None:
        changed, lot, _ = await self._activate(cancelled=True)
        self.assertFalse(changed)
        self.assertIsNone(lot.trigger_type)

    async def test_ambiguous_property_does_not_link_or_activate(self) -> None:
        changed, lot, _ = await self._activate(linked=False, properties=2)
        self.assertFalse(changed)
        self.assertIsNone(lot.property_id)
        self.assertIsNone(lot.trigger_type)

    async def test_unambiguous_property_links_before_activation(self) -> None:
        changed, lot, _ = await self._activate(linked=False)
        self.assertTrue(changed)
        self.assertIsNotNone(lot.property_id)
        self.assertEqual(LotTriggerType.SPEC, lot.trigger_type)

    async def test_sale_agreement_reserves_otp_path(self) -> None:
        changed, lot, _ = await self._activate(sale_agreement=True)
        self.assertFalse(changed)
        self.assertIsNone(lot.trigger_type)

    async def test_group_row_without_property_does_not_activate(self) -> None:
        db = SimpleNamespace(scalars=AsyncMock(), scalar=AsyncMock())
        changed = await activate_from_construction_stage(
            db, property_id=None, address="52 Ash Cove - SPEC", sold_or_spec="SPEC",
        )
        self.assertFalse(changed)
        db.scalars.assert_not_awaited()

    def test_plain_sold_does_not_activate(self) -> None:
        self.assertIsNone(construction_trigger("SOLD", "52 Ash Cove"))
