"""Add task_links table (Story 4.2 — Ingest a task graph into a Project, AD-9).

Revision ID: 0062
Revises: 0060
"""

import sqlalchemy as sa

from alembic import op

revision = "0062"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("repo_path", sa.String(), nullable=False),
        sa.Column("story_node_id", sa.String(), nullable=True),
        sa.Column("depends_on", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("tracker_ticket_ref", sa.String(), nullable=True),
        sa.Column("prompt_override", sa.Text(), nullable=True),
        sa.Column("epic_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_task_links_project_id",
        "task_links",
        ["project_id"],
    )
    op.create_index(
        "ix_task_links_project_repo_node",
        "task_links",
        ["project_id", "repo_path", "story_node_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_task_links_project_repo_node", table_name="task_links")
    op.drop_index("ix_task_links_project_id", table_name="task_links")
    op.drop_table("task_links")
