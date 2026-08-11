from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


RequestStatus = Literal["draft", "requested", "approved", "released"]
BasisSource = Literal[
    "appraisal",
    "estimated_sale_price",
    "lesser_of_appraisal_and_estimated_sale_price",
    "lot_purchase_price",
    "explicit_historical",
]


class ProgramCreate(BaseModel):
    lender_id: UUID
    name: str = Field(min_length=1, max_length=255)
    umbrella_limit: Decimal = Field(ge=0)
    notes: str | None = None
    active: bool = True


class ProgramUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    umbrella_limit: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    active: bool | None = None


class AllocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    allocation_limit: Decimal = Field(ge=0)
    max_units: int = Field(ge=0)
    max_per_unit: Decimal | None = Field(default=None, ge=0)
    funding_percentage: Decimal = Field(ge=0)
    notes: str | None = None


class AllocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    allocation_limit: Decimal | None = Field(default=None, ge=0)
    max_units: int | None = Field(default=None, ge=0)
    max_per_unit: Decimal | None = Field(default=None, ge=0)
    funding_percentage: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class TierCreate(BaseModel):
    face_value: Decimal = Field(ge=0)
    slot_count: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=255)


class TierUpdate(BaseModel):
    face_value: Decimal | None = Field(default=None, ge=0)
    slot_count: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=255)


class FitEvaluationRequest(BaseModel):
    lot_id: UUID
    allocation_id: UUID
    appraisal_value: Decimal | None = Field(default=None, ge=0)
    estimated_sale_price: Decimal | None = Field(default=None, ge=0)
    basis_value: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_a_basis(self) -> "FitEvaluationRequest":
        if self.appraisal_value is None and self.estimated_sale_price is None and self.basis_value is None:
            raise ValueError("Provide appraisal_value, estimated_sale_price, or basis_value.")
        return self


class AllocationRequestCreate(FitEvaluationRequest):
    property_id: UUID | None = None
    actual_amount: Decimal | None = Field(default=None, ge=0)
    status: RequestStatus = "draft"
    notes: str | None = None


class AllocationRequestUpdate(BaseModel):
    property_id: UUID | None = None
    appraisal_value: Decimal | None = Field(default=None, ge=0)
    estimated_sale_price: Decimal | None = Field(default=None, ge=0)
    basis_value: Decimal | None = Field(default=None, ge=0)
    actual_amount: Decimal | None = Field(default=None, ge=0)
    status: RequestStatus | None = None
    notes: str | None = None


class TierCapacityOut(BaseModel):
    id: UUID
    face_value: Decimal
    slot_count: int
    label: str | None = None
    slots_occupied: int
    slots_remaining: int


class AllocationCapacityOut(BaseModel):
    id: UUID
    name: str
    allocation_limit: Decimal
    consumed: Decimal
    remaining: Decimal
    max_units: int
    units_used: int
    units_remaining: int
    max_per_unit: Decimal | None = None
    funding_percentage: Decimal
    notes: str | None = None
    tiers: list[TierCapacityOut]


class ProgramCapacityOut(BaseModel):
    id: UUID
    lender_id: UUID
    lender_name: str
    name: str
    umbrella_limit: Decimal
    consumed: Decimal
    remaining: Decimal
    notes: str | None = None
    active: bool
    allocations: list[AllocationCapacityOut]


class FitEvaluationOut(BaseModel):
    lot_id: UUID
    allocation_id: UUID
    appraisal_value: Decimal | None = None
    estimated_sale_price: Decimal | None = None
    basis_value: Decimal
    basis_source: BasisSource
    suggested_amount: Decimal
    nearest_tier: TierCapacityOut | None = None
    fits_remaining_allocation: bool
    fits_umbrella: bool
    units_available: bool
    flags: list[str]


class AllocationRequestOut(BaseModel):
    id: UUID
    allocation_id: UUID
    lot_id: UUID
    property_id: UUID | None = None
    address: str
    appraisal_value: Decimal | None = None
    estimated_sale_price: Decimal | None = None
    basis_value: Decimal
    basis_source: BasisSource
    suggested_amount: Decimal
    actual_amount: Decimal | None = None
    nearest_tier_id: UUID | None = None
    nearest_tier_face_value: Decimal | None = None
    status: RequestStatus
    requested_at: datetime | None = None
    approved_at: datetime | None = None
    released_at: datetime | None = None
    notes: str | None = None
    flags: list[str]


class ProgramDetailOut(ProgramCapacityOut):
    requests: list[AllocationRequestOut]
