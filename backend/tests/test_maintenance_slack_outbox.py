from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services.maintenance.notifier import OutboxMaintenanceNotifier
from app.services.maintenance.slack.outbox import enqueue_slack_notification


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(statement)


def params(statement: object) -> dict[str, object]:
    return statement.compile(dialect=postgresql.dialect()).params  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_outbox_insert_is_transactional_and_idempotent() -> None:
    db = RecordingSession()
    ticket_id = uuid4()
    await enqueue_slack_notification(
        db,  # type: ignore[arg-type]
        idempotency_key=f"ticket:{ticket_id}:created",
        kind="ticket_created",
        ticket_id=ticket_id,
    )
    assert len(db.statements) == 1
    compiled = str(db.statements[0].compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in compiled
    values = params(db.statements[0])
    assert values["idempotency_key"] == f"ticket:{ticket_id}:created"
    assert values["ticket_id"] == ticket_id


@pytest.mark.asyncio
async def test_notifier_builds_stable_keys_without_storing_phone() -> None:
    db = RecordingSession()
    notifier = OutboxMaintenanceNotifier()
    ticket = SimpleNamespace(id=uuid4())
    message = SimpleNamespace(
        id=uuid4(),
        ticket_id=ticket.id,
        work_order_id=None,
        status="held",
    )
    await notifier.ticket_created(db, ticket)  # type: ignore[arg-type]
    await notifier.inbound_message(db, message, ticket)  # type: ignore[arg-type]
    await notifier.sms_status_changed(db, message)  # type: ignore[arg-type]
    await notifier.opted_out(
        db,  # type: ignore[arg-type]
        "+12045550123",
        source_key=f"sms:{message.id}",
    )
    values = [params(statement) for statement in db.statements]
    assert [item["idempotency_key"] for item in values] == [
        f"ticket:{ticket.id}:created",
        f"sms:{message.id}:inbound",
        f"sms:{message.id}:status:held",
        f"sms:{message.id}:opted-out",
    ]
    assert values[-1]["payload"] == {"phone_last4": "0123"}
    assert "+12045550123" not in repr(values)
