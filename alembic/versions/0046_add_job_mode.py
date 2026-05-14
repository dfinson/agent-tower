"""Add mode column to jobs table for plan mode support.

Revision ID: 0046
Revises: 0045
Create Date: 2026-05-14
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("mode", sa.String(), nullable=False, server_default="standard"))


def downgrade() -> None:
    op.drop_column("jobs", "mode")
