from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fakeredis.aioredis import FakeRedis

from app.core.config import settings
from app.services.maintenance.subscription_alerts import (
    alert_subscription_renewal_status,
    subscription_alert_state_key,
)

NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)
CALLBACK = "https://staging.invalid/api/webhooks/ringcentral/sms"


class RecordingSlack:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def post_message(self, channel: str, text: str) -> dict[str, object]:
        self.messages.append((channel, text))
        return {"ok": True}


@pytest.fixture(autouse=True)
def alert_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "staging_slack_channel_id", "C-STAGING")
    monkeypatch.setattr(settings, "public_base_url", "https://staging.invalid")


async def observe(redis: FakeRedis, slack: RecordingSlack, *, healthy: bool = False,
                  at: datetime = NOW, callback: str = CALLBACK, detail: str = "HTTP 404") -> bool:
    return await alert_subscription_renewal_status(
        healthy=healthy, callback_url=callback, detail=detail,
        redis=redis, client=slack, now=at,
    )


@pytest.mark.asyncio
async def test_first_healthy_observation_is_silent_then_failure_is_announced() -> None:
    redis = FakeRedis(decode_responses=True)
    slack = RecordingSlack()
    assert not await observe(redis, slack, healthy=True)
    assert await redis.hget(subscription_alert_state_key(CALLBACK), "status") == "ok"
    assert slack.messages == []
    assert await observe(redis, slack, at=NOW + timedelta(hours=1))
    assert "renewal failed in staging" in slack.messages[0][1]
    assert await redis.ttl(subscription_alert_state_key(CALLBACK)) == -1


@pytest.mark.asyncio
async def test_unknown_first_failure_and_exact_24_hour_reminder_boundary() -> None:
    redis = FakeRedis()
    slack = RecordingSlack()
    assert await observe(redis, slack)
    for hour in range(1, 24):
        assert not await observe(redis, slack, at=NOW + timedelta(hours=hour), detail="different safe error")
    assert not await observe(redis, slack, at=NOW + timedelta(seconds=86399))
    assert len(slack.messages) == 1
    assert await observe(redis, slack, at=NOW + timedelta(hours=24))
    assert "24-hour reminder" in slack.messages[-1][1]
    assert not await observe(redis, slack, at=NOW + timedelta(hours=24, seconds=1))
    assert not await observe(redis, slack, at=NOW + timedelta(hours=48, microseconds=-1))
    assert await observe(redis, slack, at=NOW + timedelta(hours=48))
    assert len(slack.messages) == 3


@pytest.mark.asyncio
async def test_recovery_once_and_new_failure_transition_is_not_rate_limited() -> None:
    redis = FakeRedis()
    slack = RecordingSlack()
    assert await observe(redis, slack)
    assert await observe(redis, slack, healthy=True, at=NOW + timedelta(minutes=1))
    assert "recovered in staging" in slack.messages[-1][1]
    assert not await observe(redis, slack, healthy=True, at=NOW + timedelta(minutes=2))
    assert await observe(redis, slack, at=NOW + timedelta(minutes=3))
    assert len(slack.messages) == 3


@pytest.mark.asyncio
async def test_atomic_claim_across_64_concurrent_workers_for_each_transition() -> None:
    server = fakeredis.FakeServer()
    stores = [FakeRedis(server=server) for _ in range(64)]
    slack = RecordingSlack()
    try:
        assert sum(await asyncio.gather(*(observe(r, slack) for r in stores))) == 1
        assert sum(await asyncio.gather(*(observe(r, slack, at=NOW + timedelta(hours=24)) for r in stores))) == 1
        assert sum(await asyncio.gather(*(observe(r, slack, healthy=True, at=NOW + timedelta(hours=25)) for r in stores))) == 1
        assert len(slack.messages) == 3
    finally:
        await asyncio.gather(*(r.aclose() for r in stores))


@pytest.mark.asyncio
async def test_new_worker_connection_after_restart_reuses_persistent_state() -> None:
    # The broker/store remains up; discard all client state as on worker restart.
    server = fakeredis.FakeServer()
    slack = RecordingSlack()
    old_worker = FakeRedis(server=server)
    assert await observe(old_worker, slack)
    await old_worker.aclose()
    new_worker = FakeRedis(server=server)
    assert not await observe(new_worker, slack, at=NOW + timedelta(hours=1))
    assert await new_worker.ttl(subscription_alert_state_key(CALLBACK)) == -1
    assert await observe(new_worker, slack, at=NOW + timedelta(hours=24))
    await new_worker.aclose()
    third_worker = FakeRedis(server=server)
    assert await observe(third_worker, slack, healthy=True, at=NOW + timedelta(hours=25))
    await third_worker.aclose()
    fourth_worker = FakeRedis(server=server)
    assert not await observe(fourth_worker, slack, healthy=True, at=NOW + timedelta(hours=26))
    assert len(slack.messages) == 3
    await fourth_worker.aclose()


