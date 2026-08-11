"""Add development hierarchy and lot legal-description verification.

Revision ID: 20260811_0034
Revises: 20260811_0033
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_0034"
down_revision: str | None = "20260811_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "developments",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="core",
    )
    op.add_column(
        "developments",
        sa.Column("name_normalized", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column(
        "developments",
        sa.Column("development_type", sa.Text(), nullable=True),
        schema="core",
    )
    op.create_foreign_key(
        "fk_core_developments_parent_id",
        "developments",
        "developments",
        ["parent_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="RESTRICT",
    )
    op.execute("UPDATE core.developments SET name_normalized = lower(regexp_replace(trim(name), '\\s+', ' ', 'g'))")
    op.execute("UPDATE core.developments SET development_type = 'subdivision'")
    op.execute("UPDATE core.developments SET development_type = 'municipality' WHERE lower(trim(name)) = 'headingley'")
    op.execute("UPDATE core.developments SET development_type = 'community' WHERE lower(trim(name)) = 'grande pointe'")

    op.execute(
        """
        INSERT INTO core.developments (
            id, org_id, parent_id, developer_contact_id, name, name_normalized,
            development_type, municipality, province, metadata
        )
        SELECT gen_random_uuid(), source.org_id, NULL, NULL, values.name,
               lower(values.name), 'municipality', values.name, 'Manitoba', '{}'::jsonb
        FROM (
            SELECT DISTINCT org_id FROM core.developments
        ) AS source
        CROSS JOIN (VALUES
            ('RM of Ritchot'),
            ('RM of West St. Paul'),
            ('RM of Springfield')
        ) AS values(name)
        WHERE NOT EXISTS (
            SELECT 1 FROM core.developments existing
            WHERE existing.org_id = source.org_id
              AND lower(trim(existing.name)) = lower(values.name)
        )
        """
    )
    op.execute(
        """
        UPDATE core.developments child
        SET parent_id = parent.id,
            municipality = 'RM of Ritchot',
            development_type = 'community'
        FROM core.developments parent
        WHERE child.org_id = parent.org_id
          AND lower(trim(child.name)) = 'grande pointe'
          AND lower(trim(parent.name)) = 'rm of ritchot'
        """
    )
    op.execute(
        """
        UPDATE core.developments child
        SET parent_id = parent.id,
            municipality = 'RM of West St. Paul',
            development_type = 'subdivision'
        FROM core.developments parent
        WHERE child.org_id = parent.org_id
          AND lower(trim(child.name)) = 'parkview pointe'
          AND lower(trim(parent.name)) = 'rm of west st. paul'
        """
    )
    op.execute(
        """
        UPDATE core.developments
        SET municipality = 'RM of Headingley', development_type = 'municipality'
        WHERE lower(trim(name)) = 'headingley'
        """
    )
    op.execute(
        """
        INSERT INTO core.developments (
            id, org_id, parent_id, developer_contact_id, name, name_normalized,
            development_type, municipality, province, metadata
        )
        SELECT gen_random_uuid(), parent.org_id, parent.id, NULL, 'Forest Grove Estates',
               'forest grove estates', 'subdivision', 'RM of Headingley', 'Manitoba',
               '{"phases": ["Phase 2"]}'::jsonb
        FROM core.developments parent
        WHERE lower(trim(parent.name)) = 'headingley'
          AND NOT EXISTS (
              SELECT 1 FROM core.developments existing
              WHERE existing.org_id = parent.org_id
                AND existing.parent_id = parent.id
                AND lower(trim(existing.name)) = 'forest grove estates'
          )
        """
    )
    op.execute(
        """
        INSERT INTO core.developments (
            id, org_id, parent_id, developer_contact_id, name, name_normalized,
            development_type, municipality, province, metadata
        )
        SELECT gen_random_uuid(), parent.org_id, parent.id, NULL, child.name,
               lower(child.name), 'community', 'RM of Springfield', 'Manitoba', '{}'::jsonb
        FROM core.developments parent
        CROSS JOIN (VALUES ('Oakbank'), ('Dugald')) AS child(name)
        WHERE lower(trim(parent.name)) = 'rm of springfield'
          AND NOT EXISTS (
              SELECT 1 FROM core.developments existing
              WHERE existing.org_id = parent.org_id
                AND existing.parent_id = parent.id
                AND lower(trim(existing.name)) = lower(child.name)
          )
        """
    )
    op.execute(
        """
        UPDATE core.lots lot
        SET development_id = forest_grove.id
        FROM core.developments current_development
        JOIN core.developments forest_grove
          ON forest_grove.org_id = current_development.org_id
         AND forest_grove.parent_id = current_development.id
         AND forest_grove.name_normalized = 'forest grove estates'
        WHERE lot.development_id = current_development.id
          AND current_development.name_normalized = 'headingley'
          AND lower(coalesce(lot.civic_address, '')) LIKE '48 ash cove%'
        """
    )

    op.alter_column("developments", "name_normalized", nullable=False, schema="core")
    op.alter_column("developments", "development_type", nullable=False, schema="core")
    op.create_check_constraint(
        "ck_core_developments_type",
        "developments",
        "development_type IN ('municipality', 'community', 'subdivision')",
        schema="core",
    )
    op.create_index("idx_core_developments_parent_id", "developments", ["parent_id"], schema="core")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_core_developments_sibling_name
        ON core.developments (org_id, parent_id, name_normalized) NULLS NOT DISTINCT
        """
    )

    op.add_column(
        "lots",
        sa.Column("legal_description_verification_status", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column("lots", sa.Column("legal_description_source", sa.Text(), nullable=True), schema="core")
    op.add_column(
        "lots",
        sa.Column("legal_description_verified_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.create_check_constraint(
        "ck_core_lots_legal_description_verification_status",
        "lots",
        "legal_description_verification_status IN ('title_confirmed', 'permit_agreement_confirmed')",
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_core_lots_legal_description_verification_status",
        "lots",
        schema="core",
        type_="check",
    )
    op.drop_column("lots", "legal_description_verified_at", schema="core")
    op.drop_column("lots", "legal_description_source", schema="core")
    op.drop_column("lots", "legal_description_verification_status", schema="core")

    op.execute(
        """
        UPDATE core.lots lot
        SET development_id = headingley.id
        FROM core.developments forest_grove
        JOIN core.developments headingley ON headingley.id = forest_grove.parent_id
        WHERE lot.development_id = forest_grove.id
          AND forest_grove.name_normalized = 'forest grove estates'
          AND headingley.name_normalized = 'headingley'
        """
    )
    op.execute(
        """
        UPDATE core.developments
        SET parent_id = NULL,
            municipality = CASE
                WHEN name_normalized = 'grande pointe' THEN 'Grande Pointe'
                WHEN name_normalized = 'headingley' THEN 'Headingley'
                ELSE municipality
            END
        """
    )
    op.execute(
        """
        DELETE FROM core.developments
        WHERE name_normalized IN (
            'forest grove estates', 'oakbank', 'dugald',
            'rm of ritchot', 'rm of west st. paul', 'rm of springfield'
        )
        """
    )
    op.execute("DROP INDEX core.uq_core_developments_sibling_name")
    op.drop_index("idx_core_developments_parent_id", table_name="developments", schema="core")
    op.drop_constraint("ck_core_developments_type", "developments", schema="core", type_="check")
    op.drop_constraint("fk_core_developments_parent_id", "developments", schema="core", type_="foreignkey")
    op.drop_column("developments", "development_type", schema="core")
    op.drop_column("developments", "name_normalized", schema="core")
    op.drop_column("developments", "parent_id", schema="core")
