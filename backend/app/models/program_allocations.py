from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Numeric
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.core.database import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=func.gen_random_uuid(),
        server_default=func.gen_random_uuid(),
    )


class LenderProgram(Base):
    __tablename__ = "lender_programs"
    __table_args__ = (
        UniqueConstraint("lender_id", "name", name="uq_lender_programs_lender_name"),
        CheckConstraint("umbrella_limit >= 0", name="ck_lender_programs_umbrella_limit"),
        {"schema": "financing"},
    )

    id: Mapped[UUID] = _uuid_pk()
    lender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lenders.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    umbrella_limit: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProgramAllocation(Base):
    __tablename__ = "program_allocations"
    __table_args__ = (
        UniqueConstraint("program_id", "name", name="uq_program_allocations_program_name"),
        CheckConstraint("allocation_limit >= 0", name="ck_program_allocations_limit"),
        CheckConstraint("max_units >= 0", name="ck_program_allocations_max_units"),
        CheckConstraint("max_per_unit IS NULL OR max_per_unit >= 0", name="ck_program_allocations_max_per_unit"),
        CheckConstraint("funding_percentage >= 0", name="ck_program_allocations_funding_percentage"),
        {"schema": "financing"},
    )

    id: Mapped[UUID] = _uuid_pk()
    program_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("financing.lender_programs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    allocation_limit: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    max_units: Mapped[int] = mapped_column(Integer, nullable=False)
    max_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    funding_percentage: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class AllocationTier(Base):
    __tablename__ = "allocation_tiers"
    __table_args__ = (
        CheckConstraint("face_value >= 0", name="ck_allocation_tiers_face_value"),
        CheckConstraint("slot_count >= 0", name="ck_allocation_tiers_slot_count"),
        CheckConstraint(
            "(build_group_type IS NULL AND amount_per_unit IS NULL AND units_per_group IS NULL AND group_ceiling IS NULL) OR "
            "(build_group_type IS NOT NULL AND amount_per_unit IS NOT NULL AND units_per_group IS NOT NULL AND group_ceiling IS NOT NULL)",
            name="ck_allocation_tiers_group_config_complete",
        ),
        CheckConstraint(
            "group_ceiling IS NULL OR group_ceiling = amount_per_unit * units_per_group",
            name="ck_allocation_tiers_group_ceiling",
        ),
        {"schema": "financing"},
    )

    id: Mapped[UUID] = _uuid_pk()
    allocation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("financing.program_allocations.id", ondelete="CASCADE"), nullable=False
    )
    face_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    slot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    build_group_type: Mapped[str | None] = mapped_column(Text)
    amount_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    units_per_group: Mapped[int | None] = mapped_column(Integer)
    group_ceiling: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))


class BuildGroupFundingDecision(Base):
    __tablename__ = "build_group_funding_decisions"
    __table_args__ = (
        UniqueConstraint("build_group_id", "allocation_id", name="uq_build_group_funding_decisions_group_allocation"),
        CheckConstraint("status IN ('draft','approved','released')", name="ck_build_group_funding_decisions_status"),
        CheckConstraint("unit_count > 0", name="ck_build_group_funding_decisions_unit_count"),
        CheckConstraint("slots_consumed > 0", name="ck_build_group_funding_decisions_slots"),
        CheckConstraint("amount_per_unit >= 0", name="ck_build_group_funding_decisions_amount"),
        CheckConstraint("group_ceiling = amount_per_unit * unit_count", name="ck_build_group_funding_decisions_ceiling"),
        {"schema": "financing"},
    )

    id: Mapped[UUID] = _uuid_pk()
    build_group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.build_groups.id", ondelete="RESTRICT"), nullable=False
    )
    allocation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("financing.program_allocations.id", ondelete="RESTRICT"), nullable=False
    )
    tier_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("financing.allocation_tiers.id", ondelete="RESTRICT"), nullable=False
    )
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_per_unit: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    group_ceiling: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    slots_consumed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AllocationRequest(Base):
    __tablename__ = "allocation_requests"
    __table_args__ = (
        CheckConstraint("basis_value >= 0", name="ck_allocation_requests_basis_value"),
        CheckConstraint("suggested_amount >= 0", name="ck_allocation_requests_suggested_amount"),
        CheckConstraint("actual_amount IS NULL OR actual_amount >= 0", name="ck_allocation_requests_actual_amount"),
        CheckConstraint(
            "status IN ('draft','requested','approved','released')",
            name="ck_allocation_requests_status",
        ),
        CheckConstraint(
            "basis_source IN ('appraisal','estimated_sale_price','lesser_of_appraisal_and_estimated_sale_price','lot_purchase_price','explicit_historical')",
            name="ck_allocation_requests_basis_source",
        ),
        {"schema": "financing"},
    )

    id: Mapped[UUID] = _uuid_pk()
    allocation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("financing.program_allocations.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="RESTRICT"), nullable=False
    )
    property_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.properties.id", ondelete="SET NULL")
    )
    funding_decision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("financing.build_group_funding_decisions.id", ondelete="RESTRICT"),
    )
    appraisal_value: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    estimated_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    basis_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    basis_source: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    nearest_tier_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("financing.allocation_tiers.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "AllocationRequest",
    "AllocationTier",
    "BuildGroupFundingDecision",
    "LenderProgram",
    "ProgramAllocation",
]