@pytest.mark.asyncio
async def test_environment_and_callback_scoping(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    slack = RecordingSlack()
    staging_key = subscription_alert_state_key(CALLBACK)
    assert await observe(redis, slack)
    monkeypatch.setattr(settings, "environment", "production")
    assert subscription_alert_state_key(CALLBACK) != staging_key
    assert await observe(redis, slack)
    assert await observe(redis, slack, callback="https://other.invalid/api/webhooks/ringcentral/sms")
    assert len(slack.messages) == 3


@pytest.mark.asyncio
async def test_older_overlapping_run_cannot_undo_newer_recovery() -> None:
    redis = FakeRedis(decode_responses=True)
    slack = RecordingSlack()
    assert await observe(redis, slack)
    assert await observe(redis, slack, healthy=True, at=NOW + timedelta(hours=2))
    assert not await observe(redis, slack, at=NOW + timedelta(hours=1))
    assert await redis.hget(subscription_alert_state_key(CALLBACK), "status") == "ok"
    assert len(slack.messages) == 2


@pytest.mark.asyncio
async def test_persistence_unavailable_fails_closed_without_sensitive_logging(caplog: pytest.LogCaptureFixture) -> None:
    class UnavailableRedis(FakeRedis):
        async def eval(self, *_args: object, **_kwargs: object) -> object:
            raise ConnectionError("private-value-must-not-be-logged")

    slack = RecordingSlack()
    assert not await observe(UnavailableRedis(), slack)
    assert slack.messages == []
    assert "ConnectionError" in caplog.text
    assert "private-value-must-not-be-logged" not in caplog.text


@pytest.mark.asyncio
async def test_ambiguous_delivery_keeps_claim_instead_of_retry_storm(caplog: pytest.LogCaptureFixture) -> None:
    class AmbiguousSlack(RecordingSlack):
        async def post_message(self, channel: str, text: str) -> dict[str, object]:
            await super().post_message(channel, text)
            raise RuntimeError("private-slack-response")

    redis = FakeRedis()
    slack = AmbiguousSlack()
    assert not await observe(redis, slack)
    assert not await observe(redis, slack, at=NOW + timedelta(hours=1))
    assert len(slack.messages) == 1
    assert not await observe(redis, slack, at=NOW + timedelta(hours=24))
    assert len(slack.messages) == 2
    assert "private-slack-response" not in caplog.text


@pytest.mark.asyncio
async def test_slack_disabled_still_records_state_and_does_not_consume_first_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "slack_bot_token", "")
    redis = FakeRedis(decode_responses=True)
    for healthy, hour in [(True, 0), (False, 1)]:
        assert not await alert_subscription_renewal_status(
            healthy=healthy, callback_url=CALLBACK, detail="HTTP 404", redis=redis,
            now=NOW + timedelta(hours=hour),
        )
    key = subscription_alert_state_key(CALLBACK)
    assert await redis.hget(key, "status") == "failing"
    assert await redis.hget(key, "last_alert_at") is None
    slack = RecordingSlack()
    assert await observe(redis, slack, at=NOW + timedelta(hours=2))
    assert "renewal failed" in slack.messages[0][1]


@pytest.mark.asyncio
async def test_health_monitor_and_job_share_claims_and_recovery() -> None:
    from app.services.maintenance.scheduler_health import (
        alert_if_subscription_scheduler_stale,
        record_subscription_scheduler_heartbeat,
    )

    redis = FakeRedis(decode_responses=True)
    slack = RecordingSlack()
    assert await observe(redis, slack)
    await record_subscription_scheduler_heartbeat(
        expires_at=NOW + timedelta(days=7), healthy=False, detail="HTTP 404", redis=redis, now=NOW,
    )
    assert not await alert_if_subscription_scheduler_stale(redis=redis, client=slack, now=NOW + timedelta(hours=1))
    assert await alert_if_subscription_scheduler_stale(redis=redis, client=slack, now=NOW + timedelta(hours=24))
    assert not await observe(redis, slack, at=NOW + timedelta(hours=24, seconds=1))
    await record_subscription_scheduler_heartbeat(
        expires_at=NOW + timedelta(days=7), healthy=True, detail="ok", redis=redis,
        now=NOW + timedelta(hours=25),
    )
    assert await alert_if_subscription_scheduler_stale(redis=redis, client=slack, now=NOW + timedelta(hours=25))
    assert not await observe(redis, slack, healthy=True, at=NOW + timedelta(hours=25, seconds=1))
    assert len(slack.messages) == 3


@pytest.mark.asyncio
async def test_monitor_restart_cannot_bypass_persistent_throttle() -> None:
    from app.services.maintenance.scheduler_health import alert_if_subscription_scheduler_stale

    server = fakeredis.FakeServer()
    slack = RecordingSlack()
    old = FakeRedis(server=server)
    assert await alert_if_subscription_scheduler_stale(redis=old, client=slack, now=NOW)
    await old.aclose()
    new = FakeRedis(server=server)
    assert not await alert_if_subscription_scheduler_stale(redis=new, client=slack, now=NOW + timedelta(hours=1))
    assert len(slack.messages) == 1
    await new.aclose()


@pytest.mark.asyncio
async def test_invalid_state_client_configuration_is_also_fail_closed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    from app.services.maintenance import subscription_alerts

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise ValueError("private-invalid-connection-value")

    monkeypatch.setattr(subscription_alerts.Redis, "from_url", unavailable)
    slack = RecordingSlack()
    assert not await alert_subscription_renewal_status(
        healthy=False, callback_url=CALLBACK, detail="HTTP 404", client=slack, now=NOW,
    )
    assert slack.messages == []
    assert "private-invalid-connection-value" not in caplog.text
