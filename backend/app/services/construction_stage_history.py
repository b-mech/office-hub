from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_stage_change(
    db: AsyncSession,
    *,
    property_id: UUID,
    incoming_stage: str | None,
    synced_at: datetime,
) -> bool:
    if incoming_stage is None:
        return False

    previous_stage = (
        await db.execute(
            text(
                """
                SELECT stage_clean
                FROM documents.construction_stage_sync
                WHERE property_id = :property_id
                ORDER BY last_synced_at DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"property_id": property_id},
        )
    ).scalar_one_or_none()
    if previous_stage == incoming_stage:
        return False

    await db.execute(
        text(
            """
            INSERT INTO documents.construction_stage_history (
                property_id, previous_stage, new_stage, changed_at, synced_at
            )
            VALUES (
                :property_id, :previous_stage, :new_stage, :synced_at, :synced_at
            )
            """
        ),
        {
            "property_id": property_id,
            "previous_stage": previous_stage,
            "new_stage": incoming_stage,
            "synced_at": synced_at,
        },
    )
    return True


async def list_stage_history(db: AsyncSession, property_id: UUID) -> list[dict[str, object]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, property_id, previous_stage, new_stage, changed_at, synced_at
                FROM documents.construction_stage_history
                WHERE property_id = :property_id
                ORDER BY changed_at DESC, id DESC
                """
            ),
            {"property_id": property_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]
