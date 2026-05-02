"""Add write sub-node columns to trail_nodes.

Per §13.1 of the unified trail service design: write sub-nodes are children
of modify nodes, one per file_write span, carrying per-file granularity
data that downstream consumers (StoryService, MotivationService,
SummarizationService) need.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trail_nodes") as batch_op:
        # Per-write identity
        batch_op.add_column(sa.Column("tool_name", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("snippet", sa.Text, nullable=True))
        # Retry / error context
        batch_op.add_column(sa.Column("is_retry", sa.Boolean, nullable=True))
        batch_op.add_column(sa.Column("error_kind", sa.String(50), nullable=True))
        # Motivation data (migrated from telemetry spans)
        batch_op.add_column(sa.Column("write_summary", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("edit_motivations", sa.Text, nullable=True))
        # Per-tool metadata (§13.3)
        batch_op.add_column(sa.Column("tool_display", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("tool_intent", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("tool_success", sa.Boolean, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trail_nodes") as batch_op:
        batch_op.drop_column("tool_success")
        batch_op.drop_column("tool_intent")
        batch_op.drop_column("tool_display")
        batch_op.drop_column("edit_motivations")
        batch_op.drop_column("write_summary")
        batch_op.drop_column("error_kind")
        batch_op.drop_column("is_retry")
        batch_op.drop_column("snippet")
        batch_op.drop_column("tool_name")
