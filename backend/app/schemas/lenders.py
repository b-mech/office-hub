from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field


class LenderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class LenderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class LenderListItem(BaseModel):
    id: UUID
    name: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    active_facility_count: int
    created_at: datetime
    updated_at: datetime


class LenderFacilityLink(BaseModel):
    facility_id: UUID
    property_id: UUID | None = None
    property_address: str | None = None
    lender_type: str
    status: str
    total_facility: str | None = None
    opening_balance: str | None = None


class LenderDetail(LenderListItem):
    facilities: list[LenderFacilityLink]
