from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("MINIO_URL", "http://localhost:9000")
os.environ.setdefault("MINIO_ROOT_USER", "minio")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "minio123")
os.environ.setdefault("IMAP_HOST", "localhost")
os.environ.setdefault("IMAP_USER", "test")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IMAP_FOLDER", "INBOX")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ACTIVE_MODEL_PROVIDER", "claude")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("OFFICE_HUB_API_KEY", "test")
os.environ.setdefault("DEFAULT_ORG_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("ENVIRONMENT", "test")

from app.models.core import Lot, SaleType
from app.models.presales import ApprovalLetterStatus, PresaleApprovalLetter
from app.services import presales


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class PresaleLotLinkingTests(unittest.IsolatedAsyncioTestCase):
    async def test_lot_options_include_presale_and_non_presale_lots(self) -> None:
        presale_lot = SimpleNamespace(
            id=uuid4(),
            civic_address="217 Woodland Way",
            legal_description_normalized="BLK 14 LT 41 PLAN 71499",
            sale_type=SaleType.PRESALE,
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        unflagged_lot = SimpleNamespace(
            id=uuid4(),
            civic_address="48 Woodland Way",
            legal_description_normalized="BLK 1 LT 1 PLAN 1",
            sale_type=None,
            created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        db = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([unflagged_lot, presale_lot])))

        with patch.object(presales, "_buyer_names", AsyncMock(return_value=[])):
            options = await presales.list_extension_lots(db)  # type: ignore[arg-type]

        self.assertEqual([option["id"] for option in options], [str(unflagged_lot.id), str(presale_lot.id)])
        self.assertEqual([option["is_presale"] for option in options], [False, True])

    async def test_link_can_mark_unflagged_lot_as_presale_atomically(self) -> None:
        letter_id = uuid4()
        lot_id = uuid4()
        letter = SimpleNamespace(
            id=letter_id,
            lot_id=None,
            file_sha256=None,
            extracted={},
            needs_manual_entry=False,
            quality_score=None,
            status=ApprovalLetterStatus.PENDING_REVIEW.value,
        )
        lot = SimpleNamespace(id=lot_id, sale_type=None)

        async def get(model: type[object], record_id: object) -> object | None:
            if model is PresaleApprovalLetter and record_id == letter_id:
                return letter
            if model is Lot and record_id == lot_id:
                return lot
            return None

        db = SimpleNamespace(get=AsyncMock(side_effect=get), commit=AsyncMock(), refresh=AsyncMock())
        with (
            patch.object(presales, "populate_lot_realtor", AsyncMock()) as populate_realtor,
            patch.object(presales, "_upsert_review_task", AsyncMock()),
            patch.object(presales, "recompute_readiness", AsyncMock()),
        ):
            updated = await presales.update_letter(
                db,  # type: ignore[arg-type]
                letter_id,
                lot_id=lot_id,
                mark_as_presale=True,
            )

        self.assertIs(updated, letter)
        self.assertEqual(letter.lot_id, lot_id)
        self.assertEqual(lot.sale_type, SaleType.PRESALE)
        populate_realtor.assert_awaited_once_with(db, lot)
        db.commit.assert_awaited_once()

    async def test_link_requires_explicit_mark_intent_for_unflagged_lot(self) -> None:
        letter_id = uuid4()
        lot_id = uuid4()
        letter = SimpleNamespace(id=letter_id, lot_id=None)
        lot = SimpleNamespace(id=lot_id, sale_type=None)

        async def get(model: type[object], record_id: object) -> object | None:
            return letter if model is PresaleApprovalLetter else lot

        db = SimpleNamespace(get=AsyncMock(side_effect=get), commit=AsyncMock())
        with self.assertRaisesRegex(ValueError, "Selected lot is not a presale"):
            await presales.update_letter(db, letter_id, lot_id=lot_id)  # type: ignore[arg-type]
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
