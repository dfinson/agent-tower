"""Add purpose and purpose_source columns to trail_nodes.

Revision ID: 0037
Revises: 0036
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trail_nodes", sa.Column("purpose", sa.String(20), nullable=True))
    op.add_column("trail_nodes", sa.Column("purpose_source", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("trail_nodes", "purpose_source")
    op.drop_column("trail_nodes", "purpose")
