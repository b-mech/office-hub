from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.land import Agreement
from app.models.sales import SalesAgreement
from app.services.promotion import PromotionAlreadyExistsError
from app.services.promotion import PromotionService


@pytest.mark.asyncio
@pytest.mark.parametrize("agreement_model", [Agreement, SalesAgreement])
async def test_duplicate_document_is_rejected_with_existing_agreement_id(
    agreement_model: type[Agreement] | type[SalesAgreement],
) -> None:
    document_id = uuid4()
    agreement_id = uuid4()
    db = AsyncMock()
    db.scalar.return_value = agreement_id

    with pytest.raises(PromotionAlreadyExistsError) as caught:
        await PromotionService(db)._ensure_not_already_promoted(document_id, agreement_model)

    assert caught.value.document_id == document_id
    assert caught.value.agreement_id == agreement_id
    assert str(agreement_id) in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("agreement_model", [Agreement, SalesAgreement])
async def test_unpromoted_document_passes_guard(
    agreement_model: type[Agreement] | type[SalesAgreement],
) -> None:
    db = AsyncMock()
    db.scalar.return_value = None

    await PromotionService(db)._ensure_not_already_promoted(uuid4(), agreement_model)
