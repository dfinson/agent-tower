"""Add preceding_context column to steps table.

Stores a JSON array of the recent transcript entries (agent reasoning,
tool calls, operator messages) that were in-flight when the step closed.
Used by the title generator to produce outcome-focused summaries that
explain *why* the step happened, not just *what* it did.

Revision ID: 0020
Revises: 0019
"""

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy import Column, Text


def upgrade() -> None:
    op.add_column("steps", Column("preceding_context", Text, nullable=True))


def downgrade() -> None:
    op.drop_column("steps", "preceding_context")
