from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field
from pydantic import field_validator


CONDITION_CATEGORIES = (
    "sale_of_existing_home",
    "subject_to_appraisal",
    "income_verification",
    "down_payment_verification",
    "credit_review",
    "insurer_approval",
    "builder_docs",
    "rate_hold_expiry",
    "other",
)


class IntakeEmail(BaseModel):
    message_id: str = ""
    from_: str = Field(default="", alias="from")
    subject: str = ""
    received_at: datetime | None = None
    body_text: str = Field(default="", max_length=4000)

    model_config = {"populate_by_name": True}


class IntakeAttachment(BaseModel):
    filename: str
    content_base64: str
    mime: str = "application/pdf"


class ApprovalLetterIntake(BaseModel):
    lot_id: UUID | None = None
    mark_as_presale: bool = False
    email: IntakeEmail
    attachments: list[IntakeAttachment] = Field(min_length=1)


class ConditionPayload(BaseModel):
    text: str
    category: str
    deadline: str | None = None

    @field_validator("category")
    @classmethod
    def valid_category(cls, value: str) -> str:
        if value not in CONDITION_CATEGORIES:
            raise ValueError("Unknown approval-letter condition category")
        return value


class ApprovalLetterUpdate(BaseModel):
    lot_id: UUID | None = None
    mark_as_presale: bool = False
    extracted: dict[str, Any] | None = None
    quality_score: int | None = Field(default=None, ge=1, le=10)


class ContactLenderRequest(BaseModel):
    notes: str = ""


class RejectApprovalLetterRequest(BaseModel):
    reason: str = Field(min_length=1)


class MarkPresaleRequest(BaseModel):
    sale_type: Literal["presale", "spec", "showhome", "other"]
    building_type: Literal["bungalow", "two_storey", "duplex", "other"] | None = None
    realtor_name: str | None = None
    realtor_email: EmailStr | None = None
    realtor_brokerage: str | None = None


class MarkRequestedRequest(BaseModel):
    requested_from: str | None = None


class PackageItemAction(BaseModel):
    action: Literal["requested", "ordered"]


class MarkPackageSentRequest(BaseModel):
    partner_code: str


class FundingPartnerRuleWrite(BaseModel):
    partner_code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    priority: int = Field(ge=0)
    required_docs: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    disqualifying_conditions: list[str] = Field(default_factory=list)
    min_quality_score: int | None = Field(default=None, ge=1, le=10)
    formula: dict[str, Any] | None = None
    max_advance_rule: dict[str, Any] | None = None
    package_recipient: EmailStr | None = None
    package_docs: list[str] = Field(default_factory=list)
    active: bool = True

    @field_validator("disqualifying_conditions")
    @classmethod
    def valid_condition_categories(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - set(CONDITION_CATEGORIES))
        if unknown:
            raise ValueError(f"Unknown condition categories: {', '.join(unknown)}")
        return values


class FundingPartnerRulePatch(BaseModel):
    display_name: str | None = None
    priority: int | None = Field(default=None, ge=0)
    required_docs: list[str] | None = None
    required_fields: list[str] | None = None
    disqualifying_conditions: list[str] | None = None
    min_quality_score: int | None = Field(default=None, ge=1, le=10)
    formula: dict[str, Any] | None = None
    max_advance_rule: dict[str, Any] | None = None
    package_recipient: EmailStr | None = None
    package_docs: list[str] | None = None
    active: bool | None = None

    @field_validator("disqualifying_conditions")
    @classmethod
    def valid_condition_categories(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return values
        unknown = sorted(set(values) - set(CONDITION_CATEGORIES))
        if unknown:
            raise ValueError(f"Unknown condition categories: {', '.join(unknown)}")
        return values


class TaskCompleteRequest(BaseModel):
    notes: str | None = None


class ApprovalLetterOut(BaseModel):
    id: UUID
    lot_id: UUID | None
    status: str
    version: int
    requested_at: datetime | None
    requested_from: str | None
    file_key: str | None
    original_filename: str | None
    email_from: str | None
    email_subject: str | None
    email_received_at: datetime | None
    extracted: dict[str, Any]
    extraction_confidence: dict[str, Any]
    low_confidence_fields: list[str]
    needs_manual_entry: bool
    quality_score: int | None
    lender_contacted_at: datetime | None
    lender_contact_notes: str | None
    rejection_reason: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
