"""Add description column to jobs table.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "description")
