from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

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
    access_basis: Literal["routine", "tenant_consent", "emergency"] = "routine"
    consent_evidence: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_reason(self) -> "ScheduleRequest":
        if self.access_basis != "emergency" and not (self.reason and self.reason.strip()):
            raise ValueError("Reason for entry is required")
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        return self


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


class StaffTicketCreate(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    property_id: int = Field(gt=0)
    unit_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=10, max_length=10000)
    category: MaintCategory
    priority: MaintPriority = MaintPriority.ROUTINE
    is_emergency: bool = False
    reporter_name: str | None = Field(default=None, max_length=150)
    reporter_phone: str | None = Field(default=None, max_length=50)
    sms_opt_in: bool = False
    entry_permission: Literal["granted", "denied", "not_asked"] = "not_asked"
    entry_notes: str | None = Field(default=None, max_length=2000)


class VendorPortalAction(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    action: Literal["accept", "decline", "propose_schedule", "confirm_schedule", "start", "complete"]
    notes: str | None = Field(default=None, max_length=4000)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def required_details(self):
        if self.action in {"decline", "complete"} and not self.notes:
            raise ValueError("Notes are required for declining or completing work")
        if self.action == "propose_schedule" and (not self.start or not self.end):
            raise ValueError("A start and end time with timezone are required")
        if self.action != "propose_schedule" and (self.start is not None or self.end is not None):
            raise ValueError("Only a proposal may specify times; staff schedules the actual visit")
        return self
