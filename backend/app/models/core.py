from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import String
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy import Index
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


class UserRole(str, Enum):
    ADMIN = "admin"
    STAFF = "staff"
    READONLY = "readonly"


class UserOrgRole(str, Enum):
    TENANT_ADMIN = "tenant_admin"
    MEMBER = "member"


class OrgProjectScope(str, Enum):
    ORG = "org"
    ASSIGNED = "assigned"


class ClientType(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class ClientLifecycleStage(str, Enum):
    LEAD = "lead"
    QUALIFIED = "qualified"
    ACTIVE = "active"
    POSSESSION = "possession"
    WARRANTY = "warranty"
    CLOSED = "closed"
    LOST = "lost"


class ProjectRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ContactType(str, Enum):
    DEVELOPER = "developer"
    BUYER = "buyer"
    REALTOR = "realtor"
    VENDOR = "vendor"
    LAWYER = "lawyer"


class LotStatus(str, Enum):
    LAND_CONTRACTED = "land_contracted"
    LAND_PURCHASED = "land_purchased"
    SERVICED = "serviced"
    SALE_SIGNED = "sale_signed"
    BUILD_ACTIVE = "build_active"
    POSSESSION = "possession"
    WARRANTY = "warranty"


class LotTriggerType(str, Enum):
    OTP = "otp"
    SPEC = "spec"
    SHOWHOME = "showhome"


class SaleType(str, Enum):
    PRESALE = "presale"
    SPEC = "spec"
    SHOWHOME = "showhome"
    OTHER = "other"


class BuildingType(str, Enum):
    BUNGALOW = "bungalow"
    TWO_STOREY = "two_storey"
    DUPLEX = "duplex"
    OTHER = "other"


class DevelopmentType(str, Enum):
    MUNICIPALITY = "municipality"
    COMMUNITY = "community"
    SUBDIVISION = "subdivision"


class LegalDescriptionVerificationStatus(str, Enum):
    TITLE_CONFIRMED = "title_confirmed"
    PERMIT_AGREEMENT_CONFIRMED = "permit_agreement_confirmed"


class BuildGroup(Base):
    __tablename__ = "build_groups"

    id: Mapped[UUID] = _uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.orgs.id", ondelete="RESTRICT"), nullable=False
    )
    development_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.developments.id", ondelete="RESTRICT"), nullable=False
    )
    group_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed", server_default=text("'proposed'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("group_type IN ('duplex')", name="ck_core_build_groups_type"),
        CheckConstraint(
            "status IN ('proposed','active','completed','cancelled')",
            name="ck_core_build_groups_status",
        ),
        Index("idx_core_build_groups_org_status", "org_id", "status"),
        Index("idx_core_build_groups_development", "development_id"),
        {"schema": "core"},
    )


