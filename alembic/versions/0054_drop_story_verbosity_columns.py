"""Drop story_text_summary and story_text_detailed columns from jobs.

Single verbosity level replaces the triple-column design.

Revision ID: 0054
Revises: 0053
"""

from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("jobs", "story_text_summary")
    op.drop_column("jobs", "story_text_detailed")


def downgrade() -> None:
    op.add_column("jobs", sa.Column("story_text_summary", sa.Text, nullable=True))
    op.add_column("jobs", sa.Column("story_text_detailed", sa.Text, nullable=True))
