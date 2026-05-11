"""Add tail_offset to jobs for events.jsonl resume-after-restart.

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("tail_offset", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("jobs", "tail_offset")
