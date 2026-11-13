from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LeaseImportTenant(BaseModel):
    full_name: str = Field(min_length=1)
    phone: str | None = None
    email: str | None = None
    is_primary_contact: bool = False


class LeaseParsedData(BaseModel):
    property_street_address: str = Field(min_length=1)
    unit_label: str | None = None
    tenants: list[LeaseImportTenant] = Field(min_length=1)
    rent: Decimal = Field(gt=0)
    rent_discount_amount: Decimal | None = None
    deposit: Decimal | None = None
    water_credit_amount: Decimal | None = None
    lease_start: date | None = None
    lease_end: date | None = None
    lease_notes: str | None = None


class LeaseImportRowPatch(BaseModel):
    parsed_data: LeaseParsedData | None = None
    matched_unit_id: int | None = None
    match_type: Literal["existing_unit", "new_unit", "unresolved"] | None = None
    suggested_action: Literal["create_lease", "renew_lease", "update_lease", "skip"] | None = None
    existing_lease_id: int | None = None


class LeaseImportRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: int
    source_row_number: int
    raw_data: dict[str, Any]
    parsed_data: dict[str, Any] | None
    confidence: dict[str, Any] | None
    match_type: str | None
    matched_unit_id: int | None
    suggested_action: str | None
    existing_lease_id: int | None
    review_status: str
    reviewed_at: datetime | None
    committed_lease_id: int | None
    created_at: datetime


class LeaseImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_filename: str
    uploaded_at: datetime
    status: str
    total_rows: int
    rows_pending: int
    rows: list[LeaseImportRowOut] = Field(default_factory=list)


class BulkApprovalOut(BaseModel):
    approved: int
    skipped_for_review: int


class LeaseImportPreviewRow(BaseModel):
    source_row_number: int
    property_street_address: str | None = None
    unit_label: str | None = None
    tenant_names: list[str] = Field(default_factory=list)
    rent: str | None = None
    lease_start: str | None = None
    lease_end: str | None = None
    property_match: Literal["existing_unit", "existing_property", "new_property", "unknown"] = "unknown"
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LeaseImportValidationOut(BaseModel):
    """Dry-run result: nothing is stored and no extraction runs."""
    dry_run: Literal[True] = True
    filename: str
    ok: bool
    file_errors: list[str] = Field(default_factory=list)
    total_rows: int = 0
    rows_ready: int = 0
    rows_with_errors: int = 0
    rows_with_warnings: int = 0
    rows: list[LeaseImportPreviewRow] = Field(default_factory=list)
