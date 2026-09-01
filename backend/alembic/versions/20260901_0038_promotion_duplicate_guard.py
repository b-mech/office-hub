"""Prevent duplicate agreement promotion by source document.

Revision ID: 20260901_0038
Revises: 20260824_0037
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0038"
down_revision: str | None = "20260824_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove the known incomplete duplicate promotion. The checks deliberately
    # fail the migration if production no longer matches the audited state.
    connection = op.get_bind()
    obsolete_agreement_id = "03e6bc56-85e5-4084-83d5-2e1b4b1e2f15"
    surviving_agreement_id = "62006c7d-0cb0-40aa-9741-147ea16d02c1"
    document_id = "d4628f16-9011-4c99-868c-75e745d3223a"

    duplicate = connection.execute(
        sa.text(
            """
            SELECT
                (SELECT count(*) FROM land.agreements
                 WHERE id IN (CAST(:obsolete AS uuid), CAST(:surviving AS uuid))
                   AND document_id = CAST(:document AS uuid)) AS agreement_count,
                (SELECT count(*) FROM land.deposit_schedule ds
                 JOIN land.lot_terms lt ON lt.id = ds.lot_terms_id
                 WHERE lt.agreement_id = CAST(:obsolete AS uuid)
                   AND (ds.paid_at IS NOT NULL OR ds.paid_amount IS NOT NULL)) AS paid_deposit_count,
                (SELECT count(*) FROM land.lot_terms old_lt
                 JOIN land.lot_terms new_lt ON new_lt.lot_id = old_lt.lot_id
                 WHERE old_lt.agreement_id = CAST(:obsolete AS uuid)
                   AND new_lt.agreement_id = CAST(:surviving AS uuid)
                   AND new_lt.purchase_price = 184900.00
                   AND (SELECT array_agg(ds.amount ORDER BY ds.deposit_number)
                        FROM land.deposit_schedule ds
                        WHERE ds.lot_terms_id = new_lt.id) =
                       ARRAY[27735.00, 18490.00]::numeric[]) AS valid_surviving_term_count
            """
        ),
        {
            "obsolete": obsolete_agreement_id,
            "surviving": surviving_agreement_id,
            "document": document_id,
        },
    ).mappings().one()
    if (
        duplicate["agreement_count"] != 2
        or duplicate["paid_deposit_count"] != 0
        or duplicate["valid_surviving_term_count"] != 1
    ):
        raise RuntimeError(
            "Parkview duplicate cleanup preconditions failed; no cleanup was performed"
        )

    params = {"obsolete": obsolete_agreement_id}
    connection.execute(
        sa.text(
            """
            DELETE FROM core.reminders
            WHERE (entity_table = 'land.deposit_schedule' AND entity_id IN (
                SELECT ds.id FROM land.deposit_schedule ds
                JOIN land.lot_terms lt ON lt.id = ds.lot_terms_id
                WHERE lt.agreement_id = CAST(:obsolete AS uuid)
            )) OR (entity_table = 'land.lot_terms' AND entity_id IN (
                SELECT id FROM land.lot_terms
                WHERE agreement_id = CAST(:obsolete AS uuid)
            ))
            """
        ),
        params,
    )
    connection.execute(
        sa.text(
            """DELETE FROM land.deposit_schedule WHERE lot_terms_id IN
            (SELECT id FROM land.lot_terms WHERE agreement_id = CAST(:obsolete AS uuid))"""
        ),
        params,
    )
    connection.execute(
        sa.text("DELETE FROM land.lot_terms WHERE agreement_id = CAST(:obsolete AS uuid)"),
        params,
    )
    connection.execute(
        sa.text("DELETE FROM land.security_deposit WHERE agreement_id = CAST(:obsolete AS uuid)"),
        params,
    )
    connection.execute(
        sa.text(
            """DELETE FROM core.audit_log
            WHERE schema_name = 'land' AND table_name = 'agreements'
              AND record_id = CAST(:obsolete AS uuid)"""
        ),
        params,
    )
    connection.execute(
        sa.text("DELETE FROM land.agreements WHERE id = CAST(:obsolete AS uuid)"),
        params,
    )

    op.create_unique_constraint(
        "uq_land_agreements_document_id",
        "agreements",
        ["document_id"],
        schema="land",
    )
    op.create_unique_constraint(
        "uq_sales_agreements_document_id",
        "agreements",
        ["document_id"],
        schema="sales",
    )


def downgrade() -> None:
    # The duplicate cleanup is intentionally irreversible; downgrade only
    # removes the uniqueness backstops.
    op.drop_constraint(
        "uq_sales_agreements_document_id",
        "agreements",
        schema="sales",
        type_="unique",
    )
    op.drop_constraint(
        "uq_land_agreements_document_id",
        "agreements",
        schema="land",
        type_="unique",
    )
