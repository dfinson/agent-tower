"""Add story_text_summary and story_text_detailed columns to jobs.

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("story_text_summary", sa.Text, nullable=True))
    op.add_column("jobs", sa.Column("story_text_detailed", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "story_text_detailed")
    op.drop_column("jobs", "story_text_summary")
