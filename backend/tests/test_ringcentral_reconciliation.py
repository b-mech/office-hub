from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

import pytest

from app.core.config import settings
from app.services.maintenance.notifier import NoopMaintenanceNotifier
from app.services.maintenance.ringcentral_reconciliation import reconcile_ringcentral_messages
from app.services.maintenance.sms.providers import FakeProvider
from app.workers.celery_app import celery_app


NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


class ScalarResult:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def all(self) -> list[str]:
        return self.values


class FakeDb:
    def __init__(self, existing: list[str]) -> None:
        self.existing = existing
        self.flushed = False

    async def scalars(self, _statement: object) -> ScalarResult:
        return ScalarResult(self.existing)

    async def flush(self) -> None:
        self.flushed = True


class FakeMessageStore:
    def __init__(self, records: list[Mapping[str, object]]) -> None:
        self.records = records
        self.window: tuple[datetime, datetime] | None = None

    async def list_inbound_messages(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> list[Mapping[str, object]]:
        self.window = (date_from, date_to)
        return list(self.records)


def message(message_id: str, *, to: str = "+12042598093") -> dict[str, object]:
    return {
        "id": message_id,
        "creationTime": "2026-10-08T14:55:00.000Z",
        "direction": "Inbound",
        "type": "SMS",
        "from": {"phoneNumber": "+12048904781"},
        "to": [{"phoneNumber": to, "target": True}],
        "subject": "Status update",
        "attachments": [],
    }


@pytest.mark.asyncio
async def test_reconciliation_ingests_only_missing_messages_for_configured_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ringcentral_from_number", "+12042598093")
    received: list[tuple[str, datetime]] = []

    async def record_receive(
        _db: object,
        _provider: object,
        _notifier: object,
        form: Mapping[str, str],
        *,
        now: datetime,
    ) -> object:
        received.append((form["MessageSid"], now))
        return object()

    monkeypatch.setattr(
        "app.services.maintenance.ringcentral_reconciliation.receive_sms",
        record_receive,
    )
    store = FakeMessageStore(
        [message("existing"), message("missing"), message("other-number", to="+12045550000")]
    )
    db = FakeDb(["existing"])

    result = await reconcile_ringcentral_messages(
        db,  # type: ignore[arg-type]
        store,
        NoopMaintenanceNotifier(),
        media_provider=FakeProvider(),
        now=NOW,
    )

    assert received == [("missing", datetime(2026, 10, 8, 14, 55, tzinfo=timezone.utc))]
    assert result.scanned == 3
    assert result.ingested == 1
    assert result.existing == 1
    assert result.ignored == 1
    assert db.flushed
    assert store.window == (
        datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc),
        NOW,
    )


def test_reconciliation_is_scheduled_every_five_minutes() -> None:
    schedule = celery_app.conf.beat_schedule["maintenance-reconcile-ringcentral-messages"]
    assert schedule["task"] == "maintenance.reconcile_ringcentral_messages"
    assert schedule["schedule"] == 300.0
