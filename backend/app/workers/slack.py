from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.maintenance import MaintSlackOutbox
from app.services.maintenance.slack.dispatcher import SlackOutboxDispatcher
from app.services.maintenance.slack.handlers import SlackController, register_handlers
from app.services.maintenance.slack.outbox import (
    claim_due_notifications,
    mark_delivered,
    mark_failed_attempt,
)


logger = logging.getLogger("uvicorn.error")


async def dispatch_outbox_once(dispatcher: SlackOutboxDispatcher) -> int:
    async with AsyncSessionLocal() as db:
        rows = await claim_due_notifications(db)
        ids = [row.id for row in rows]
        await db.commit()
    for row_id in ids:
        async with AsyncSessionLocal() as db:
            row = await db.get(MaintSlackOutbox, row_id)
            if row is None or row.delivered_at is not None or row.failed_at is not None:
                continue
            try:
                await dispatcher.dispatch(db, row)
                mark_delivered(row)
            except Exception as exc:
                mark_failed_attempt(row, exc)
                logger.warning("Slack outbox delivery failed: %s", type(exc).__name__)
            await db.commit()
    return len(ids)


async def outbox_loop(dispatcher: SlackOutboxDispatcher) -> None:
    while True:
        await dispatch_outbox_once(dispatcher)
        await asyncio.sleep(1)


async def main() -> None:
    if not settings.slack_configured:
        raise RuntimeError("Slack worker configuration is incomplete")
    try:
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    except ImportError as exc:
        raise RuntimeError("slack-bolt is not installed") from exc

    app = AsyncApp(token=settings.slack_bot_token)
    register_handlers(app, SlackController())
    dispatcher = SlackOutboxDispatcher(app.client)
    poller = asyncio.create_task(outbox_loop(dispatcher))
    try:
        await AsyncSocketModeHandler(app, settings.slack_app_token).start_async()
    finally:
        poller.cancel()
        await asyncio.gather(poller, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
