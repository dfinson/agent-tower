"""Add story_text column to jobs table.

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("story_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "story_text")
