from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.maintenance import MaintCategory, MaintPriority


class TriageRequest(BaseModel):
    category: MaintCategory
    priority: MaintPriority
    is_emergency: bool = False
    title: str = Field(min_length=1, max_length=120)
    staff_summary: str | None = Field(default=None, max_length=2000)


class AssignmentRequest(BaseModel):
    assignee_type: Literal["staff", "vendor"]
    scope: str = Field(min_length=1, max_length=4000)
    assignee_user_id: UUID | None = None
    vendor_id: UUID | None = None
    cost_estimate: Decimal | None = Field(default=None, ge=0)


class ScheduleRequest(BaseModel):
    work_order_id: UUID
    start: datetime
    end: datetime
    admin_override_reason: str | None = Field(default=None, max_length=1000)


class CompleteWorkOrderRequest(BaseModel):
    completion_notes: str = Field(default="", max_length=4000)
    cost_actual: Decimal | None = Field(default=None, ge=0)


class ScheduledVisitRequest(BaseModel):
    status: Literal["completed", "cancelled"]


class ResolveRequest(BaseModel):
    note: str = Field(min_length=1, max_length=4000)
    cancel_scheduled_visit_ids: list[UUID] = Field(default_factory=list)


class MoreActionRequest(BaseModel):
    action: Literal["cancel", "duplicate", "reopen", "toggle_chargeback"]
    reason: str | None = Field(default=None, max_length=2000)
    canonical_ticket_id: UUID | None = None
