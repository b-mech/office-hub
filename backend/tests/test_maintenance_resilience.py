from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.models.maintenance import MaintDirection, MaintSmsMessage
from app.services.maintenance import emergencies
from app.services.maintenance.notifier import NoopMaintenanceNotifier
from app.services.maintenance.scheduler_health import (
    HEARTBEAT_KEY,
    STALE_ALERT_INTERVAL_SECONDS,
    alert_if_scheduler_stale,
    record_scheduler_heartbeat,
    scheduler_health,
)
from app.services.maintenance.slack.client import HttpSlackClient, StagingSlackChannelBlocked
from app.services.maintenance.sms.outbound import send_due_messages
from app.services.maintenance.sms.providers import FakeProvider, StagingSmsRecipientBlocked


NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)


class RecordingDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1


@pytest.mark.asyncio
async def test_overdue_emergency_skips_intermediate_pages_and_pages_current_stage_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = SimpleNamespace(
        id=uuid4(),
        created_at=NOW,
        is_emergency=True,
        emergency_acked_at=None,
    )
    initial_page = SimpleNamespace(payload={"stage": 0}, created_at=NOW)
    calls: list[int] = []

    async def page(_db, _ticket, *, stage: int, now: datetime) -> bool:
        calls.append(stage)
        assert now == NOW + timedelta(minutes=46)
        return True

    monkeypatch.setattr(emergencies, "page_emergency", page)
    db = RecordingDb()
    count = await emergencies.catch_up_emergency(
        db,  # type: ignore[arg-type]
        ticket,  # type: ignore[arg-type]
        [initial_page],  # type: ignore[list-item]
        checked_at=NOW + timedelta(minutes=46),
        interval=timedelta(minutes=15),
    )

    assert count == 1
    assert calls == [2]
    assert len(db.added) == 1
    skipped = db.added[0]
    assert skipped.event_type == "emergency_paged"  # type: ignore[attr-defined]
    assert skipped.payload == {"stage": 1, "skipped": True, "caught_up_to": 2}  # type: ignore[attr-defined]

    completed_pages = [
        initial_page,
        SimpleNamespace(payload=skipped.payload, created_at=NOW + timedelta(minutes=46)),  # type: ignore[attr-defined]
        SimpleNamespace(payload={"stage": 2}, created_at=NOW + timedelta(minutes=46)),
    ]
    assert await emergencies.catch_up_emergency(
        db,  # type: ignore[arg-type]
        ticket,  # type: ignore[arg-type]
        completed_pages,  # type: ignore[arg-type]
        checked_at=NOW + timedelta(hours=2),
        interval=timedelta(minutes=15),
    ) == 0
    assert calls == [2]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class RecordingSlack:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def post_message(self, channel: str, text: str) -> dict[str, object]:
        self.messages.append((channel, text))
        return {"ok": True}


@pytest.mark.asyncio
async def test_scheduler_heartbeat_and_stale_alert_are_independent_and_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    slack = RecordingSlack()
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(settings, "staging_slack_channel_id", "C-STAGING")

    await record_scheduler_heartbeat(redis=redis, now=NOW)  # type: ignore[arg-type]
    assert (await scheduler_health(redis=redis, now=NOW + timedelta(minutes=4))).healthy  # type: ignore[arg-type]
    assert not (await scheduler_health(redis=redis, now=NOW + timedelta(minutes=6))).healthy  # type: ignore[arg-type]

    assert await alert_if_scheduler_stale(
        redis=redis, client=slack, now=NOW + timedelta(minutes=6)  # type: ignore[arg-type]
    )
    assert not await alert_if_scheduler_stale(
        redis=redis, client=slack, now=NOW + timedelta(minutes=7)  # type: ignore[arg-type]
    )
    assert slack.messages == [
        ("C-STAGING", f"Maintenance escalation scheduler has not run since {NOW.isoformat()}")
    ]
    assert redis.values[HEARTBEAT_KEY] == NOW.isoformat()
    assert STALE_ALERT_INTERVAL_SECONDS in redis.expirations.values()


@pytest.mark.asyncio
async def test_staging_sms_provider_blocks_every_number_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "staging_sms_allowlist", "+12045550100")
    provider = FakeProvider()
    assert await provider.send("+12045550100", "allowed", [])
    with pytest.raises(StagingSmsRecipientBlocked):
        await provider.send("+12045550101", "blocked", [])
    assert [item["to"] for item in provider.sent] == ["+12045550100"]


class ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class SenderSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.added: list[object] = []

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows(self.values)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_blocked_staging_sms_is_logged_as_dropped_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "staging_sms_allowlist", "+12045550100")
    message = MaintSmsMessage(
        direction=MaintDirection.OUTBOUND,
        from_e164="+12045550999",
        to_e164="+12045550101",
        body="must not leave staging",
        media_attachment_ids=[],
        is_automated=True,
        status="pending",
        ticket_id=uuid4(),
    )
    provider = FakeProvider()
    db = SenderSession([message])
    assert await send_due_messages(
        db, provider, NoopMaintenanceNotifier(), now=NOW  # type: ignore[arg-type]
    ) == 1
    assert provider.sent == []
    assert message.status == "cancelled"
    assert message.cancelled_at == NOW
    assert message.error_code == "staging_recipient_blocked"
    assert db.added[0].event_type == "sms_staging_dropped"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_staging_slack_client_allows_only_dedicated_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1.2"})

    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "staging_slack_channel_id", "C-STAGING")
    client = HttpSlackClient("xoxb-test", transport=httpx.MockTransport(handler))
    await client.post_message("C-STAGING", "safe")
    with pytest.raises(StagingSlackChannelBlocked):
        await client.post_message("C-PRODUCTION", "blocked")
    assert len(requests) == 1
