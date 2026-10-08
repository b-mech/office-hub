from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services.maintenance.scheduler_health import subscription_scheduler_health
from app.services.maintenance.subscription_renewal import (
    MultipleActiveRingCentralSubscriptions,
    NoActiveRingCentralSubscription,
    maintain_ringcentral_subscription,
)


NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
CALLBACK = "https://staging.invalid/api/webhooks/ringcentral/sms"
EVENT_FILTER = "/restapi/v1.0/account/123/extension/456/message-store/instant?type=SMS"


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, **_kwargs: object) -> bool:
        self.values[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeProvider:
    def __init__(self, records: list[Mapping[str, object]]) -> None:
        self.records = records
        self.updated: list[tuple[str, str]] = []

    async def list_subscriptions(self) -> list[Mapping[str, object]]:
        return self.records

    async def update_sms_webhook_subscription(
        self,
        subscription_id: str,
        address: str,
    ) -> Mapping[str, object]:
        self.updated.append((subscription_id, address))
        return {
            "id": subscription_id,
            "status": "Active",
            "expirationTime": (NOW + timedelta(days=7)).isoformat(),
        }


class RecordingSlack:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def post_message(self, channel: str, text: str) -> dict[str, object]:
        self.messages.append((channel, text))
        return {"ok": True}


class RecordingProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, callback_url: str, validation_token: str) -> None:
        self.calls.append((callback_url, validation_token))


def subscription(subscription_id: str, expires_at: datetime, *, address: str = CALLBACK) -> dict[str, object]:
    return {
        "id": subscription_id,
        "status": "Active",
        "eventFilters": [EVENT_FILTER],
        "deliveryMode": {"transportType": "WebHook", "address": address},
        "expirationTime": expires_at.isoformat(),
    }


@pytest.fixture(autouse=True)
def renewal_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "public_base_url", "https://staging.invalid")
    monkeypatch.setattr(settings, "staging_slack_channel_id", "C-STAGING")
    monkeypatch.setattr(
        settings,
        "ringcentral_webhook_validation_token",
        SecretStr("validation-secret"),
    )


@pytest.mark.asyncio
async def test_reconciles_matching_subscription_token_and_probes_public_route() -> None:
    provider = FakeProvider([subscription("sub-1", NOW + timedelta(hours=47, minutes=59))])
    redis = FakeRedis()
    probe = RecordingProbe()
    result = await maintain_ringcentral_subscription(
        provider=provider, redis=redis, now=NOW, probe=probe  # type: ignore[arg-type]
    )
    assert result.renewed
    assert result.expires_at == NOW + timedelta(days=7)
    assert provider.updated == [("sub-1", CALLBACK)]
    assert probe.calls == [(CALLBACK, "validation-secret")]
    health = await subscription_scheduler_health(redis=redis, now=NOW)  # type: ignore[arg-type]
    assert health.healthy
    assert health.expires_at == result.expires_at


@pytest.mark.asyncio
async def test_reconciles_token_even_when_expiration_is_not_near() -> None:
    provider = FakeProvider([subscription("sub-1", NOW + timedelta(hours=48))])
    result = await maintain_ringcentral_subscription(
        provider=provider,
        redis=FakeRedis(),  # type: ignore[arg-type]
        now=NOW,
        probe=RecordingProbe(),
    )
    assert result.renewed
    assert provider.updated == [("sub-1", CALLBACK)]


@pytest.mark.asyncio
async def test_existing_duplicates_fail_closed_and_alert() -> None:
    provider = FakeProvider(
        [
            subscription("older", NOW + timedelta(hours=2)),
            subscription("canonical", NOW + timedelta(days=4)),
        ]
    )
    slack = RecordingSlack()
    with pytest.raises(MultipleActiveRingCentralSubscriptions):
        await maintain_ringcentral_subscription(
            provider=provider,
            client=slack,  # type: ignore[arg-type]
            redis=FakeRedis(),  # type: ignore[arg-type]
            now=NOW,
            probe=RecordingProbe(),
        )
    assert provider.updated == []
    assert len(slack.messages) == 1


@pytest.mark.asyncio
async def test_no_active_matching_subscription_alerts_and_marks_health_unhealthy() -> None:
    provider = FakeProvider(
        [subscription("other-environment", NOW + timedelta(days=4), address="https://other.invalid")]
    )
    redis = FakeRedis()
    slack = RecordingSlack()
    with pytest.raises(NoActiveRingCentralSubscription):
        await maintain_ringcentral_subscription(
            provider=provider,
            client=slack,  # type: ignore[arg-type]
            redis=redis,  # type: ignore[arg-type]
            now=NOW,
            probe=RecordingProbe(),
        )
    assert len(slack.messages) == 1
    assert "no active SMS webhook subscription" in slack.messages[0][1]
    health = await subscription_scheduler_health(redis=redis, now=NOW)  # type: ignore[arg-type]
    assert not health.healthy
    assert "no active SMS webhook subscription" in health.detail


@pytest.mark.asyncio
async def test_provider_failure_posts_non_sensitive_slack_alert() -> None:
    class FailingProvider(FakeProvider):
        async def list_subscriptions(self) -> list[Mapping[str, object]]:
            raise RuntimeError("secret provider response")

    slack = RecordingSlack()
    with pytest.raises(RuntimeError, match="secret provider response"):
        await maintain_ringcentral_subscription(
            provider=FailingProvider([]),
            client=slack,  # type: ignore[arg-type]
            redis=FakeRedis(),  # type: ignore[arg-type]
            now=NOW,
            probe=RecordingProbe(),
        )
    assert len(slack.messages) == 1
    assert "RuntimeError" in slack.messages[0][1]
    assert "secret provider response" not in slack.messages[0][1]
