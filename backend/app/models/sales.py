from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint
from sqlalchemy import Boolean
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import Numeric
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

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


class SalesAgreementStatus(str, Enum):
    RECEIVED = "received"
    CONDITIONS_PENDING = "conditions_pending"
    FIRM = "firm"
    BUILD_STARTED = "build_started"
    POSSESSION_COMPLETE = "possession_complete"
    COLLAPSED = "collapsed"


class PartyRole(str, Enum):
    BUYER = "buyer"
    CO_BUYER = "co_buyer"
    BUYERS_REALTOR = "buyers_realtor"
    SELLERS_REALTOR = "sellers_realtor"


class SalesAgreement(Base):
    __tablename__ = "agreements"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.lots.id"),
        nullable=False,
    )
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
    sale_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    agreement_date: Mapped[date | None] = mapped_column(Date)
    possession_date: Mapped[date | None] = mapped_column(Date)
    condition_removal_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[SalesAgreementStatus] = mapped_column(
        SqlEnum(
            SalesAgreementStatus,
            name="sales_agreement_status",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=SalesAgreementStatus.RECEIVED,
        server_default=text("'received'"),
    )
    conditions: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    notable_clauses: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_sales_agreements_lot_status", "lot_id", "status"),
        {"schema": "sales"},
    )


class Party(Base):
    __tablename__ = "parties"
    __table_args__ = {"schema": "sales"}

    id: Mapped[UUID] = _uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sales.agreements.id"),
        nullable=False,
    )
    contact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.contacts.id"),
        nullable=False,
    )
    party_role: Mapped[PartyRole] = mapped_column(
        SqlEnum(
            PartyRole,
            name="party_role",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SalesDepositSchedule(Base):
    __tablename__ = "deposit_schedule"

    id: Mapped[UUID] = _uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sales.agreements.id"),
        nullable=False,
    )
    deposit_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    held_by: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("held_by IN ('realtor', 'lawyer', 'builder')"),
        {"schema": "sales"},
    )


class ChangeOrder(Base):
    __tablename__ = "change_orders"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("land.agreements.id", ondelete="SET NULL"),
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    co_number: Mapped[str | None] = mapped_column(Text)
    date: Mapped[date | None] = mapped_column(Date)
    payment_method: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="due_upon_receipt",
        server_default=text("'due_upon_receipt'"),
    )
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="draft",
        server_default=text("'draft'"),
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    gst: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    docusign_envelope_id: Mapped[str | None] = mapped_column(Text)
    box_file_id: Mapped[str | None] = mapped_column(Text)
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.orgs.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    line_items: Mapped[list["ChangeOrderLineItem"]] = relationship(
        back_populates="change_order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChangeOrderLineItem.sort_order",
    )

    __table_args__ = (
        Index("idx_sales_change_orders_org_status_created", "org_id", "status", created_at.desc()),
        {"schema": "sales"},
    )


class ChangeOrderLineItem(Base):
    __tablename__ = "change_order_line_items"

    id: Mapped[UUID] = _uuid_pk()
    change_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sales.change_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    is_credit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    change_order: Mapped[ChangeOrder] = relationship(back_populates="line_items")

    __table_args__ = (
        Index("idx_sales_change_order_line_items_change_order", "change_order_id"),
        {"schema": "sales"},
    )


__all__ = [
    "ChangeOrder",
    "ChangeOrderLineItem",
    "Party",
    "PartyRole",
    "SalesAgreement",
    "SalesAgreementStatus",
    "SalesDepositSchedule",
]
