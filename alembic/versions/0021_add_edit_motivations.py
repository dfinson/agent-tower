"""Add edit_motivations column to job_telemetry_spans.

Stores a JSON array of per-edit motivation summaries, each with an
edit_key fingerprint for matching to diff hunks at render time.
Complements the existing file-level motivation_summary.

Revision ID: 0021
Revises: 0020
"""

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy import Column, Text


def upgrade() -> None:
    op.add_column("job_telemetry_spans", Column("edit_motivations", Text, nullable=True))


def downgrade() -> None:
    op.drop_column("job_telemetry_spans", "edit_motivations")
