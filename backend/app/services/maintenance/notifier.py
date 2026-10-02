from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintSmsMessage, MaintTicket, MaintWorkOrder
from app.services.maintenance.slack.outbox import enqueue_slack_notification


class MaintenanceNotifier(Protocol):
    """Boundary implemented by the Slack worker in Phase 7."""

    async def ticket_created(self, db: AsyncSession, ticket: MaintTicket) -> None: ...
    async def inbound_message(self, db: AsyncSession, message: MaintSmsMessage, ticket: MaintTicket | None) -> None: ...
    async def unmatched_message(self, db: AsyncSession, message: MaintSmsMessage, *, known_tenant: bool) -> None: ...
    async def sms_status_changed(self, db: AsyncSession, message: MaintSmsMessage) -> None: ...
    async def opted_out(self, db: AsyncSession, phone_e164: str, *, source_key: str) -> None: ...


class NoopMaintenanceNotifier:
    async def ticket_created(self, db: AsyncSession, ticket: MaintTicket) -> None:
        return None

    async def inbound_message(self, db: AsyncSession, message: MaintSmsMessage, ticket: MaintTicket | None) -> None:
        return None

    async def unmatched_message(self, db: AsyncSession, message: MaintSmsMessage, *, known_tenant: bool) -> None:
        return None

    async def sms_status_changed(self, db: AsyncSession, message: MaintSmsMessage) -> None:
        return None

    async def opted_out(self, db: AsyncSession, phone_e164: str, *, source_key: str) -> None:
        return None


class OutboxMaintenanceNotifier:
    async def ticket_created(self, db: AsyncSession, ticket: MaintTicket) -> None:
        await enqueue_slack_notification(
            db,
            idempotency_key=f"ticket:{ticket.id}:created",
            kind="ticket_created",
            ticket_id=ticket.id,
        )

    async def inbound_message(
        self, db: AsyncSession, message: MaintSmsMessage, ticket: MaintTicket | None
    ) -> None:
        await enqueue_slack_notification(
            db,
            idempotency_key=f"sms:{message.id}:inbound",
            kind="inbound_message",
            ticket_id=ticket.id if ticket else None,
            work_order_id=message.work_order_id,
            sms_message_id=message.id,
        )

    async def unmatched_message(
        self, db: AsyncSession, message: MaintSmsMessage, *, known_tenant: bool
    ) -> None:
        await enqueue_slack_notification(
            db,
            idempotency_key=f"sms:{message.id}:unmatched",
            kind="unmatched_message",
            sms_message_id=message.id,
            payload={"known_tenant": known_tenant},
        )

    async def sms_status_changed(self, db: AsyncSession, message: MaintSmsMessage) -> None:
        await enqueue_slack_notification(
            db,
            idempotency_key=f"sms:{message.id}:status:{message.status}",
            kind="sms_status_changed",
            ticket_id=message.ticket_id,
            work_order_id=message.work_order_id,
            sms_message_id=message.id,
            payload={"status": message.status},
        )

    async def opted_out(self, db: AsyncSession, phone_e164: str, *, source_key: str) -> None:
        await enqueue_slack_notification(
            db,
            idempotency_key=f"{source_key}:opted-out",
            kind="opted_out",
            payload={"phone_last4": phone_e164[-4:]},
        )


_notifier: MaintenanceNotifier = OutboxMaintenanceNotifier()


def get_maintenance_notifier() -> MaintenanceNotifier:
    return _notifier


def set_maintenance_notifier(notifier: MaintenanceNotifier) -> None:
    global _notifier
    _notifier = notifier
