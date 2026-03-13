"""add pr_url to jobs

Revision ID: a1b2c3d4e5f6
Revises: eef13d8f8935
Create Date: 2026-03-12 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "eef13d8f8935"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add pr_url column to jobs table."""
    op.add_column("jobs", sa.Column("pr_url", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove pr_url column from jobs table."""
    op.drop_column("jobs", "pr_url")
