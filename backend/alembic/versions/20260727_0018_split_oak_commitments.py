"""Split official Oak Meadows commitments while retaining the combined report.

Revision ID: 20260727_0018
Revises: 20260727_0017
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260727_0018"
down_revision: str | None = "20260727_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO core.properties (address, address_normalized, canonical_address_key)
        VALUES
            ('26 Oak Meadows Drive', '26 OAK MEADOWS DRIVE', '26 OAK MEADOW DR OAKBANK'),
            ('28 Oak Meadows Drive', '28 OAK MEADOWS DRIVE', '28 OAK MEADOW DR OAKBANK')
        ON CONFLICT (address_normalized) DO NOTHING
        """
    )
    op.execute(
        """
        WITH official(facility_key, canonical_key, property_name) AS (
            VALUES
                ('PRO-26-OAK-MEADOW', '26 OAK MEADOW DR OAKBANK', '26 Oak Meadows Drive'),
                ('PRO-28-OAK-MEADOW', '28 OAK MEADOW DR OAKBANK', '28 Oak Meadows Drive')
        )
        INSERT INTO core.lender_facilities (
            property_id, lender_type, lender, lender_name, facility_key,
            property_name, canonical_address_key, borrower, annual_rate, rate,
            original_advance_date, original_advance_amount, total_facility,
            already_drawn, requested_draw_amount, commitment_source,
            commitment_confirmed_at, status, notes
        )
        SELECT
            property.id, 'PRO', 'PRO', 'ProAuto', official.facility_key,
            official.property_name, property.canonical_address_key,
            'Connection Homes', 0.11000, 11.0000,
            DATE '2024-10-31', 110000.00, 315000.00,
            110000.00, 205000.00,
            'Official ProAuto commitment schedule confirmed 2026-07-27',
            now(), 'active',
            'Official per-property commitment. The supplied ProAuto amortization report combines 26 and 28 Oak Meadows into one $220,000 original advance.'
        FROM official
        JOIN core.properties AS property
          ON property.canonical_address_key = official.canonical_key
        ON CONFLICT (facility_key) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities
        SET commitment_source = NULL,
            status = 'statement_only',
            notes = 'Combined ProAuto statement ledger retained for reconciliation. Official commitments are recorded separately under 26 and 28 Oak Meadows.',
            updated_at = now()
        WHERE facility_key = 'PRO-26-28-OAK-MEADOW'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM core.lender_facilities
        WHERE facility_key IN ('PRO-26-OAK-MEADOW', 'PRO-28-OAK-MEADOW')
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities
        SET commitment_source = 'Official ProAuto commitment schedule confirmed 2026-07-27',
            status = 'active',
            updated_at = now()
        WHERE facility_key = 'PRO-26-28-OAK-MEADOW'
        """
    )
