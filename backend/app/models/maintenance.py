from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer
from sqlalchemy import Numeric, Sequence, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

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


class MaintCategory(str, Enum):
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    HEATING = "heating"
    COOLING = "cooling"
    APPLIANCE = "appliance"
    DOORS_LOCKS_WINDOWS = "doors_locks_windows"
    PESTS = "pests"
    EXTERIOR_GROUNDS = "exterior_grounds"
    STRUCTURAL = "structural"
    WATER_LEAK = "water_leak"
    NO_HEAT = "no_heat"
    GAS_SMELL = "gas_smell"
    NO_POWER = "no_power"
    SECURITY = "security"
    OTHER = "other"


class MaintPriority(str, Enum):
    EMERGENCY = "emergency"
    URGENT = "urgent"
    ROUTINE = "routine"
    LOW = "low"


class MaintStatus(str, Enum):
    NEW = "new"
    TRIAGED = "triaged"
    ASSIGNED = "assigned"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    AWAITING_PARTS = "awaiting_parts"
    AWAITING_TENANT = "awaiting_tenant"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    DUPLICATE = "duplicate"


class MaintWorkOrderStatus(str, Enum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MaintEventChannel(str, Enum):
    WEB = "web"
    SMS = "sms"
    SLACK = "slack"
    SYSTEM = "system"


class MaintVisibility(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class MaintDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    NONE = "none"


class MaintParty(str, Enum):
    TENANT = "tenant"
    VENDOR = "vendor"
    STAFF = "staff"
    SYSTEM = "system"


def _db_enum(enum_cls: type[Enum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        name=name,
        values_callable=_enum_values,
        validate_strings=True,
    )


MAINT_CATEGORY_DB = _db_enum(MaintCategory, "maint_category")
MAINT_PRIORITY_DB = _db_enum(MaintPriority, "maint_priority")
MAINT_STATUS_DB = _db_enum(MaintStatus, "maint_status")
MAINT_WO_STATUS_DB = _db_enum(MaintWorkOrderStatus, "maint_wo_status")
MAINT_EVENT_CHANNEL_DB = _db_enum(MaintEventChannel, "maint_event_channel")
MAINT_VISIBILITY_DB = _db_enum(MaintVisibility, "maint_visibility")
MAINT_DIRECTION_DB = _db_enum(MaintDirection, "maint_direction")
MAINT_PARTY_DB = _db_enum(MaintParty, "maint_party")


class MaintVendor(Base):
    __tablename__ = "maint_vendors"

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trades: Mapped[list[MaintCategory]] = mapped_column(
        ARRAY(MAINT_CATEGORY_DB), nullable=False, default=list, server_default=text("'{}'")
    )
    contact_name: Mapped[str | None] = mapped_column(Text)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    insurance_expiry: Mapped[date | None] = mapped_column(Date)
    wcb_expiry: Mapped[date | None] = mapped_column(Date)
    sms_opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("uq_maint_vendors_active_phone", "phone_e164", unique=True, postgresql_where=text("is_active")),
    )


class MaintUnitToken(Base):
    __tablename__ = "maint_unit_tokens"

    id: Mapped[UUID] = _uuid_pk()
    unit_id: Mapped[int] = mapped_column(ForeignKey("rental_units.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_maint_unit_tokens_active_unit", "unit_id", unique=True, postgresql_where=text("revoked_at IS NULL")),
    )


class MaintIntakeToken(Base):
    """Short-lived intake links created for known tenants who text without an open ticket."""

    __tablename__ = "maint_intake_tokens"

    id: Mapped[UUID] = _uuid_pk()
    unit_id: Mapped[int] = mapped_column(ForeignKey("rental_units.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


maint_ticket_number_seq = Sequence("maint_ticket_number_seq")


class MaintTicket(Base):
    __tablename__ = "maint_tickets"

    id: Mapped[UUID] = _uuid_pk()
    number: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
        server_default=text("'MT-' || lpad(nextval('maint_ticket_number_seq')::text, 5, '0')"),
    )
    property_id: Mapped[int] = mapped_column(ForeignKey("rental_properties.id"), nullable=False)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("rental_units.id"))
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("rental_leases.id"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    reporter_party: Mapped[MaintParty] = mapped_column(MAINT_PARTY_DB, nullable=False)
    reporter_name: Mapped[str | None] = mapped_column(Text)
    reporter_phone_e164: Mapped[str | None] = mapped_column(Text)
    reporter_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[MaintCategory | None] = mapped_column(MAINT_CATEGORY_DB)
    priority: Mapped[MaintPriority | None] = mapped_column(MAINT_PRIORITY_DB)
    is_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[MaintStatus] = mapped_column(
        MAINT_STATUS_DB, nullable=False, default=MaintStatus.NEW, server_default=MaintStatus.NEW.value
    )
    entry_permission: Mapped[str] = mapped_column(Text, nullable=False, default="not_asked", server_default="not_asked")
    entry_notes: Mapped[str | None] = mapped_column(Text)
    ai_suggestion: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    triaged_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emergency_acked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    emergency_acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(Text)
    duplicate_of: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_tickets.id"))
    chargeback_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    inspection_id: Mapped[int | None] = mapped_column(ForeignKey("rental_inspections.id"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("source IN ('tenant_qr','staff','inspection','sms')", name="ck_maint_tickets_source"),
        CheckConstraint("entry_permission IN ('granted','denied','not_asked')", name="ck_maint_tickets_entry_permission"),
        Index("idx_maint_tickets_open_status", "status", postgresql_where=text("status NOT IN ('closed','cancelled','duplicate')")),
        Index("idx_maint_tickets_unit_created", "unit_id", text("created_at DESC")),
        Index("idx_maint_tickets_open_reporter_phone", "reporter_phone_e164", postgresql_where=text("status NOT IN ('closed','cancelled','duplicate')")),
    )


class MaintWorkOrder(Base):
    __tablename__ = "maint_work_orders"

    id: Mapped[UUID] = _uuid_pk()
    ticket_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_tickets.id"), nullable=False)
    number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    assignee_type: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    vendor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_vendors.id"))
    status: Mapped[MaintWorkOrderStatus] = mapped_column(
        MAINT_WO_STATUS_DB, nullable=False, default=MaintWorkOrderStatus.OFFERED, server_default=MaintWorkOrderStatus.OFFERED.value
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(Text)
    access_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cost_actual: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cost_class: Mapped[str | None] = mapped_column(Text)
    invoice_attachment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("maint_attachments.id", use_alter=True, name="fk_maint_work_orders_invoice_attachment"),
    )
    completion_notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("assignee_type IN ('staff','vendor')", name="ck_maint_work_orders_assignee_type"),
        CheckConstraint("cost_class IS NULL OR cost_class IN ('repair','capital')", name="ck_maint_work_orders_cost_class"),
        CheckConstraint(
            "(assignee_type = 'staff' AND assignee_user_id IS NOT NULL AND vendor_id IS NULL) OR "
            "(assignee_type = 'vendor' AND vendor_id IS NOT NULL AND assignee_user_id IS NULL)",
            name="ck_maint_work_orders_assignee",
        ),
    )


class MaintSmsMessage(Base):
    __tablename__ = "maint_sms_messages"

    id: Mapped[UUID] = _uuid_pk()
    direction: Mapped[MaintDirection] = mapped_column(MAINT_DIRECTION_DB, nullable=False)
    from_e164: Mapped[str] = mapped_column(Text, nullable=False)
    to_e164: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    media_attachment_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    ticket_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_tickets.id"))
    work_order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_work_orders.id"))
    is_automated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_sid: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("direction IN ('inbound','outbound')", name="ck_maint_sms_direction"),
        CheckConstraint("status IN ('pending','held','queued','sent','delivered','failed','cancelled','received')", name="ck_maint_sms_status"),
    )


class MaintEvent(Base):
    __tablename__ = "maint_events"

    id: Mapped[UUID] = _uuid_pk()
    ticket_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_tickets.id"), nullable=False)
    work_order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_work_orders.id"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[MaintEventChannel] = mapped_column(MAINT_EVENT_CHANNEL_DB, nullable=False)
    visibility: Mapped[MaintVisibility] = mapped_column(MAINT_VISIBILITY_DB, nullable=False)
    direction: Mapped[MaintDirection] = mapped_column(
        MAINT_DIRECTION_DB, nullable=False, default=MaintDirection.NONE, server_default=MaintDirection.NONE.value
    )
    actor_party: Mapped[MaintParty] = mapped_column(MAINT_PARTY_DB, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"))
    actor_vendor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_vendors.id"))
    actor_phone_e164: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    sms_message_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_sms_messages.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_maint_events_ticket_created", "ticket_id", "created_at"),)


class MaintAttachment(Base):
    __tablename__ = "maint_attachments"

    id: Mapped[UUID] = _uuid_pk()
    ticket_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_tickets.id"))
    work_order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_work_orders.id"))
    event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_events.id"))
    minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    uploaded_by_party: Mapped[MaintParty] = mapped_column(MAINT_PARTY_DB, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="photo", server_default="photo")
    box_file_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("kind IN ('photo','invoice','document')", name="ck_maint_attachments_kind"),
    )


class MaintSlackOutbox(Base):
    __tablename__ = "maint_slack_outbox"

    id: Mapped[UUID] = _uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_tickets.id"))
    work_order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_work_orders.id"))
    sms_message_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("maint_sms_messages.id"))
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_maint_slack_outbox_attempts"),
        Index(
            "idx_maint_slack_outbox_due",
            "available_at",
            "created_at",
            postgresql_where=text("delivered_at IS NULL AND failed_at IS NULL"),
        ),
    )


class MaintOnCall(Base):
    __tablename__ = "maint_on_call"

    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_backup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ck_maint_on_call_window"),)
