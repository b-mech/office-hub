from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import Numeric
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.core.database import Base


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=func.gen_random_uuid(),
        server_default=func.gen_random_uuid(),
    )


class TriggerType(str, Enum):
    ON_SIGNING = "on_signing"
    FIXED_DATE = "fixed_date"
    MILESTONE = "milestone"


class Agreement(Base):
    __tablename__ = "agreements"

    id: Mapped[UUID] = _uuid_pk()
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.documents.id"),
        nullable=False,
    )
    review_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.reviews.id"),
        nullable=False,
    )
    developer_contact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.contacts.id"),
        nullable=False,
    )
    development_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.developments.id"),
        nullable=False,
    )
    agreement_date: Mapped[date] = mapped_column(Date, nullable=False)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    interest_type: Mapped[str | None] = mapped_column(Text)
    interest_terms: Mapped[str | None] = mapped_column(Text)
    interest_free_from: Mapped[date | None] = mapped_column(Date)
    balance_due_rule: Mapped[str | None] = mapped_column(Text)
    total_purchase_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    municipality: Mapped[str | None] = mapped_column(Text)
    notable_clauses: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("interest_type IN ('flat', 'prime_plus_fixed')"),
        Index("idx_land_agreements_development_document", "development_id", "document_id"),
        {"schema": "land"},
    )


class SecurityDeposit(Base):
    __tablename__ = "security_deposit"
    __table_args__ = {"schema": "land"}

    id: Mapped[UUID] = _uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("land.agreements.id"),
        nullable=False,
        unique=True,
    )
    rate_per_lot: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    maximum_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    calculated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    due_trigger: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="on_signing",
        server_default=text("'on_signing'"),
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LotTerms(Base):
    __tablename__ = "lot_terms"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.lots.id"),
        nullable=False,
    )
    agreement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("land.agreements.id"),
        nullable=False,
    )
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    frontage_metres: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    frontage_feet: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    lot_notes: Mapped[str | None] = mapped_column(Text)
    balance_due_date: Mapped[date | None] = mapped_column(Date)
    possession_date: Mapped[date | None] = mapped_column(Date)
    lot_specific_conditions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("lot_id", "agreement_id"),
        {"schema": "land"},
    )


class DepositSchedule(Base):
    __tablename__ = "deposit_schedule"

    id: Mapped[UUID] = _uuid_pk()
    lot_terms_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("land.lot_terms.id"),
        nullable=False,
    )
    lot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.lots.id"),
        nullable=False,
    )
    deposit_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    trigger_type: Mapped[TriggerType] = mapped_column(
        SqlEnum(
            TriggerType,
            name="trigger_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    trigger_description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_land_deposit_schedule_lot_due_paid", "lot_id", "due_date", "paid_at"),
        {"schema": "land"},
    )


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = {"schema": "land"}

    id: Mapped[UUID] = _uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("land.agreements.id"),
        nullable=False,
    )
    lot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.lots.id"),
    )
    milestone_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    expected_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = [
    "Agreement",
    "DepositSchedule",
    "LotTerms",
    "Milestone",
    "SecurityDeposit",
    "TriggerType",
]
