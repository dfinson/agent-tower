"""Add event_metadata column to events table.

Post event-core-collapse, events are ``traceforge.SessionEvent`` whose
enrichment (turn_id, tool_display, motivation, duration_ms, visibility, …)
lives on ``EventMetadata``. Persist it so DB-replay consumers (REST transcript,
snapshot, search, handoff) reconstruct the full event rather than a lossy
payload-only version.

Revision ID: 0055
Revises: 0054
"""

import sqlalchemy as sa

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("event_metadata", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("events", "event_metadata")
