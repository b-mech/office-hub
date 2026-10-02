from __future__ import annotations

from typing import Protocol

from app.models.maintenance import MaintSmsMessage, MaintTicket, MaintWorkOrder


class MaintenanceNotifier(Protocol):
    """Boundary implemented by the Slack worker in Phase 7."""

    async def ticket_created(self, ticket: MaintTicket) -> None: ...
    async def inbound_message(self, message: MaintSmsMessage, ticket: MaintTicket | None) -> None: ...
    async def unmatched_message(self, message: MaintSmsMessage, *, known_tenant: bool) -> None: ...
    async def sms_status_changed(self, message: MaintSmsMessage) -> None: ...
    async def opted_out(self, phone_e164: str) -> None: ...


class NoopMaintenanceNotifier:
    async def ticket_created(self, ticket: MaintTicket) -> None:
        return None

    async def inbound_message(self, message: MaintSmsMessage, ticket: MaintTicket | None) -> None:
        return None

    async def unmatched_message(self, message: MaintSmsMessage, *, known_tenant: bool) -> None:
        return None

    async def sms_status_changed(self, message: MaintSmsMessage) -> None:
        return None

    async def opted_out(self, phone_e164: str) -> None:
        return None


_notifier: MaintenanceNotifier = NoopMaintenanceNotifier()


def get_maintenance_notifier() -> MaintenanceNotifier:
    return _notifier


def set_maintenance_notifier(notifier: MaintenanceNotifier) -> None:
    global _notifier
    _notifier = notifier
