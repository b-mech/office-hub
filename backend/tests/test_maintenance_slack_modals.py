from __future__ import annotations

from uuid import uuid4

from app.services.maintenance.slack.handlers import register_handlers
from app.services.maintenance.slack.modals import (
    assignment_modal,
    cancel_modal,
    complete_work_order_modal,
    duplicate_modal,
    message_modal,
    resolve_modal,
    schedule_modal,
    triage_modal,
)


class FakeApp:
    def __init__(self) -> None:
        self.events: dict[str, object] = {}
        self.commands: dict[str, object] = {}
        self.actions: dict[str, object] = {}
        self.views: dict[str, object] = {}

    def _register(self, target: dict[str, object], name: str):
        def decorator(function):
            target[name] = function
            return function
        return decorator

    def event(self, name): return self._register(self.events, name)
    def command(self, name): return self._register(self.commands, name)
    def action(self, name): return self._register(self.actions, name)
    def view(self, name): return self._register(self.views, name)


class Controller:
    async def message_event(self, *args): pass
    async def ticket_command(self, *args): pass
    async def tickets_command(self, *args): pass
    async def acknowledge(self, *args): pass
    async def cancel_sms(self, *args): pass
    async def reopen(self, *args): pass
    async def mark_resolved(self, *args): pass
    async def open_modal(self, *args): pass
    async def submit_triage(self, *args): pass
    async def submit_assign(self, *args): pass
    async def submit_message(self, *args): pass
    async def submit_resolve(self, *args): pass
    async def submit_schedule(self, *args): pass
    async def submit_complete(self, *args): pass
    async def submit_cancel(self, *args): pass
    async def submit_duplicate(self, *args): pass


def test_all_commands_actions_and_views_are_registered() -> None:
    app = FakeApp()
    register_handlers(app, Controller())  # type: ignore[arg-type]
    assert set(app.commands) == {"/ticket", "/tickets"}
    assert {"maint_ack_emergency", "maint_cancel_held_sms", "maint_reopen", "maint_mark_resolved"} <= set(app.actions)
    assert {"maint_triage_submit", "maint_assign_submit", "maint_schedule_submit", "maint_complete_work_order_submit"} <= set(app.views)


def test_modal_builders_have_stable_callbacks_and_private_ids() -> None:
    ticket_id = uuid4()
    work_order_id = uuid4()
    modals = [
        triage_modal(ticket_id, "Leak"),
        message_modal(ticket_id),
        resolve_modal(ticket_id),
        assignment_modal(ticket_id, [{"text": {"type": "plain_text", "text": "Vendor"}, "value": "vendor:x"}]),
        schedule_modal(ticket_id, work_order_id),
        complete_work_order_modal(ticket_id, work_order_id),
        cancel_modal(ticket_id),
        duplicate_modal(ticket_id),
    ]
    assert all(item["type"] == "modal" for item in modals)
    assert all(str(ticket_id) in str(item["private_metadata"]) for item in modals)
    assert len({item["callback_id"] for item in modals}) == len(modals)
    duplicate_modal,
