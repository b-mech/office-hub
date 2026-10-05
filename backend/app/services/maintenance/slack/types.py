from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class WorkOrderCardView:
    id: UUID
    number: str
    assignee_type: str
    assignee_name: str
    status: str
    scope: str
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


@dataclass(frozen=True)
class TicketCardView:
    id: UUID
    number: str
    title: str
    description: str
    status: str
    category: str | None
    priority: str | None
    is_emergency: bool
    emergency_acknowledged: bool
    property_label: str
    unit_label: str
    reporter_name: str | None
    reporter_verified: bool
    entry_permission: str
    sla_due_at: datetime | None
    work_orders: tuple[WorkOrderCardView, ...] = ()
    attachment_count: int = 0
    ai_suggestion: str | None = None


@dataclass(frozen=True)
class RelayResult:
    kind: str
    message_id: UUID | None = None
    reason: str | None = None
