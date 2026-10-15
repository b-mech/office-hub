"""Correct PRO statement balance statuses derived from non-balance warnings.

Revision ID: 20261015_0048
Revises: 20260917_0045
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20261015_0048"
down_revision: str | None = "20260917_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH corrected AS (
            UPDATE documents.facility_statement_snapshots
            SET reconciliation_status = CASE
                WHEN delta = 0.00 THEN 'matched'
                ELSE 'parse_error'
            END
            WHERE reconciliation_status = 'balance_mismatch'
              AND (
                  (
                      delta = 0.00
                      AND jsonb_array_length(COALESCE(new_draws_detected, '[]'::jsonb)) = 0
                  )
                  OR (
                      delta <> 0.00
                      AND EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements_text(
                              COALESCE(parse_payload->'validation_errors', '[]'::jsonb)
                          ) AS error_text
                          WHERE error_text LIKE 'Could not parse%'
                      )
                  )
              )
            RETURNING statement_id
        ),
        affected AS (
            SELECT DISTINCT statement_id
            FROM corrected
        )
        UPDATE documents.lender_statements statement
        SET status = CASE
            WHEN EXISTS (
                SELECT 1
                FROM documents.facility_statement_snapshots snapshot
                WHERE snapshot.statement_id = statement.id
                  AND snapshot.reconciliation_status NOT IN ('matched', 'acknowledged')
            ) OR EXISTS (
                SELECT 1
                FROM documents.lender_statement_discrepancies discrepancy
                WHERE discrepancy.statement_id = statement.id
                  AND discrepancy.status = 'open'
            ) THEN 'needs_review'
            WHEN EXISTS (
                SELECT 1
                FROM documents.lender_statement_discrepancies discrepancy
                WHERE discrepancy.statement_id = statement.id
            ) THEN 'reviewed'
            ELSE 'reconciled'
        END
        FROM affected
        WHERE statement.id = affected.statement_id
        """
    )


def downgrade() -> None:
    # The previous classifications cannot be reconstructed reliably because a
    # zero-cent mismatch was indistinguishable from a valid manual status.
    pass
