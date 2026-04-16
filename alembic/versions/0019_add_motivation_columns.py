"""Add preceding_context and motivation_summary to job_telemetry_spans.

preceding_context: JSON array of the 5 most recent transcript entries
before a mutative tool call — captures the conversational "why".

motivation_summary: LLM-generated motivation summary explaining why
the change was made, produced asynchronously by the motivation service.

Revision ID: 0019
Revises: 0018
"""

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.add_column("job_telemetry_spans", __import__("sqlalchemy").Column("preceding_context", __import__("sqlalchemy").Text, nullable=True))
    op.add_column("job_telemetry_spans", __import__("sqlalchemy").Column("motivation_summary", __import__("sqlalchemy").Text, nullable=True))


def downgrade() -> None:
    op.drop_column("job_telemetry_spans", "motivation_summary")
    op.drop_column("job_telemetry_spans", "preceding_context")
