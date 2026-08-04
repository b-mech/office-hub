from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class FinancialSummaryLender(BaseModel):
    has_lender: bool
    lender_id: UUID | None = None
    lender_name: str | None = None
    facility_type: str | None = None


class FinancialSummaryDraw(BaseModel):
    opening_balance: Decimal | None = None
    drawn_to_date: Decimal | None = None
    remaining: Decimal | None = None
    current_stage: str | None = None
    next_eligible_draw: Decimal | None = None
    last_draw_date: date | None = None
    facility_document_count: int = 0


class FinancialSummaryPrepDraw(BaseModel):
    state: Literal["no_active_schedule", "pending_review", "ready_to_request"]
    ready_to_request: bool


class FinancialSummaryChangeOrders(BaseModel):
    count: int
    pending_signature_count: int
    total_value: Decimal
    last_signed_at: datetime | None = None
    box_filed: bool | None = None
    box_unfiled: bool


class PropertyFinancialSummary(BaseModel):
    property_id: UUID
    lender: FinancialSummaryLender
    draw: FinancialSummaryDraw | None = None
    prep_draw: FinancialSummaryPrepDraw
    change_orders: FinancialSummaryChangeOrders
