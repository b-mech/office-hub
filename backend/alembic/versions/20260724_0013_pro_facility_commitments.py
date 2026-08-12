"""Set confirmed PRO facility commitments and correct Gleneagles matching.

Revision ID: 20260724_0013
Revises: 20260723_0012
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260724_0013"
down_revision: str | None = "20260723_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE core.lender_facilities
        SET total_facility = CASE facility_key
                WHEN 'PRO-122-RAMONA-GALLOS' THEN 420000.00
                WHEN 'PRO-126-RAMONA-GALLOS' THEN 435000.00
                WHEN 'PRO-127-CHAMPAGNE' THEN 475000.00
                WHEN 'PRO-64-WOODLAND' THEN 485000.00
                WHEN 'PRO-24-GLENEAGLES' THEN 535000.00
                ELSE total_facility
            END,
            updated_at = now()
        WHERE facility_key IN (
            'PRO-122-RAMONA-GALLOS',
            'PRO-126-RAMONA-GALLOS',
            'PRO-127-CHAMPAGNE',
            'PRO-64-WOODLAND',
            'PRO-24-GLENEAGLES'
        )
        """
    )
    op.execute(
        """
        INSERT INTO core.facility_aliases (facility_id, alias)
        SELECT id, '24 Gleneagles St, Niverville, MB'
        FROM core.lender_facilities
        WHERE facility_key = 'PRO-24-GLENEAGLES'
        ON CONFLICT (alias) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities AS facility
        SET property_id = property.id,
            facility_key = 'PRO-28-GLENEAGLES',
            property_name = '28 Gleneagles Street, Niverville, MB',
            canonical_address_key = property.canonical_address_key,
            status = 'active',
            updated_at = now()
        FROM core.properties AS property
        WHERE facility.facility_key = 'PRO-24-GLENEAGLES'
          AND property.canonical_address_key = '28 GLENEAGLES ST NIVERVILLE'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE core.lender_facilities
        SET property_id = NULL,
            facility_key = 'PRO-24-GLENEAGLES',
            property_name = '24 Gleneagles St, Niverville, MB',
            canonical_address_key = '24 GLENEAGLES ST NIVERVILLE',
            status = 'needs_link',
            updated_at = now()
        WHERE facility_key = 'PRO-28-GLENEAGLES'
        """
    )
    op.execute(
        """
        UPDATE core.lender_facilities
        SET total_facility = NULL,
            updated_at = now()
        WHERE facility_key IN (
            'PRO-122-RAMONA-GALLOS',
            'PRO-126-RAMONA-GALLOS',
            'PRO-127-CHAMPAGNE',
            'PRO-64-WOODLAND',
            'PRO-24-GLENEAGLES'
        )
        """
    )
    op.execute(
        """
        DELETE FROM core.facility_aliases
        WHERE alias = '24 Gleneagles St, Niverville, MB'
        """
    )
