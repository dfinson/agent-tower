"""Add mcp_tool column to trust_grants.

Revision ID: 0042
Revises: 0041
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trust_grants", sa.Column("mcp_tool", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("trust_grants", "mcp_tool")
