"""Add rental property coordinates.

Revision ID: 20260810_0031
Revises: 20260809_0030
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
revision:str="20260810_0031"; down_revision:str|None="20260809_0030"; branch_labels:str|Sequence[str]|None=None; depends_on:str|Sequence[str]|None=None
def upgrade()->None:
    op.add_column("rental_properties",sa.Column("latitude",sa.Numeric(9,6)))
    op.add_column("rental_properties",sa.Column("longitude",sa.Numeric(9,6)))
def downgrade()->None:
    op.drop_column("rental_properties","longitude");op.drop_column("rental_properties","latitude")
