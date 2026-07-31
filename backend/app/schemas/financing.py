from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class FacilityBase(BaseModel):
    property_id: UUID | None = None
    lender_type: str
    lender_name: str | None = None
    total_facility: Decimal | None = None
    opening_balance: Decimal | None = None
    rate: Decimal | None = None
    already_drawn: Decimal = Decimal("0")
    draw_eligible_override: Decimal | None = None
    requested_draw_amount: Decimal | None = None
    requested_draw_as_of: date | None = None
    commitment_source: str | None = None
    commitment_confirmed_at: datetime | None = None
    last_draw_date: date | None = None
    last_draw_amount: Decimal | None = None
    account_number: str | None = None
    account_title: str | None = None
    account_type: str | None = None
    current_balance: Decimal | None = None
    outstanding_balance: Decimal | None = None
    account_currency: str | None = None
    maturity_date: date | None = None
    member_number: str | None = None
    next_interest_payment_date: date | None = None
    next_payment_date: date | None = None
    account_nickname: str | None = None
    open_date: date | None = None
    original_loan_amount: Decimal | None = None
    payment_schedule: str | None = None
    term_length_days: int | None = None
    notes: str | None = None


class FacilityCreate(FacilityBase):
    pass


class FacilityUpdate(BaseModel):
    property_id: UUID | None = None
    lot_id: UUID | None = None
    lender_type: str | None = None
    lender_name: str | None = None
    total_facility: Decimal | None = None
    opening_balance: Decimal | None = None
    rate: Decimal | None = None
    already_drawn: Decimal | None = None
    last_draw_date: date | None = None
    last_draw_amount: Decimal | None = None
    account_number: str | None = None
    account_title: str | None = None
    account_type: str | None = None
    current_balance: Decimal | None = None
    outstanding_balance: Decimal | None = None
    account_currency: str | None = None
    maturity_date: date | None = None
    member_number: str | None = None
    next_interest_payment_date: date | None = None
    next_payment_date: date | None = None
    account_nickname: str | None = None
    open_date: date | None = None
    original_loan_amount: Decimal | None = None
    payment_schedule: str | None = None
    term_length_days: int | None = None
    notes: str | None = None


