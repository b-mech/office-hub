from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.funds_intake import _money, resolve_legal_folder
from app.services.funds_posting import _resolve_discharge_facility, post_confirmed_notice


def test_discharge_requires_unique_facility_reference_or_lender() -> None:
    one = SimpleNamespace(id=uuid4(), facility_key="PRO-999", account_number=None,
                          lender="PRO", lender_type="PRO", lender_name="PRO Mortgage")
    two = SimpleNamespace(id=uuid4(), facility_key="SCU-999", account_number=None,
                          lender="SCU", lender_type="SCU", lender_name="Steinbach Credit Union")
    assert _resolve_discharge_facility([one, two], {"facility_reference": "PRO-999"}) is one
    assert _resolve_discharge_facility([one, two], {"lender": "Steinbach Credit Union"}) is two
    assert _resolve_discharge_facility([one, two], {"lender": "unknown"}) is None
    assert _resolve_discharge_facility([one, one], {"lender": "PRO Mortgage"}) is None


def test_money_keeps_cents_and_rejects_negative_or_missing_values() -> None:
    assert _money("$11,394.86") == Decimal("11394.86")
    assert _money("-1.00") is None
    assert _money(None) is None


def test_legal_folder_requires_exact_match_beneath_verified_root() -> None:
    correct = SimpleNamespace(id="353244169629", name="Ramona Gallos Way, 154",
                              path_collection={"entries": [{"id": "210783521222"}]})
    wrong_root = SimpleNamespace(id="other", name=correct.name,
                                 path_collection={"entries": [{"id": "production"}]})
    client = SimpleNamespace(search=lambda: SimpleNamespace(query=lambda **_kwargs: [correct, wrong_root]),
                             folder=lambda value: value)
    assert resolve_legal_folder(client, "154 Ramona Gallos Way") == correct.id


@pytest.mark.asyncio
async def test_multi_entry_notice_cannot_post_until_every_entry_is_confirmed() -> None:
    notice_id = uuid4()
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=notice_id)
    db.scalars.return_value = SimpleNamespace(all=lambda: [
        SimpleNamespace(status="confirmed"), SimpleNamespace(status="pending_review")])
    with pytest.raises(ValueError, match="Every entry"):
        await post_confirmed_notice(db, notice_id)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_cannot_post_while_an_attachment_has_not_been_extracted() -> None:
    notice_id = uuid4()
    attachment_id = uuid4()
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=notice_id)
    db.scalars.side_effect = [
        SimpleNamespace(all=lambda: [SimpleNamespace(status="confirmed", attachment_id=attachment_id)]),
        SimpleNamespace(all=lambda: [SimpleNamespace(id=attachment_id, extraction_status="pending")]),
    ]
    with pytest.raises(ValueError, match="finish extraction"):
        await post_confirmed_notice(db, notice_id)
    db.commit.assert_not_awaited()
