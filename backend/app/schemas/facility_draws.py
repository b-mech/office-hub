"""Dated transaction history; independent of the bank-maintained balance."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class FacilityDrawCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    txn_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)
    txn_type: Literal["draw", "repayment"] = "draw"
    reference: str = Field(default="", max_length=1000)
    notes: str | None = Field(default=None, max_length=10000, validation_alias=AliasChoices("notes", "confirmation_text"))
    confirmed_by: str | None = Field(default=None, max_length=255)
    percent_complete: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2, allow_inf_nan=False)
    source: Literal["scu_confirmation", "manual"] | None = None

    @field_validator("reference", mode="before")
    @classmethod
    def normalize_reference(cls, value):
        return "" if value is None else value.strip() if isinstance(value, str) else value

    @field_validator("notes", "confirmed_by", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class FacilityDrawOut(BaseModel):
    id: UUID
    facility_id: UUID
    txn_date: date
    txn_type: str
    amount: Decimal
    reference: str | None = None
    notes: str | None = None
    confirmed_by: str | None = None
    percent_complete: Decimal | None = None
    source: str
    created_at: datetime
    running_total: Decimal
    can_delete: bool


class FacilityDrawHistory(BaseModel):
    facility_id: UUID
    lender_type: str
    already_drawn: Decimal | None
    sum_of_draws: Decimal
    sum_of_repayments: Decimal
    net_draws: Decimal
    difference_from_already_drawn: Decimal | None
    items: list[FacilityDrawOut]


class DrawImportResult(BaseModel):
    status: Literal["created", "skipped"]
    txn_id: UUID


class FacilityDrawImportOut(BaseModel):
    facility_id: UUID
    created: int
    skipped: int
    results: list[DrawImportResult]
    history: FacilityDrawHistory


class FacilityDrawDeleteOut(BaseModel):
    deleted: bool
    txn_id: UUID
    history: FacilityDrawHistory
