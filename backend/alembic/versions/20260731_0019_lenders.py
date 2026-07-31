"""Add reusable lenders and link lender facilities.

Revision ID: 20260731_0019
Revises: 20260715_0010
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260731_0019"
down_revision: str | None = "20260715_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lenders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255)),
        sa.Column("contact_email", sa.String(length=320)),
        sa.Column("contact_phone", sa.String(length=50)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_core_lenders_name"),
        schema="core",
    )
    op.create_index(
        "uq_core_lenders_name_lower",
        "lenders",
        [sa.text("lower(name)")],
        unique=True,
        schema="core",
    )
    op.add_column(
        "lender_facilities",
        sa.Column("lender_id", postgresql.UUID(as_uuid=True)),
        schema="core",
    )
    op.create_foreign_key(
        "fk_core_lender_facilities_lender_id",
        "lender_facilities",
        "lenders",
        ["lender_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="RESTRICT",
    )
    op.create_index(
        "idx_core_lender_facilities_lender_id",
        "lender_facilities",
        ["lender_id"],
        schema="core",
    )

    op.execute(
        """
        INSERT INTO core.lenders (name)
        SELECT DISTINCT btrim(lender_name)
        FROM core.lender_facilities
        WHERE lender_name IS NOT NULL
          AND btrim(lender_name) <> ''
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO core.lenders (name)
        VALUES ('ProAuto'), ('Steinbach Credit Union')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities AS facility
        SET lender_id = lender.id
        FROM core.lenders AS lender
        WHERE facility.lender_name IS NOT NULL
          AND lower(btrim(facility.lender_name)) = lower(lender.name)
        """
    )
    # This migration is an isolated branch from the last committed revision.
    # Preserve links if pending financing migrations insert named facilities
    # after this branch is applied during an `upgrade heads` deployment.
    op.execute(
        """
        CREATE FUNCTION core.link_lender_facility_by_name()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.lender_id IS NULL AND NEW.lender_name IS NOT NULL THEN
                SELECT id INTO NEW.lender_id
                FROM core.lenders
                WHERE lower(name) = lower(btrim(NEW.lender_name));
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_link_lender_facility_by_name
        BEFORE INSERT OR UPDATE OF lender_name ON core.lender_facilities
        FOR EACH ROW
        EXECUTE FUNCTION core.link_lender_facility_by_name()
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities AS facility
        SET lender_id = lender.id,
            lender_name = lender.name,
            updated_at = now()
        FROM core.lenders AS lender
        JOIN core.properties AS property
          ON property.address IN ('106 Buffalo Trail', '158 Rosybloom Lane')
        WHERE lender.name = 'Steinbach Credit Union'
          AND facility.property_id = property.id
          AND facility.lender_type = 'SCU'
          AND facility.lender_name IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_link_lender_facility_by_name ON core.lender_facilities"
    )
    op.execute("DROP FUNCTION IF EXISTS core.link_lender_facility_by_name()")
    op.drop_index(
        "idx_core_lender_facilities_lender_id",
        table_name="lender_facilities",
        schema="core",
    )
    op.drop_constraint(
        "fk_core_lender_facilities_lender_id",
        "lender_facilities",
        schema="core",
        type_="foreignkey",
    )
    op.drop_column("lender_facilities", "lender_id", schema="core")
    op.drop_index(
        "uq_core_lenders_name_lower",
        table_name="lenders",
        schema="core",
    )
    op.drop_table("lenders", schema="core")
