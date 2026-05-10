"""Add source and external_session_id to jobs.

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("source", sa.String(), nullable=False, server_default="managed"))
    op.add_column("jobs", sa.Column("external_session_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "external_session_id")
    op.drop_column("jobs", "source")
