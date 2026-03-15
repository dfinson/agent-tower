"""add_merge_status_to_jobs

Revision ID: 8b0b1c2ee2d1
Revises: eef13d8f8935
Create Date: 2026-03-15 16:14:33.383069

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b0b1c2ee2d1"
down_revision: str | Sequence[str] | None = "eef13d8f8935"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("jobs", sa.Column("merge_status", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("jobs", "merge_status")
