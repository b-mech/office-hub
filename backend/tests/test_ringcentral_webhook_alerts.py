from __future__ import annotations

import logging

import pytest

from app.core.config import settings
from app.services.maintenance.webhook_alerts import alert_ringcentral_webhook_failure


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool, **_kwargs: object) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
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
async def test_webhook_failure_alert_is_rate_limited_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "slack_bot_token", "configured")
    monkeypatch.setattr(settings, "staging_slack_channel_id", "C-STAGING")
    redis = FakeRedis()
    slack = RecordingSlack()

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        first = await alert_ringcentral_webhook_failure(
            403,
            "validation token mismatched",
            redis=redis,  # type: ignore[arg-type]
            client=slack,  # type: ignore[arg-type]
        )
        second = await alert_ringcentral_webhook_failure(
            403,
            "validation token mismatched",
            redis=redis,  # type: ignore[arg-type]
            client=slack,  # type: ignore[arg-type]
        )

    assert first
    assert not second
    assert len(slack.messages) == 1
    assert "HTTP 403" in slack.messages[0][1]
    assert "validation token mismatched" in slack.messages[0][1]
    assert "Rejected RingCentral webhook: status=403 reason=validation token mismatched" in caplog.text
