from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class FacilityAssignmentCreate(BaseModel):
    facility_type: str = Field(min_length=1, max_length=20)
    lender_id: UUID | None = None
    new_lender_name: str | None = Field(default=None, max_length=255)
    total_facility: Decimal | None = None
    opening_balance: Decimal | None = None
    rate: Decimal | None = None
    already_drawn: Decimal = Decimal("0")
    draw_eligible_override: Decimal | None = None
    requested_draw_amount: Decimal | None = None
    requested_draw_as_of: date | None = None
    commitment_source: str | None = None
    commitment_confirmed_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_lender_selection(self) -> "FacilityAssignmentCreate":
        new_name = (self.new_lender_name or "").strip()
        if bool(self.lender_id) == bool(new_name):
            raise ValueError("Choose one existing lender or add one new lender.")
        self.new_lender_name = new_name or None
        return self
