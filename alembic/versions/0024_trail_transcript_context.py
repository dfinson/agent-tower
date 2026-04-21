"""Add transcript context and plan/activity columns to trail_nodes.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Transcript context (pass-through from step_completed)
    op.add_column("trail_nodes", sa.Column("preceding_context", sa.Text, nullable=True))
    op.add_column("trail_nodes", sa.Column("agent_message", sa.Text, nullable=True))
    op.add_column("trail_nodes", sa.Column("tool_names", sa.Text, nullable=True))
    op.add_column("trail_nodes", sa.Column("tool_count", sa.Integer, nullable=True))
    op.add_column("trail_nodes", sa.Column("duration_ms", sa.Integer, nullable=True))
    # Plan/activity (populated by enrichment or native plan)
    op.add_column("trail_nodes", sa.Column("title", sa.Text, nullable=True))
    op.add_column("trail_nodes", sa.Column("plan_item_id", sa.String(36), nullable=True))
    op.add_column("trail_nodes", sa.Column("plan_item_label", sa.Text, nullable=True))
    op.add_column("trail_nodes", sa.Column("plan_item_status", sa.String(10), nullable=True))
    op.add_column("trail_nodes", sa.Column("activity_id", sa.String(36), nullable=True))
    op.add_column("trail_nodes", sa.Column("activity_label", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("trail_nodes", "activity_label")
    op.drop_column("trail_nodes", "activity_id")
    op.drop_column("trail_nodes", "plan_item_status")
    op.drop_column("trail_nodes", "plan_item_label")
    op.drop_column("trail_nodes", "plan_item_id")
    op.drop_column("trail_nodes", "title")
    op.drop_column("trail_nodes", "duration_ms")
    op.drop_column("trail_nodes", "tool_count")
    op.drop_column("trail_nodes", "tool_names")
    op.drop_column("trail_nodes", "agent_message")
    op.drop_column("trail_nodes", "preceding_context")
