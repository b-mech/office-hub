from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintUnitToken, MaintWorkOrder


@dataclass(frozen=True)
class RawToken:
    value: str
    digest: str


def generate_token() -> RawToken:
    value = secrets.token_urlsafe(32)
    return RawToken(value=value, digest=hash_token(value))


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_matches(value: str, expected_digest: str) -> bool:
    return hmac.compare_digest(hash_token(value), expected_digest)


async def rotate_unit_token(db: AsyncSession, unit_id: int, created_by: UUID | None) -> tuple[MaintUnitToken, str]:
    now = datetime.now(timezone.utc)
    current = await db.scalar(
        select(MaintUnitToken)
        .where(MaintUnitToken.unit_id == unit_id, MaintUnitToken.revoked_at.is_(None))
        .with_for_update()
    )
    if current is not None:
        current.revoked_at = now
        # Clear the partial unique index before inserting the replacement.
        await db.flush()
    raw = generate_token()
    record = MaintUnitToken(unit_id=unit_id, token_hash=raw.digest, created_by=created_by, created_at=now)
    db.add(record)
    await db.flush()
    return record, raw.value


def rotate_work_order_token(work_order: MaintWorkOrder) -> str:
    raw = generate_token()
    work_order.access_token_hash = raw.digest
    return raw.value
