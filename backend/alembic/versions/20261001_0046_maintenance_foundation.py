"""Add PRIVI maintenance ticketing foundation.

Revision ID: 20261001_0046
Revises: 20260917_0045
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from alembic import context, op
import phonenumbers
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261001_0046"
down_revision: str | None = "20260917_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

CATEGORIES = (
    "plumbing", "electrical", "heating", "cooling", "appliance",
    "doors_locks_windows", "pests", "exterior_grounds", "structural",
    "water_leak", "no_heat", "gas_smell", "no_power", "security", "other",
)
PRIORITIES = ("emergency", "urgent", "routine", "low")
STATUSES = (
    "new", "triaged", "assigned", "scheduled", "in_progress",
    "awaiting_parts", "awaiting_tenant", "resolved", "closed",
    "cancelled", "duplicate",
)
WO_STATUSES = ("offered", "accepted", "declined", "scheduled", "in_progress", "completed", "cancelled")
CHANNELS = ("web", "sms", "slack", "system")
VISIBILITIES = ("internal", "external")
DIRECTIONS = ("inbound", "outbound", "none")
PARTIES = ("tenant", "vendor", "staff", "system")


def _enum(name: str, values: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def _normalize_existing_tenant_phones() -> None:
    if context.is_offline_mode():
        logger.warning("tenant-phone backfill is skipped when generating offline SQL")
        return
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, phone FROM rental_tenants WHERE phone IS NOT NULL AND btrim(phone) <> '' ORDER BY id")
    ).mappings()
    normalized = 0
    failed: list[int] = []
    for row in rows:
        try:
            parsed = phonenumbers.parse(row["phone"], "CA")
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("invalid number")
            e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except (phonenumbers.NumberParseException, ValueError):
            failed.append(row["id"])
            continue
        connection.execute(
            sa.text("UPDATE rental_tenants SET phone = :phone, updated_at = now() WHERE id = :tenant_id"),
            {"phone": e164, "tenant_id": row["id"]},
        )
        normalized += 1
    logger.info("maintenance tenant-phone backfill: normalized=%d failed=%d", normalized, len(failed))
    if failed:
        logger.warning("maintenance tenant-phone backfill failures (tenant IDs): %s", ", ".join(map(str, failed)))


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in (
        ("maint_category", CATEGORIES),
        ("maint_priority", PRIORITIES),
        ("maint_status", STATUSES),
        ("maint_wo_status", WO_STATUSES),
        ("maint_event_channel", CHANNELS),
        ("maint_visibility", VISIBILITIES),
        ("maint_direction", DIRECTIONS),
        ("maint_party", PARTIES),
    ):
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    category = _enum("maint_category", CATEGORIES)
    priority = _enum("maint_priority", PRIORITIES)
    status = _enum("maint_status", STATUSES)
    wo_status = _enum("maint_wo_status", WO_STATUSES)
    channel = _enum("maint_event_channel", CHANNELS)
    visibility = _enum("maint_visibility", VISIBILITIES)
    direction = _enum("maint_direction", DIRECTIONS)
    party = _enum("maint_party", PARTIES)

    op.add_column("users", sa.Column("slack_user_id", sa.Text()), schema="core")
    op.add_column("users", sa.Column("phone_e164", sa.Text()), schema="core")
    op.create_unique_constraint("uq_core_users_slack_user_id", "users", ["slack_user_id"], schema="core")
    op.add_column(
        "rental_tenants",
        sa.Column("sms_opted_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _normalize_existing_tenant_phones()

    op.create_table(
        "maint_vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trades", postgresql.ARRAY(category), nullable=False, server_default=sa.text("'{}'::maint_category[]")),
        sa.Column("contact_name", sa.Text()),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("insurance_expiry", sa.Date()),
        sa.Column("wcb_expiry", sa.Date()),
        sa.Column("sms_opted_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_maint_vendors_active_phone", "maint_vendors", ["phone_e164"], unique=True, postgresql_where=sa.text("is_active"))

    op.create_table(
        "maint_unit_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("rental_units.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("uq_maint_unit_tokens_active_unit", "maint_unit_tokens", ["unit_id"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))

    op.execute("CREATE SEQUENCE maint_ticket_number_seq")
    op.create_table(
        "maint_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("number", sa.Text(), nullable=False, unique=True, server_default=sa.text("'MT-' || lpad(nextval('maint_ticket_number_seq')::text, 5, '0')")),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("rental_properties.id"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("rental_units.id")),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("rental_leases.id")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("reporter_party", party, nullable=False),
        sa.Column("reporter_name", sa.Text()),
        sa.Column("reporter_phone_e164", sa.Text()),
        sa.Column("reporter_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", category),
        sa.Column("priority", priority),
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", status, nullable=False, server_default="new"),
        sa.Column("entry_permission", sa.Text(), nullable=False, server_default="not_asked"),
        sa.Column("entry_notes", sa.Text()),
        sa.Column("ai_suggestion", postgresql.JSONB()),
        sa.Column("triaged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("triaged_at", sa.DateTime(timezone=True)),
        sa.Column("sla_due_at", sa.DateTime(timezone=True)),
        sa.Column("emergency_acked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("emergency_acked_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("close_reason", sa.Text()),
        sa.Column("duplicate_of", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id")),
        sa.Column("chargeback_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("inspection_id", sa.Integer(), sa.ForeignKey("rental_inspections.id")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("source IN ('tenant_qr','staff','inspection','sms')", name="ck_maint_tickets_source"),
        sa.CheckConstraint("entry_permission IN ('granted','denied','not_asked')", name="ck_maint_tickets_entry_permission"),
    )
    op.create_index("idx_maint_tickets_open_status", "maint_tickets", ["status"], postgresql_where=sa.text("status NOT IN ('closed','cancelled','duplicate')"))
    op.create_index("idx_maint_tickets_unit_created", "maint_tickets", ["unit_id", sa.text("created_at DESC")])
    op.create_index("idx_maint_tickets_open_reporter_phone", "maint_tickets", ["reporter_phone_e164"], postgresql_where=sa.text("status NOT IN ('closed','cancelled','duplicate')"))

    op.create_table(
        "maint_work_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id"), nullable=False),
        sa.Column("number", sa.Text(), nullable=False, unique=True),
        sa.Column("assignee_type", sa.Text(), nullable=False),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_vendors.id")),
        sa.Column("status", wo_status, nullable=False, server_default="offered"),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True)),
        sa.Column("scheduled_end", sa.DateTime(timezone=True)),
        sa.Column("decline_reason", sa.Text()),
        sa.Column("access_token_hash", sa.String(64), unique=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("cost_estimate", sa.Numeric(15, 2)),
        sa.Column("cost_actual", sa.Numeric(15, 2)),
        sa.Column("cost_class", sa.Text()),
        sa.Column("invoice_attachment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("completion_notes", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("assignee_type IN ('staff','vendor')", name="ck_maint_work_orders_assignee_type"),
        sa.CheckConstraint("cost_class IS NULL OR cost_class IN ('repair','capital')", name="ck_maint_work_orders_cost_class"),
        sa.CheckConstraint("(assignee_type = 'staff' AND assignee_user_id IS NOT NULL AND vendor_id IS NULL) OR (assignee_type = 'vendor' AND vendor_id IS NOT NULL AND assignee_user_id IS NULL)", name="ck_maint_work_orders_assignee"),
    )

    op.create_table(
        "maint_sms_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("direction", direction, nullable=False),
        sa.Column("from_e164", sa.Text(), nullable=False),
        sa.Column("to_e164", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("media_attachment_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id")),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_work_orders.id")),
        sa.Column("is_automated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hold_until", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("provider_sid", sa.Text(), unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.Text()),
        sa.Column("slack_channel_id", sa.Text()),
        sa.Column("slack_ts", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("direction IN ('inbound','outbound')", name="ck_maint_sms_direction"),
        sa.CheckConstraint("status IN ('pending','held','queued','sent','delivered','failed','cancelled','received')", name="ck_maint_sms_status"),
    )

    op.create_table(
        "maint_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id"), nullable=False),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_work_orders.id")),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("channel", channel, nullable=False),
        sa.Column("visibility", visibility, nullable=False),
        sa.Column("direction", direction, nullable=False, server_default="none"),
        sa.Column("actor_party", party, nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id")),
        sa.Column("actor_vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_vendors.id")),
        sa.Column("actor_phone_e164", sa.Text()),
        sa.Column("body", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sms_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_sms_messages.id")),
        sa.Column("slack_ts", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_maint_events_ticket_created", "maint_events", ["ticket_id", "created_at"])

    op.create_table(
        "maint_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id"), nullable=False),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_work_orders.id")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_events.id")),
        sa.Column("minio_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.Text()),
        sa.Column("uploaded_by_party", party, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="photo"),
        sa.Column("box_file_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('photo','invoice','document')", name="ck_maint_attachments_kind"),
    )
    op.create_foreign_key("fk_maint_work_orders_invoice_attachment", "maint_work_orders", "maint_attachments", ["invoice_attachment_id"], ["id"], use_alter=True)

    op.create_table(
        "maint_slack_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_tickets.id"), nullable=False),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maint_work_orders.id")),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("message_ts", sa.Text(), nullable=False),
        sa.Column("thread_party", party, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("channel_id", "message_ts", name="uq_maint_slack_cards_message"),
    )
    op.create_index("uq_maint_slack_cards_ticket", "maint_slack_cards", ["ticket_id"], unique=True, postgresql_where=sa.text("work_order_id IS NULL"))
    op.create_index("uq_maint_slack_cards_work_order", "maint_slack_cards", ["work_order_id"], unique=True, postgresql_where=sa.text("work_order_id IS NOT NULL"))

    op.create_table(
        "maint_on_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_backup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint("ends_at > starts_at", name="ck_maint_on_call_window"),
    )

    op.execute("""
        CREATE FUNCTION prevent_maint_event_mutation() RETURNS trigger AS $$
        DECLARE migration_role regrole;
        BEGIN
          migration_role := to_regrole('officehub_migration');
          IF migration_role IS NOT NULL AND pg_has_role(current_user, migration_role, 'member') THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
          END IF;
          RAISE EXCEPTION 'maint_events is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_maint_events_append_only
        BEFORE UPDATE OR DELETE ON maint_events
        FOR EACH ROW EXECUTE FUNCTION prevent_maint_event_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_maint_events_append_only ON maint_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_maint_event_mutation()")
    op.drop_table("maint_on_call")
    op.drop_table("maint_slack_cards")
    op.drop_constraint("fk_maint_work_orders_invoice_attachment", "maint_work_orders", type_="foreignkey")
    op.drop_table("maint_attachments")
    op.drop_table("maint_events")
    op.drop_table("maint_sms_messages")
    op.drop_table("maint_work_orders")
    op.drop_table("maint_tickets")
    op.execute("DROP SEQUENCE maint_ticket_number_seq")
    op.drop_table("maint_unit_tokens")
    op.drop_table("maint_vendors")
    op.drop_column("rental_tenants", "sms_opted_out")
    op.drop_constraint("uq_core_users_slack_user_id", "users", schema="core", type_="unique")
    op.drop_column("users", "phone_e164", schema="core")
    op.drop_column("users", "slack_user_id", schema="core")
    for name in (
        "maint_party", "maint_direction", "maint_visibility", "maint_event_channel",
        "maint_wo_status", "maint_status", "maint_priority", "maint_category",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
