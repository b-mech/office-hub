"""Merge maintenance and financing migration branches.

Revision ID: 20261015_0049
Revises: 20261001_0047, 20261015_0048
"""
from __future__ import annotations

from collections.abc import Sequence


revision: str = "20261015_0049"
down_revision: tuple[str, str] = ("20261001_0047", "20261015_0048")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