class FacilityOut(FacilityBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lender_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FinancingPropertyOut(BaseModel):
    property_id: UUID
    address: str
    lender_type: str
    sold_or_spec: str | None = None
    stage: str | None = None
    stage_is_estimate: bool
    possession_date: date | None = None
    build_start: date | None = None
    client_name: str | None = None
    banker_raw: str | None = None
    lender_name: str | None = None
    total_facility: Decimal | None = None
    opening_balance: Decimal | None = None
    already_drawn: Decimal | None = None
    last_draw_date: date | None = None
    last_draw_amount: Decimal | None = None
    rate: Decimal | None = None
    account_number: str | None = None
    account_title: str | None = None
    account_type: str | None = None
    current_balance: Decimal | None = None
    outstanding_balance: Decimal | None = None
    account_currency: str | None = None
    maturity_date: date | None = None
    member_number: str | None = None
    next_interest_payment_date: date | None = None
    next_payment_date: date | None = None
    account_nickname: str | None = None
    open_date: date | None = None
    original_loan_amount: Decimal | None = None
    payment_schedule: str | None = None
    term_length_days: int | None = None
    daily_interest_estimate: Decimal | None = None
    monthly_interest_estimate: Decimal | None = None
    annual_interest_estimate: Decimal | None = None
    notes: str | None = None
    draw_eligible: Decimal | None = None
    cumulative_entitled: Decimal | None = None
    funds_remaining: Decimal | None = None
    flag: str | None = None
    formula: str
    facility_id: UUID | None = None


class LenderSummary(BaseModel):
    total_drawable: Decimal | None
    properties: int
    flagged: int


class DashboardSummary(BaseModel):
    SCU: LenderSummary = Field(default_factory=lambda: LenderSummary(total_drawable=Decimal("0"), properties=0, flagged=0))
    PRO: LenderSummary = Field(default_factory=lambda: LenderSummary(total_drawable=Decimal("0"), properties=0, flagged=0))
    STRIDE: LenderSummary = Field(default_factory=lambda: LenderSummary(total_drawable=Decimal("0"), properties=0, flagged=0))
    RSU: LenderSummary = Field(default_factory=lambda: LenderSummary(total_drawable=Decimal("0"), properties=0, flagged=0))
    CLIENT: LenderSummary = Field(default_factory=lambda: LenderSummary(total_drawable=None, properties=0, flagged=0))
    OTHER: LenderSummary = Field(default_factory=lambda: LenderSummary(total_drawable=None, properties=0, flagged=0))


class FinancingDashboardOut(BaseModel):
    last_synced_at: datetime | None
    summary: DashboardSummary
    properties: list[FinancingPropertyOut]


class SyncResult(BaseModel):
    synced: int
    created_properties: int
    stale_deleted: int = 0
    errors: list[str]
    sync_conflicts: list[dict[str, Any]] = Field(default_factory=list)


class DocumentUploadOut(BaseModel):
    doc_id: UUID
    review_document_id: UUID | None = None
    lender_type: str
    minio_key: str
    extracted: dict[str, Any]
    requires_review: bool


class FacilityDocumentOut(BaseModel):
    id: UUID
    facility_id: UUID | None = None
    lender_type: str
    document_type: str
    minio_bucket: str
    minio_key: str
    original_filename: str | None = None
    uploaded_at: datetime
    extracted_values: dict[str, Any] | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None


class ConfirmDocumentRequest(BaseModel):
    facility_id: UUID | None = None
    property_id: UUID | None = None
    values: dict[str, Any]


class ProFacilityOut(BaseModel):
    id: UUID
    facility_key: str
    property_name: str
    borrower: str | None = None
    facility_scope: str
    instrument: str | None = None
    annual_rate: Decimal | None = None
    original_advance_date: date | None = None
    original_advance_amount: Decimal | None = None
    status: str
    balance_as_of: Decimal | None = None
    last_statement_status: str | None = None
    last_statement_delta: Decimal | None = None


class ProLedgerEventOut(BaseModel):
    event_date: date
    days: int
    interest: Decimal
    draw: Decimal
    repayment: Decimal
    balance: Decimal
    accrued_interest_running_total: Decimal
    reference: str | None = None
    event_type: str


class ProLedgerOut(BaseModel):
    facility_id: UUID
    facility_key: str
    property_name: str
    as_of: date
    balance_as_of: Decimal
    events: list[ProLedgerEventOut]


class LenderStatementOut(BaseModel):
    id: UUID
    lender: str
    period: str
    minio_object_key: str
    original_filename: str | None = None
    uploaded_at: datetime
    parsed_at: datetime | None = None
    status: str


class FacilityStatementSnapshotOut(BaseModel):
    id: UUID
    statement_id: UUID
    facility_id: UUID | None = None
    matched_property_name: str
    reported_period_end_date: date
    reported_period_end_balance: Decimal
    computed_balance: Decimal | None = None
    delta: Decimal | None = None
    reconciliation_status: str
    canonical_address_key: str | None = None
    parse_payload: dict[str, Any] | None = None
    new_draws_detected: list[dict[str, Any]] | None = None


class LenderStatementDetailOut(LenderStatementOut):
    parse_payload: dict[str, Any] | None = None
    snapshots: list[FacilityStatementSnapshotOut]


class ClientDrawScheduleItem(BaseModel):
    seq: int
    label_raw: str
    stage_key: str | None = None
    amount: Decimal | None = None
    amount_type: str = "fixed"
    percent: Decimal | None = None
    conditions_raw: str | None = None
    source_page: int | None = None


class ClientDrawDeposit(BaseModel):
    seq: int | None = None
    label_raw: str | None = None
    amount: Decimal | None = None
    due_raw: str | None = None
    source_page: int | None = None


class ClientDrawScheduleOut(BaseModel):
    id: UUID
    property_id: UUID
    document_id: UUID
    minio_object_key: str
    original_filename: str | None = None
    purchase_price: Decimal | None = None
    client_name: str | None = None
    otp_date: date | None = None
    schedule: list[dict[str, Any]]
    deposits: list[dict[str, Any]]
    extraction_confidence: str
    extraction_status: str
    extraction_notes: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    superseded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ClientDrawScheduleReviewRequest(BaseModel):
    purchase_price: Decimal | None = None
    client_name: str | None = None
    otp_date: date | None = None
    schedule: list[dict[str, Any]]
    deposits: list[dict[str, Any]] = Field(default_factory=list)
    extraction_notes: str | None = None


class ClientDrawRequestOut(BaseModel):
    id: UUID
    property_id: UUID
    schedule_id: UUID
    draw_items: list[dict[str, Any]]
    amount: Decimal
    stage_at_prep: str | None = None
    prepared_at: datetime
    prepared_by: UUID | None = None
    status: str
    notes: str | None = None


class ClientPrepDrawConfirmRequest(BaseModel):
    draw_items: list[dict[str, Any]]
    amount: Decimal
    notes: str | None = None


class ClientDrawStatusRequest(BaseModel):
    status: str
    notes: str | None = None


class ClientPrepDrawOut(BaseModel):
    status: str
    property: dict[str, Any]
    current_stage: str | None = None
    current_stage_synced_at: datetime | None = None
    schedule: ClientDrawScheduleOut | None = None
    schedule_table: list[dict[str, Any]] = Field(default_factory=list)
    requestable_items: list[dict[str, Any]] = Field(default_factory=list)
    already_requested_items: list[dict[str, Any]] = Field(default_factory=list)
    unmapped_items: list[dict[str, Any]] = Field(default_factory=list)
    next_upcoming_item: dict[str, Any] | None = None
    requestable_total: Decimal | None = None
    eligibility_unavailable_reason: str | None = None
    lawyer_note: str | None = None
