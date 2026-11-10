from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import User
from app.services.maintenance.slack.client import SlackClient


async def ensure_slack_user_id(
    db: AsyncSession,
    client: SlackClient,
    user: User,
) -> str | None:
    if user.slack_user_id:
        return user.slack_user_id
    slack_user_id = await client.lookup_user_by_email(user.email)
    if slack_user_id:
        user.slack_user_id = slack_user_id
        await db.flush()
    return slack_user_id
