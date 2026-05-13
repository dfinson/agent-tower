"""Rename preset 'strict' to 'locked'.

Revision ID: 0041
Revises: 0040
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Rename preset in jobs table
    conn.execute(
        sa.text("UPDATE jobs SET preset = 'locked' WHERE preset = 'strict'")
    )

    # Rename preset in policy_config table (if any rows exist)
    conn.execute(
        sa.text("UPDATE policy_config SET preset = 'locked' WHERE preset = 'strict'")
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("UPDATE jobs SET preset = 'strict' WHERE preset = 'locked'")
    )
    conn.execute(
        sa.text("UPDATE policy_config SET preset = 'strict' WHERE preset = 'locked'")
    )
