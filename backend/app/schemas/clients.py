from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


ClientTypeValue = Literal["individual", "company"]
ClientStageValue = Literal["lead", "qualified", "active", "possession", "warranty", "closed", "lost"]


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    client_type: ClientTypeValue = "individual"
    lifecycle_stage: ClientStageValue = "lead"
    primary_contact_id: UUID | None = None
    external_ref: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    client_type: ClientTypeValue | None = None
    lifecycle_stage: ClientStageValue | None = None
    primary_contact_id: UUID | None = None
    external_ref: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class ContactSummary(BaseModel):
    id: UUID
    full_name: str
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    contact_type: str


class ClientProject(BaseModel):
    id: UUID
    address: str
    community: str
    lifecycle_status: str
    trigger_type: str | None = None
    on_hold: bool
    possession_date: str | None = None


class ClientOut(BaseModel):
    id: UUID
    org_id: UUID
    display_name: str
    client_type: ClientTypeValue
    lifecycle_stage: ClientStageValue
    stage_changed_at: datetime
    primary_contact: ContactSummary | None = None
    external_ref: str | None = None
    notes: str | None = None
    project_count: int = 0
    created_at: datetime
    updated_at: datetime


class ClientDetail(ClientOut):
    projects: list[ClientProject] = []
    duplicate_name_count: int = 0


class ClientList(BaseModel):
    items: list[ClientOut]
    total: int
    limit: int
    offset: int


class ProjectClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID | None = None