class Org(Base):
    __tablename__ = "orgs"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    member_project_scope: Mapped[OrgProjectScope] = mapped_column(
        SqlEnum(OrgProjectScope, name="ck_core_orgs_member_project_scope", native_enum=False,
                create_constraint=False, values_callable=_enum_values, validate_strings=True, length=8),
        nullable=False,
        default=OrgProjectScope.ASSIGNED,
        server_default=OrgProjectScope.ASSIGNED.value,
    )
    land_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = _uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.orgs.id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    google_subject: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SqlEnum(
            UserRole,
            name="user_role",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    permissions: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    slack_user_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    phone_e164: Mapped[str | None] = mapped_column(Text, nullable=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invite_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserOrgMembership(Base):
    __tablename__ = "user_org_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_core_user_org_memberships_user_org"),
        Index("idx_core_user_org_memberships_org_id", "org_id"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.orgs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[UserOrgRole] = mapped_column(
        SqlEnum(UserOrgRole, name="ck_core_user_org_memberships_role", native_enum=False,
                create_constraint=True, values_callable=_enum_values, validate_strings=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("lot_id", "user_id", name="uq_core_project_members_lot_user"),
        Index("idx_core_project_members_user_id", "user_id"),
        Index("idx_core_project_members_lot_id", "lot_id"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.lots.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ProjectRole] = mapped_column(
        SqlEnum(ProjectRole, name="ck_core_project_members_role", native_enum=False,
                create_constraint=True, values_callable=_enum_values, validate_strings=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    invited_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True
    )


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_core_contacts_id_org"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = _uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.orgs.id"),
        nullable=False,
    )
    contact_type: Mapped[ContactType] = mapped_column(
        SqlEnum(
            ContactType,
            name="contact_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
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


class Client(Base):
    """Tenant-owned client record; projects link to it through ``core.lots.client_id``."""

    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("client_type IN ('individual', 'company')", name="ck_core_clients_client_type"),
        CheckConstraint(
            "lifecycle_stage IN ('lead', 'qualified', 'active', 'possession', 'warranty', 'closed', 'lost')",
            name="ck_core_clients_lifecycle_stage",
        ),
        ForeignKeyConstraint(
            ["primary_contact_id", "org_id"],
            ["core.contacts.id", "core.contacts.org_id"],
            name="fk_core_clients_primary_contact_same_org",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "org_id", name="uq_core_clients_id_org"),
        Index("idx_core_clients_org_name", "org_id", "name_normalized"),
        Index("idx_core_clients_org_stage", "org_id", "lifecycle_stage"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = _uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.orgs.id", ondelete="RESTRICT"), nullable=False
    )
    client_type: Mapped[str] = mapped_column(Text, nullable=False, default="individual", server_default="individual")
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    primary_contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lifecycle_stage: Mapped[str] = mapped_column(Text, nullable=False, default="lead", server_default="lead")
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    external_ref: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Development(Base):
    __tablename__ = "developments"

    id: Mapped[UUID] = _uuid_pk()
    org_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.orgs.id"),
        nullable=False,
    )
    developer_contact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.contacts.id"),
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.developments.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    development_type: Mapped[DevelopmentType] = mapped_column(
        SqlEnum(
            DevelopmentType,
            name="development_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    municipality: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(Text)
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
        Index("idx_core_developments_parent_id", "parent_id"),
        Index(
            "uq_core_developments_sibling_name",
            "org_id",
            "parent_id",
            "name_normalized",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "core"},
    )


class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[UUID] = _uuid_pk()
    development_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.developments.id"),
        nullable=False,
    )
    property_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    build_group_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.build_groups.id", ondelete="RESTRICT"),
        nullable=True,
    )
    client_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.clients.id", ondelete="RESTRICT", name="fk_core_lots_client_id"),
        nullable=True,
    )
    trigger_type: Mapped[LotTriggerType | None] = mapped_column(
        SqlEnum(
            LotTriggerType,
            name="ck_core_lots_trigger_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=True,
    )
    on_hold: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    cancelled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    sale_type: Mapped[SaleType | None] = mapped_column(
        SqlEnum(
            SaleType,
            name="ck_core_lots_sale_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        )
    )
    building_type: Mapped[BuildingType | None] = mapped_column(
        SqlEnum(
            BuildingType,
            name="ck_core_lots_building_type",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        )
    )
    realtor_name: Mapped[str | None] = mapped_column(Text)
    realtor_email: Mapped[str | None] = mapped_column(Text)
    realtor_brokerage: Mapped[str | None] = mapped_column(Text)
    active_approval_letter_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.presale_approval_letters.id", ondelete="SET NULL")
    )
    funding_partner_suggested: Mapped[str | None] = mapped_column(Text)
    funding_readiness: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    package_sent_to: Mapped[str | None] = mapped_column(Text)
    package_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_description_raw: Mapped[str | None] = mapped_column(Text)
    legal_description_normalized: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    location_set_by: Mapped[UUID | None] = mapped_column(ForeignKey("core.users.id", ondelete="SET NULL"))
    geocode_snapshot: Mapped[dict | None] = mapped_column(JSON)
    geocode_precision: Mapped[str | None] = mapped_column(String(20))
    geocode_source: Mapped[str | None] = mapped_column(String(100))
    geocoded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    civic_address: Mapped[str | None] = mapped_column(Text)
    street_number: Mapped[str | None] = mapped_column(Text)
    street_name: Mapped[str | None] = mapped_column(Text)
    lot_number: Mapped[str | None] = mapped_column(Text)
    block: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str | None] = mapped_column(Text)
    legal_description_verification_status: Mapped[LegalDescriptionVerificationStatus | None] = mapped_column(
        SqlEnum(
            LegalDescriptionVerificationStatus,
            name="legal_description_verification_status",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        )
    )
    legal_description_source: Mapped[str | None] = mapped_column(Text)
    legal_description_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[LotStatus] = mapped_column(
        SqlEnum(
            LotStatus,
            name="lot_status",
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=LotStatus.LAND_CONTRACTED,
        server_default=text("'land_contracted'"),
    )
    possession_confirmed_date: Mapped[date | None] = mapped_column(Date)
    possession_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_date: Mapped[date | None] = mapped_column(Date)
    final_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    net_proceeds: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
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

    __table_args__ = (
        Index("idx_core_lots_development_status", "development_id", "status"),
        Index("idx_core_lots_build_group_id", "build_group_id"),
        Index(
            "uq_core_lots_property_id_not_null",
            "property_id",
            unique=True,
            postgresql_where=text("property_id IS NOT NULL"),
        ),
        {"schema": "core"},
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[UUID] = _uuid_pk()
    lot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.lots.id"),
    )
    entity_table: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reminder_type: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_dismissed: Mapped[bool] = mapped_column(
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

    __table_args__ = (
        Index("idx_core_reminders_lot_due_sent", "lot_id", "due_at", "is_sent"),
        {"schema": "core"},
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.users.id"),
    )
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    old_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('INSERT', 'UPDATE', 'DELETE', 'PROMOTE', 'MATCHED_EXISTING')"
        ),
        Index(
            "idx_core_audit_log_table_record_changed_at",
            "table_name",
            "record_id",
            text("changed_at DESC"),
        ),
        {"schema": "core"},
    )


__all__ = [
    "AuditLog",
    "BuildGroup",
    "BuildingType",
    "Client",
    "ClientLifecycleStage",
    "ClientType",
    "Contact",
    "ContactType",
    "Development",
    "Lot",
    "LotStatus",
    "Org",
    "OrgProjectScope",
    "Reminder",
    "SaleType",
    "User",
    "UserRole",
]
