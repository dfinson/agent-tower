"""Add explicit TaskLink lifecycle and tracker ownership.

Revision ID: 0066
Revises: 0065
"""

import sqlalchemy as sa

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_links",
        sa.Column("state", sa.String(), nullable=False, server_default="waiting"),
    )
    op.add_column(
        "task_links",
        sa.Column(
            "tracker_link_id",
            sa.String(),
            sa.ForeignKey("tracker_links.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_task_links_tracker_link_id", "task_links", ["tracker_link_id"])
    op.execute("UPDATE task_links SET state = 'ready' WHERE job_id IS NULL AND depends_on = '[]'")
    op.execute("UPDATE task_links SET state = 'running' WHERE job_id IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_task_links_tracker_link_id", table_name="task_links")
    op.drop_column("task_links", "tracker_link_id")
    op.drop_column("task_links", "state")
