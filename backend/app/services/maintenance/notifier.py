from __future__ import annotations

from datetime import timezone
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
        if getattr(ticket, "is_emergency", False):
            from app.services.maintenance.emergencies import page_emergency

            await page_emergency(db, ticket, stage=0)

    async def inbound_message(
        self, db: AsyncSession, message: MaintSmsMessage, ticket: MaintTicket | None
    ) -> None:
        if ticket is None:
            return
        created_at = message.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        bucket = int(created_at.timestamp()) // 600
        await enqueue_slack_notification(
            db,
            idempotency_key=f"ticket:{ticket.id}:reply:{bucket}",
            kind="party_replied",
            ticket_id=ticket.id,
            work_order_id=message.work_order_id,
            sms_message_id=message.id,
            payload={"party": "vendor" if message.work_order_id else "tenant"},
        )

    async def unmatched_message(
        self, db: AsyncSession, message: MaintSmsMessage, *, known_tenant: bool
    ) -> None:
        return None

    async def sms_status_changed(self, db: AsyncSession, message: MaintSmsMessage) -> None:
        return None

    async def opted_out(self, db: AsyncSession, phone_e164: str, *, source_key: str) -> None:
        return None


_notifier: MaintenanceNotifier = OutboxMaintenanceNotifier()


def get_maintenance_notifier() -> MaintenanceNotifier:
    return _notifier


def set_maintenance_notifier(notifier: MaintenanceNotifier) -> None:
    global _notifier
    _notifier = notifier
