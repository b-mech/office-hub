from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, SmallInteger, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RentalCompany(Base):
    __tablename__ = "rental_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RentalProperty(Base):
    __tablename__ = "rental_properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("rental_companies.id"), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(100))
    street_address: Mapped[str] = mapped_column(String(255), nullable=False)
    former_address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100), server_default="Winnipeg")
    property_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="residential")
    general_notes: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalUnit(Base):
    __tablename__ = "rental_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("rental_properties.id"), nullable=False)
    unit_label: Mapped[str | None] = mapped_column(String(50))
    is_basement: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    water_credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    water_deal_raw: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalTenant(Base):
    __tablename__ = "rental_tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    secondary_email: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalLease(Base):
    __tablename__ = "rental_leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("rental_units.id"), nullable=False)
    rent: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    rent_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rent_discount_raw: Mapped[str | None] = mapped_column(String(100))
    deposit: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    lease_start: Mapped[date | None] = mapped_column(Date)
    lease_end: Mapped[date | None] = mapped_column(Date)
    date_parse_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    lease_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalLeaseTenant(Base):
    __tablename__ = "rental_lease_tenants"

    lease_id: Mapped[int] = mapped_column(ForeignKey("rental_leases.id"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("rental_tenants.id"), primary_key=True)
    is_primary_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class RentalInspection(Base):
    __tablename__ = "rental_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("rental_units.id"), nullable=False)
    inspection_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="exterior")
    inspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    inspector_name: Mapped[str | None] = mapped_column(String(100))
    front_yard_score: Mapped[int | None] = mapped_column(SmallInteger)
    front_yard_notes: Mapped[str | None] = mapped_column(Text)
    back_yard_score: Mapped[int | None] = mapped_column(SmallInteger)
    back_yard_notes: Mapped[str | None] = mapped_column(Text)
    building_condition: Mapped[str | None] = mapped_column(String(50))
    building_notes: Mapped[str | None] = mapped_column(Text)
    occupancy_flag: Mapped[str | None] = mapped_column(String(20))
    general_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalInspectionPhoto(Base):
    __tablename__ = "rental_inspection_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("rental_inspections.id"), nullable=False)
    box_file_id: Mapped[str | None] = mapped_column(String(100))
    box_folder_path: Mapped[str | None] = mapped_column(String(500))
    caption: Mapped[str | None] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RentalInspectionReport(Base):
    __tablename__ = "rental_inspection_reports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    recipient_email: Mapped[str | None] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalInspectionReportItem(Base):
    __tablename__ = "rental_inspection_report_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    report_id: Mapped[UUID] = mapped_column(ForeignKey("rental_inspection_reports.id", ondelete="CASCADE"), nullable=False)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("rental_inspections.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    notes_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RentalLeaseImportBatch(Base):
    __tablename__ = "rental_lease_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="processing")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_pending: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class RentalLeaseImportRow(Base):
    __tablename__ = "rental_lease_import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("rental_lease_import_batches.id"), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    parsed_data: Mapped[dict[str, object] | None] = mapped_column(JSON)
    confidence: Mapped[dict[str, object] | None] = mapped_column(JSON)
    match_type: Mapped[str | None] = mapped_column(String(20))
    matched_unit_id: Mapped[int | None] = mapped_column(ForeignKey("rental_units.id"))
    suggested_action: Mapped[str | None] = mapped_column(String(20))
    existing_lease_id: Mapped[int | None] = mapped_column(ForeignKey("rental_leases.id"))
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="needs_review")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_lease_id: Mapped[int | None] = mapped_column(ForeignKey("rental_leases.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
