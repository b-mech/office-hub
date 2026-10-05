from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import User


class UserLookupClient(Protocol):
    async def users_lookupByEmail(self, **kwargs: object) -> object: ...


async def resolve_slack_user(
    db: AsyncSession,
    client: UserLookupClient,
    slack_user_id: str,
) -> User | None:
    linked = await db.scalar(
        select(User).where(User.slack_user_id == slack_user_id, User.is_active.is_(True))
    )
    if linked is not None:
        return linked
    candidates = list(
        (
            await db.scalars(
                select(User)
                .where(User.slack_user_id.is_(None), User.is_active.is_(True))
                .order_by(User.email)
            )
        ).all()
    )
    matched = None
    for candidate in candidates:
        try:
            response = await client.users_lookupByEmail(email=candidate.email)
            payload = dict(response)  # type: ignore[arg-type]
            slack_id = str(dict(payload.get("user") or {}).get("id") or "")
        except Exception:
            continue
        if not slack_id:
            continue
        candidate.slack_user_id = slack_id
        if slack_id == slack_user_id:
            matched = candidate
    await db.flush()
    return matched
