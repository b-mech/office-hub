from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.models.presales import PresaleApprovalLetter
from app.services.extraction.approval_letters import extract_approval_letter
from app.services.minio_financing import get_financing_document
from app.services.presales import apply_extraction_result, mark_extraction_failed, process_expiry_reminders
from app.workers.celery_app import celery_app


@celery_app.task(name="presales.extract_approval_letter")
def extract_approval_letter_task(letter_id: str) -> None:
    asyncio.run(_extract(UUID(letter_id)))


async def _extract(letter_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        letter = await db.get(PresaleApprovalLetter, letter_id)
        if letter is None or not letter.file_key:
            return
        try:
            content = await asyncio.to_thread(get_financing_document, key=letter.file_key)
            result = await extract_approval_letter(content)
            await apply_extraction_result(
                db,
                letter_id,
                payload=result.extracted_payload,
                confidences=result.field_confidences,
            )
        except Exception as exc:
            await mark_extraction_failed(db, letter_id, str(exc))


@celery_app.task(name="presales.expiry_reminders")
def expiry_reminders_task() -> int:
    return asyncio.run(_expiry_reminders())


async def _expiry_reminders() -> int:
    async with AsyncSessionLocal() as db:
        return await process_expiry_reminders(db)
