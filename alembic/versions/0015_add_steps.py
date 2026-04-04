"""Add steps table and step_id to artifacts.

Revision ID: 0015
Revises: 0014_rename_permission_modes
Create Date: 2026-04-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014_rename_permission_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("step_number", sa.Integer, nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("intent", sa.Text, nullable=False, server_default=""),
        sa.Column("title", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("tool_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agent_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("start_sha", sa.String(40), nullable=True),
        sa.Column("end_sha", sa.String(40), nullable=True),
        sa.Column("files_read", sa.Text, nullable=True),
        sa.Column("files_written", sa.Text, nullable=True),
    )
    op.create_index("ix_steps_job_number", "steps", ["job_id", "step_number"])
    op.add_column("artifacts", sa.Column("step_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "step_id")
    op.drop_index("ix_steps_job_number", table_name="steps")
    op.drop_table("steps")
