from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field


TenderStatus = Literal["draft", "sent", "bids_in", "compared", "awarded", "cancelled"]
TenderDocumentType = Literal["plan", "markup", "spec"]


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
    created_at: datetime
    updated_at: datetime
