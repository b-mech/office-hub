from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class EmailInput(BaseModel):
    message_id: str
    from_: str = Field(alias="from")
    subject: str = ""
    received_at: datetime | None = None
    body_text: str = ""


class AttachmentInput(BaseModel):
    filename: str
    content_base64: str
    mime: str = "application/pdf"


class FundsIntake(BaseModel):
    property_id: UUID | None = None
    email: EmailInput
    attachments: list[AttachmentInput] = Field(min_length=1, max_length=10)


class EntryUpdate(BaseModel):
    property_id: UUID | None = None
    lot_id: UUID | None = None
    facility_id: UUID | None = None
    funds_type: str | None = None
    deposit_ordinal: int | None = None
    property_address: str | None = None
    amount: Decimal | None = None
    cheque_number: str | None = None
    txn_date: date | None = None
    payee: str | None = None
    memo: str | None = None
    closing: dict | None = None


class PossessionConfirm(BaseModel):
    possession_date: date
