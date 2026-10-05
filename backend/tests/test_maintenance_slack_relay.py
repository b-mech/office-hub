from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.core import UserRole
from app.models.maintenance import MaintParty, MaintStatus
from app.services.maintenance.slack.relay import (
    BLOCKED_RELAY_STATUSES,
    handle_thread_message,
    internal_note_body,
)


def test_internal_note_prefixes_are_trimmed_and_case_insensitive() -> None:
    assert internal_note_body("  // check lease first ", MaintParty.TENANT) == "check lease first"
    assert internal_note_body(" NOTE: Call owner ", MaintParty.VENDOR) == "Call owner"
    assert internal_note_body("note:Call owner", MaintParty.TENANT) == "Call owner"
    assert internal_note_body("relay this", MaintParty.TENANT) is None


def test_staff_work_order_threads_are_always_internal() -> None:
    assert internal_note_body("This never becomes SMS", MaintParty.STAFF) == "This never becomes SMS"


def test_resolved_relay_is_allowed_but_terminal_states_are_blocked() -> None:
    assert MaintStatus.RESOLVED not in BLOCKED_RELAY_STATUSES
    assert BLOCKED_RELAY_STATUSES == {
        MaintStatus.CLOSED,
        MaintStatus.CANCELLED,
        MaintStatus.DUPLICATE,
    }


class Session:
    def __init__(self, values):
        self.values = iter(values)
        self.added = []

    async def scalar(self, statement): return next(self.values)
    def add(self, value): self.added.append(value)
    async def flush(self): return None


class Client:
    def __init__(self): self.reactions = []; self.messages = []
    async def reactions_add(self, **kwargs): self.reactions.append(kwargs); return {}
    async def chat_postEphemeral(self, **kwargs): self.messages.append(kwargs); return {}
    async def chat_postMessage(self, **kwargs): self.messages.append(kwargs); return {}
    async def users_lookupByEmail(self, **kwargs): return {}


@pytest.mark.asyncio
async def test_prefixed_reply_logs_internal_event_and_lock_reaction(monkeypatch) -> None:
    monkeypatch.setattr(settings, "slack_tickets_channel_id", "C-TICKETS")
    monkeypatch.setattr(settings, "slack_emergency_channel_id", "C-EMERGENCY")
    card = SimpleNamespace(
        ticket_id=uuid4(),
        work_order_id=None,
        channel_id="C-TICKETS",
        message_ts="100.1",
        thread_party=MaintParty.TENANT,
    )
    user = SimpleNamespace(
        id=uuid4(),
        role=UserRole.STAFF,
        is_active=True,
        permissions={"maintenance": "viewer"},
        slack_user_id="U1",
    )
    db = Session([card, user])
    client = Client()
    result = await handle_thread_message(
        db,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        {
            "channel": "C-TICKETS",
            "thread_ts": "100.1",
            "ts": "100.2",
            "user": "U1",
            "text": "  note: Check the lease first  ",
        },
    )
    assert result.kind == "internal"
    assert db.added[-1].event_type == "internal_note"
    assert db.added[-1].body == "Check the lease first"
    assert client.reactions[-1]["name"] == "lock"


@pytest.mark.asyncio
async def test_staff_work_order_reply_is_internal_without_prefix(monkeypatch) -> None:
    monkeypatch.setattr(settings, "slack_tickets_channel_id", "C-TICKETS")
    monkeypatch.setattr(settings, "slack_emergency_channel_id", "C-EMERGENCY")
    card = SimpleNamespace(
        ticket_id=uuid4(),
        work_order_id=uuid4(),
        channel_id="C-TICKETS",
        message_ts="200.1",
        thread_party=MaintParty.STAFF,
    )
    user = SimpleNamespace(
        id=uuid4(),
        role=UserRole.ADMIN,
        is_active=True,
        permissions={},
        slack_user_id="U2",
    )
    db = Session([card, user])
    result = await handle_thread_message(
        db,  # type: ignore[arg-type]
        Client(),  # type: ignore[arg-type]
        {"channel": "C-TICKETS", "thread_ts": "200.1", "ts": "200.2", "user": "U2", "text": "Internal progress update"},
    )
    assert result.kind == "internal"
    assert db.added[-1].body == "Internal progress update"
