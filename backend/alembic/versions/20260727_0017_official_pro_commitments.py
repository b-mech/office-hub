"""Record the official ProAuto commitment schedule.

Revision ID: 20260727_0017
Revises: 20260724_0016
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0017"
down_revision: str | None = "20260724_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lender_facilities", sa.Column("requested_draw_amount", sa.Numeric(15, 2)), schema="core")
    op.add_column("lender_facilities", sa.Column("requested_draw_as_of", sa.Date()), schema="core")
    op.add_column("lender_facilities", sa.Column("commitment_source", sa.Text()), schema="core")
    op.add_column(
        "lender_facilities",
        sa.Column("commitment_confirmed_at", sa.DateTime(timezone=True)),
        schema="core",
    )

    # Undo the earlier 24/28 Gleneagles assumption. The amortization ledger and
    # its transactions belong to 24 Gleneagles; 28 Gleneagles is a separate
    # commitment that has not appeared on the supplied monthly report.
    op.execute(
        """
        UPDATE core.lender_facilities AS facility
        SET property_id = property.id,
            facility_key = 'PRO-24-GLENEAGLES',
            property_name = '24 Gleneagles Street, Niverville, MB',
            canonical_address_key = property.canonical_address_key,
            total_facility = 300000.00,
            rate = 11.0000,
            annual_rate = 0.11000,
            requested_draw_amount = 0.00,
            draw_eligible_override = NULL,
            commitment_source = 'Official ProAuto commitment schedule confirmed 2026-07-27',
            commitment_confirmed_at = now(),
            status = 'active',
            updated_at = now()
        FROM core.properties AS property
        WHERE facility.facility_key = 'PRO-28-GLENEAGLES'
          AND property.canonical_address_key = '24 GLENEAGLES ST NIVERVILLE'
        """
    )
    op.execute(
        """
        INSERT INTO core.lender_facilities (
            property_id, lender_type, lender, lender_name, facility_key,
            property_name, canonical_address_key, borrower, annual_rate, rate,
            total_facility, already_drawn, requested_draw_amount,
            draw_eligible_override, commitment_source, commitment_confirmed_at,
            status, notes
        )
        SELECT
            property.id, 'PRO', 'PRO', 'ProAuto', 'PRO-28-GLENEAGLES',
            '28 Gleneagles Street, Niverville, MB', property.canonical_address_key,
            'Connection Homes', 0.11500, 11.5000, 428000.00, 0.00, 428000.00,
            235000.00,
            'Official ProAuto commitment schedule confirmed 2026-07-27', now(),
            'active',
            'Separate from the 24 Gleneagles amortization facility. The requested-draw schedule date was not supplied.'
        FROM core.properties AS property
        WHERE property.canonical_address_key = '28 GLENEAGLES ST NIVERVILLE'
        ON CONFLICT (facility_key) DO NOTHING
        """
    )

    op.execute(
        """
        WITH official(facility_key, commitment, rate_pct, requested_draw) AS (
            VALUES
                ('PRO-2-CARDINAL', 345000.00, 11.00, 150000.00),
                ('PRO-127-CHAMPAGNE', 330000.00, 11.00, 145000.00),
                ('PRO-126-RAMONA-GALLOS', 420000.00, 11.00, 55000.00),
                ('PRO-122-RAMONA-GALLOS', 435000.00, 11.00, 70000.00),
                ('PRO-150-ROSYBLOOM', 415000.00, 11.00, 65000.00),
                ('PRO-64-WOODLAND', 485000.00, 11.00, 120000.00),
                ('PRO-149-RAMONA-GALLOS', 377500.00, 11.00, 75000.00),
                ('PRO-153-RAMONA-GALLOS', 377500.00, 11.00, 75000.00),
                ('PRO-WATERSIDE-PARKVIEW', 405300.00, 11.50, 0.00),
                ('PRO-TEMPLETON-DEPOSIT', 473750.00, 11.50, 0.00)
        )
        UPDATE core.lender_facilities AS facility
        SET total_facility = official.commitment,
            rate = official.rate_pct,
            annual_rate = official.rate_pct / 100.0,
            requested_draw_amount = official.requested_draw,
            requested_draw_as_of = NULL,
            commitment_source = 'Official ProAuto commitment schedule confirmed 2026-07-27',
            commitment_confirmed_at = now(),
            updated_at = now()
        FROM official
        WHERE facility.facility_key = official.facility_key
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities
        SET facility_key = 'PRO-10-DEER-MEADOW',
            property_name = '10 Deer Meadow Run',
            canonical_address_key = '10 DEER MEADOW RUN',
            lender = 'PRO',
            lender_name = 'ProAuto',
            total_facility = 309000.00,
            rate = 11.5000,
            annual_rate = 0.11500,
            requested_draw_amount = 309000.00,
            commitment_source = 'Official ProAuto commitment schedule confirmed 2026-07-27',
            commitment_confirmed_at = now(),
            updated_at = now()
        WHERE property_id = (
            SELECT id FROM core.properties
            WHERE canonical_address_key = '10 DEER MEADOW RUN'
        )
          AND COALESCE(lender, lender_type) = 'PRO'
        """
    )
    op.execute(
        """
        INSERT INTO core.properties (address, address_normalized, canonical_address_key)
        VALUES
            ('149 Ramona Gallos Way', '149 RAMONA GALLOS WAY', '149 RAMONA GALLOS WAY WINNIPEG'),
            ('153 Ramona Gallos Way', '153 RAMONA GALLOS WAY', '153 RAMONA GALLOS WAY WINNIPEG')
        ON CONFLICT (address_normalized) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities AS facility
        SET property_id = property.id,
            status = 'active',
            updated_at = now()
        FROM core.properties AS property
        WHERE facility.facility_key IN (
            'PRO-149-RAMONA-GALLOS',
            'PRO-153-RAMONA-GALLOS'
        )
          AND property.canonical_address_key = facility.canonical_address_key
        """
    )

    # The monthly report groups Oak Meadows. Preserve that ledger as one
    # facility while recording the official per-property breakdown in notes.
    op.execute(
        """
        UPDATE core.lender_facilities
        SET total_facility = 630000.00,
            rate = 11.0000,
            annual_rate = 0.11000,
            requested_draw_amount = 410000.00,
            commitment_source = 'Official ProAuto commitment schedule confirmed 2026-07-27',
            commitment_confirmed_at = now(),
            notes = 'Official breakdown: 26 Oak Meadows Drive commitment $315,000 / requested $205,000; 28 Oak Meadows Drive commitment $315,000 / requested $205,000. ProAuto amortization report is combined.',
            updated_at = now()
        WHERE facility_key = 'PRO-26-28-OAK-MEADOW'
        """
    )

    # Create official commitments that do not yet have amortization pages.
    op.execute(
        """
        WITH official(
            facility_key, canonical_key, property_name, commitment, rate_pct,
            requested_draw
        ) AS (
            VALUES
                ('PRO-37-39-ELLA', '37-39 ELLA DR', '37/39 Ella Drive', 680000.00, 11.50, 680000.00),
                ('PRO-45-47-ELLA', '45-47 ELLA DR', '45/47 Ella Drive', 680000.00, 11.50, 680000.00),
                ('PRO-8-100-GRANDE-POINTE', '8-100 GRANDE POINTE MEADOWS', '8-100 Grande Pointe Meadows', 385000.00, 11.50, 385000.00),
                ('PRO-57-100-GRANDE-POINTE', '57-100 GRANDE POINTE MEADOWS BLVD', '57-100 Grande Pointe Meadows Blvd', 392000.00, 11.50, 392000.00),
                ('PRO-76-100-GRANDE-POINTE', '76-100 GRANDE POINTE MEADOWS BLVD', '76-100 Grande Pointe Meadows Blvd', 390000.00, 11.50, 390000.00),
                ('PRO-141-145-LAURENT', '141-145 LAURENT DR', '141/145 Laurent Drive', 695000.00, 11.50, 695000.00),
                ('PRO-149-153-LAURENT', '149-153 LAURENT DR', '149/153 Laurent Drive', 695000.00, 11.50, 695000.00)
        )
        INSERT INTO core.lender_facilities (
            property_id, lender_type, lender, lender_name, facility_key,
            property_name, canonical_address_key, borrower, annual_rate, rate,
            total_facility, already_drawn, requested_draw_amount,
            commitment_source, commitment_confirmed_at, status, notes
        )
        SELECT
            property.id, 'PRO', 'PRO', 'ProAuto', official.facility_key,
            official.property_name, property.canonical_address_key,
            'Connection Homes', official.rate_pct / 100.0, official.rate_pct,
            official.commitment, 0.00, official.requested_draw,
            'Official ProAuto commitment schedule confirmed 2026-07-27', now(),
            'active', 'Requested-draw schedule date was not supplied.'
        FROM official
        JOIN core.properties AS property
          ON property.canonical_address_key = official.canonical_key
        ON CONFLICT (facility_key) DO UPDATE
        SET total_facility = EXCLUDED.total_facility,
            requested_draw_amount = EXCLUDED.requested_draw_amount,
            rate = EXCLUDED.rate,
            annual_rate = EXCLUDED.annual_rate,
            commitment_source = EXCLUDED.commitment_source,
            commitment_confirmed_at = EXCLUDED.commitment_confirmed_at,
            updated_at = now()
        """
    )

    # Development additions and 114 Froese do not yet exist as master
    # financing properties. They are created as financing display anchors.
    op.execute(
        """
        INSERT INTO core.properties (address, address_normalized, canonical_address_key)
        VALUES
            ('Parkview Lots Additional April 2026', 'PARKVIEW LOTS ADDITIONAL APRIL 2026', 'DEV:PARKVIEW LOTS ADDITIONAL APRIL 2026'),
            ('Parkview Lots Additional TBD Start Date', 'PARKVIEW LOTS ADDITIONAL TBD START DATE', 'DEV:PARKVIEW LOTS ADDITIONAL TBD START DATE'),
            ('114 Froese Crescent', '114 FROESE CRESCENT', '114 FROESE CRESCENT')
        ON CONFLICT (address_normalized) DO NOTHING
        """
    )
    op.execute(
        """
        WITH official(
            facility_key, canonical_key, property_name, commitment, rate_pct,
            requested_draw
        ) AS (
            VALUES
                ('PRO-PARKVIEW-APRIL-2026', 'DEV:PARKVIEW LOTS ADDITIONAL APRIL 2026', 'Parkview Lots Additional April 2026', 419760.00, NULL, 419760.00),
                ('PRO-PARKVIEW-TBD', 'DEV:PARKVIEW LOTS ADDITIONAL TBD START DATE', 'Parkview Lots Additional TBD Start Date', 279840.00, NULL, 279840.00),
                ('PRO-114-FROESE', '114 FROESE CRESCENT', '114 Froese Crescent', 1000000.00, 11.50, 1000000.00)
        )
        INSERT INTO core.lender_facilities (
            property_id, lender_type, lender, lender_name, facility_key,
            property_name, canonical_address_key, borrower, annual_rate, rate,
            total_facility, already_drawn, requested_draw_amount,
            commitment_source, commitment_confirmed_at, status, notes
        )
        SELECT
            property.id, 'PRO', 'PRO', 'ProAuto', official.facility_key,
            official.property_name, property.canonical_address_key,
            'Connection Homes',
            CASE WHEN official.rate_pct IS NULL THEN NULL ELSE official.rate_pct / 100.0 END,
            official.rate_pct, official.commitment, 0.00,
            official.requested_draw,
            'Official ProAuto commitment schedule confirmed 2026-07-27', now(),
            'active', 'Requested-draw schedule date was not supplied.'
        FROM official
        JOIN core.properties AS property
          ON property.canonical_address_key = official.canonical_key
        ON CONFLICT (facility_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_column("lender_facilities", "commitment_confirmed_at", schema="core")
    op.drop_column("lender_facilities", "commitment_source", schema="core")
    op.drop_column("lender_facilities", "requested_draw_as_of", schema="core")
    op.drop_column("lender_facilities", "requested_draw_amount", schema="core")
