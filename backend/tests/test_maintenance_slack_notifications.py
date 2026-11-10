from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.services.maintenance.slack.client import HttpSlackClient, SlackApiError
from app.services.maintenance.slack.dispatcher import TicketLinkView, render_link_notification
from app.services.maintenance.slack.outbox import mark_failed_attempt, retry_after_seconds
from app.services.maintenance.slack.users import ensure_slack_user_id


def test_link_notification_contains_operational_fields_and_no_private_content() -> None:
    view = TicketLinkView(
        number="MT-00042",
        unit="Parkview · Unit 3",
        category="Plumbing",
        priority="Urgent",
        link="https://office.invalid/rentals/maintenance/ticket-id",
    )
    text = render_link_notification("💬 Tenant replied", view, ("U123",))
    assert "MT-00042" in text
    assert "Parkview · Unit 3" in text
    assert "Plumbing" in text
    assert "Urgent" in text
    assert "<@U123>" in text
    assert "Alex Tenant" not in text
    assert "+12045550123" not in text
    assert "leaking under the sink" not in text


def test_rate_limit_honors_retry_after_and_terminal_failure() -> None:
    request = httpx.Request("POST", "https://slack.com/api/chat.postMessage")
    response = httpx.Response(429, headers={"Retry-After": "17"}, request=request)
    exc = SlackApiError("rate limited", response)
    assert retry_after_seconds(exc, 1) == 17
    row = SimpleNamespace(
        attempts=8,
        failed_at=None,
        claimed_at=datetime.now(timezone.utc),
        available_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_error=None,
    )
    now = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)
    mark_failed_attempt(row, exc, now=now)
    assert row.failed_at == now
    assert row.claimed_at is None
    assert row.last_error == "SlackApiError:429"


@pytest.mark.asyncio
async def test_http_client_posts_only_text_and_disables_unfurls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1.2"})

    client = HttpSlackClient("xoxb-test", transport=httpx.MockTransport(handler))
    await client.post_message("C123", "Link-only notification")
    assert requests[0].headers["Authorization"] == "Bearer xoxb-test"
    payload = json.loads(requests[0].content)
    assert payload["unfurl_links"] is False
    assert payload["unfurl_media"] is False
    assert "blocks" not in payload


class UserDb:
    def __init__(self) -> None:
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True


class UserClient:
    async def lookup_user_by_email(self, email: str) -> str | None:
        assert email == "staff@example.com"
        return "U-STAFF"


@pytest.mark.asyncio
async def test_slack_user_id_auto_links_by_office_email() -> None:
    user = SimpleNamespace(email="staff@example.com", slack_user_id=None)
    db = UserDb()
    result = await ensure_slack_user_id(db, UserClient(), user)  # type: ignore[arg-type]
    assert result == "U-STAFF"
    assert user.slack_user_id == "U-STAFF"
    assert db.flushed is True


def test_exponential_retry_is_capped() -> None:
    assert retry_after_seconds(RuntimeError(), 1) == 1
    assert retry_after_seconds(RuntimeError(), 20) == 900
