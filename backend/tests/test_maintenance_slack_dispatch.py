from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.maintenance.slack.dispatcher import SlackOutboxDispatcher
from app.services.maintenance.slack.outbox import mark_failed_attempt, retry_after_seconds


NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)


class RateLimited(Exception):
    def __init__(self) -> None:
        self.response = SimpleNamespace(status_code=429, headers={"Retry-After": "37"})


def row(attempts: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        attempts=attempts,
        claimed_at=NOW,
        delivered_at=None,
        failed_at=None,
        last_error=None,
        available_at=NOW,
        updated_at=NOW,
    )


def test_rate_limit_honors_retry_after_without_response_body() -> None:
    error = RateLimited()
    assert retry_after_seconds(error, 1) == 37
    item = row()
    mark_failed_attempt(item, error, now=NOW)
    assert item.available_at == NOW + timedelta(seconds=37)
    assert item.last_error == "RateLimited:429"
    assert item.claimed_at is None


def test_retry_backoff_caps_and_terminal_failure() -> None:
    assert retry_after_seconds(RuntimeError(), 20) == 900
    item = row(attempts=8)
    mark_failed_attempt(item, RuntimeError("secret must not be stored"), now=NOW)
    assert item.failed_at == NOW
    assert item.last_error == "RuntimeError"
    assert "secret" not in item.last_error


class Session:
    def __init__(self, value): self.value = value
    async def get(self, model, identity): return self.value


class Client:
    def __init__(self): self.added = []; self.removed = []
    async def reactions_add(self, **kwargs): self.added.append(kwargs); return {}
    async def reactions_remove(self, **kwargs): self.removed.append(kwargs); return {}


@pytest.mark.asyncio
async def test_sms_reactions_never_claim_delivered() -> None:
    message = SimpleNamespace(
        id=uuid4(),
        status="delivered",
        slack_channel_id="C1",
        slack_ts="100.2",
    )
    client = Client()
    dispatcher = SlackOutboxDispatcher(client)  # type: ignore[arg-type]
    await dispatcher.update_sms_reaction(Session(message), message.id)  # type: ignore[arg-type]
    assert client.added[-1]["name"] == "email"
    assert all(item["name"] != "white_check_mark" for item in client.added)
