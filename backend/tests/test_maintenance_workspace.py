from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.maintenance import MaintPriority, MaintStatus
from app.services.maintenance.errors import InvalidTransitionError
from app.services.maintenance.state_machine import ActorContext, transition
from app.models.maintenance import MaintParty
from app.services.maintenance.workspace import message_allowed, sla_status, sms_display_status


NOW = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def ticket(status: MaintStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        priority=MaintPriority.ROUTINE,
        created_at=NOW - timedelta(days=3),
        updated_at=NOW,
        triaged_at=NOW - timedelta(days=3),
        sla_due_at=NOW + timedelta(days=1),
        resolved_at=NOW if status == MaintStatus.RESOLVED else None,
        closed_at=NOW if status == MaintStatus.CLOSED else None,
        close_reason="done" if status == MaintStatus.CLOSED else None,
        duplicate_of=uuid4() if status == MaintStatus.DUPLICATE else None,
    )


def test_resolved_ticket_allows_messages_but_terminal_tickets_do_not() -> None:
    assert message_allowed(MaintStatus.RESOLVED) is True
    assert message_allowed(MaintStatus.CLOSED) is False
    assert message_allowed(MaintStatus.CANCELLED) is False
    assert message_allowed(MaintStatus.DUPLICATE) is False


def test_sms_ui_never_claims_delivery() -> None:
    assert sms_display_status("pending") == "held"
    assert sms_display_status("held") == "held"
    assert sms_display_status("queued") == "sent"
    assert sms_display_status("sent") == "sent"
    assert sms_display_status("delivered") == "sent"
    assert sms_display_status("failed") == "failed"


def test_sla_badges_cover_warning_breach_and_completed() -> None:
    item = ticket(MaintStatus.IN_PROGRESS)
    assert sla_status(item, now=NOW) == "warning"
    item.sla_due_at = NOW
    assert sla_status(item, now=NOW) == "overdue"
    item.status = MaintStatus.CLOSED
    assert sla_status(item, now=NOW) == "complete"


@pytest.mark.asyncio
async def test_only_admin_can_reopen_terminal_ticket_and_duplicate_link_is_cleared() -> None:
    item = ticket(MaintStatus.DUPLICATE)
    with pytest.raises(InvalidTransitionError, match="maintenance admin"):
        await transition(
            FakeSession(),  # type: ignore[arg-type]
            item,  # type: ignore[arg-type]
            MaintStatus.IN_PROGRESS,
            ActorContext(MaintParty.STAFF, user_id=uuid4()),
            "Not a duplicate after review",
            now=NOW,
        )

    await transition(
        FakeSession(),  # type: ignore[arg-type]
        item,  # type: ignore[arg-type]
        MaintStatus.IN_PROGRESS,
        ActorContext(MaintParty.STAFF, user_id=uuid4(), is_admin=True),
        "Not a duplicate after review",
        now=NOW,
    )
    assert item.status == MaintStatus.IN_PROGRESS
    assert item.duplicate_of is None
