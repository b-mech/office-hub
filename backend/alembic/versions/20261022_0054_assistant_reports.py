"""Assistant conversations, registered sources, reports, and access log.

Revision ID: 20261022_0054
Revises: 20261020_0053
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "20261022_0054"
down_revision = "20261020_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("assistant_conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default="New conversation"),
        sa.Column("openclaw_session_key", sa.Text(), nullable=False, unique=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema="core")
    op.create_table("data_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False), sa.Column("type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("schema_hint", JSONB()), sa.Column("permission_domain", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('box_folder','box_file','google_sheet')", name="ck_data_sources_type"), schema="core")
    op.create_table("reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False), sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("core.assistant_conversations.id")),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("progress_text", sa.Text()), sa.Column("error", sa.Text()),
        sa.Column("source_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("output_md_key", sa.Text()), sa.Column("output_html_key", sa.Text()),
        sa.Column("attachments", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sources_used", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary", sa.Text()), sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("parent_report_id", UUID(as_uuid=True), sa.ForeignKey("core.reports.id")),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name="ck_reports_status"), schema="core")
    op.create_table("assistant_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("core.assistant_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("report_id", UUID(as_uuid=True), sa.ForeignKey("core.reports.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user','assistant','system_event')", name="ck_assistant_messages_role"), schema="core")
    op.create_table("agent_data_access_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_token_hash", sa.Text(), nullable=False), sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("report_id", UUID(as_uuid=True)), sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True)), sa.Column("external_id", sa.Text()),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema="core")
    op.create_index("ix_agent_data_access_log_created_at", "agent_data_access_log", ["created_at"], schema="core")
    op.execute("UPDATE core.users SET permissions = (permissions::jsonb || '{\"assistant.use\":\"viewer\"}'::jsonb)::json WHERE role = 'staff' AND COALESCE(permissions->>'assistant.use', 'none') = 'none'")


def downgrade() -> None:
    op.drop_index("ix_agent_data_access_log_created_at", table_name="agent_data_access_log", schema="core")
    for name in ("agent_data_access_log", "assistant_messages", "reports", "data_sources", "assistant_conversations"):
        op.drop_table(name, schema="core")
