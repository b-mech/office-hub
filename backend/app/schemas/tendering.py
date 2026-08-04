from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field


TenderStatus = Literal["draft", "sent", "bids_in", "compared", "awarded", "cancelled"]
TenderDocumentType = Literal["plan", "markup", "spec"]
TenderBidStatus = Literal["invited", "received", "reviewed", "cancelled"]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str


class ContractorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    notes: str | None = None
    active: bool = True
    category_ids: list[UUID] = Field(default_factory=list)


class ContractorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    notes: str | None = None
    active: bool | None = None
    category_ids: list[UUID] | None = None


class ContractorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None
    active: bool
    categories: list[CategoryOut]
    created_at: datetime
    updated_at: datetime


class TenderPackageCreate(BaseModel):
    category_id: UUID
    scope_description: str = Field(min_length=1)
    due_date: date | None = None


class TenderPackageUpdate(BaseModel):
    category_id: UUID | None = None
    scope_description: str | None = Field(default=None, min_length=1)
    status: TenderStatus | None = None
    due_date: date | None = None


class TenderDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tender_package_id: UUID
    document_type: TenderDocumentType
    file_path: str
    original_filename: str
    uploaded_at: datetime


class TenderBidDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tender_bid_id: UUID
    file_path: str
    original_filename: str
    uploaded_at: datetime


class TenderBidCreate(BaseModel):
    contractor_id: UUID


class TenderLineItem(BaseModel):
    description: str = Field(min_length=1)
    amount: Decimal


class TenderBidUpdate(BaseModel):
    quote_amount: Decimal | None = Field(default=None, ge=0)
    extracted_line_items: list[TenderLineItem] | None = None
    excluded_scope_notes: str | None = None
    reviewer_notes: str | None = None


class TenderBidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tender_package_id: UUID
    contractor_id: UUID
    contractor: ContractorOut
    status: TenderBidStatus
    quote_amount: Decimal | None = None
    extracted_amount: Decimal | None = None
    extracted_line_items: list[TenderLineItem] | None = None
    excluded_scope_notes: str | None = None
    reviewer_notes: str | None = None
    invited_at: datetime | None = None
    received_at: datetime | None = None
    documents: list[TenderBidDocumentOut]
    created_at: datetime
    updated_at: datetime


class TenderAwardCreate(BaseModel):
    winning_bid_id: UUID
    budget_id: UUID
    budget_line_id: UUID
    award_instructions: str = Field(min_length=1)
    project_start_date: date
    contractor_start_date: date


class PurchaseOrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    po_number: str
    budget_id: UUID
    budget_line_id: UUID
    description: str
    amount: Decimal
    status: str


class TenderAwardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tender_package_id: UUID
    winning_bid_id: UUID
    po_id: UUID
    award_instructions: str
    project_start_date: date
    contractor_start_date: date
    awarded_at: datetime
    purchase_order: PurchaseOrderSummary | None = None


class TenderPackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    property_id: UUID
    category_id: UUID
    category: CategoryOut
    scope_description: str
    status: TenderStatus
    due_date: date | None = None
    documents: list[TenderDocumentOut]
    bids: list[TenderBidOut] = Field(default_factory=list)
    award: TenderAwardOut | None = None
    created_at: datetime
    updated_at: datetime


class TenderComparisonOut(BaseModel):
    package: TenderPackageOut
    bids: list[TenderBidOut]
    bid_count: int
    received_count: int
