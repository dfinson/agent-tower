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


def _has_column(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _has_index(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA index_list({table_name})")).fetchall()
    return any(row[1] == index_name for row in rows)


def upgrade() -> None:
    if not _has_column("task_links", "state"):
        with op.batch_alter_table("task_links", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column("state", sa.String(), nullable=False, server_default="waiting"),
            )

    if not _has_column("task_links", "tracker_link_id"):
        with op.batch_alter_table("task_links", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column("tracker_link_id", sa.String(), nullable=True),
            )

    if not _has_index("task_links", "ix_task_links_tracker_link_id"):
        op.create_index("ix_task_links_tracker_link_id", "task_links", ["tracker_link_id"])

    op.execute("UPDATE task_links SET state = 'ready' WHERE job_id IS NULL AND depends_on = '[]'")
    op.execute("UPDATE task_links SET state = 'running' WHERE job_id IS NOT NULL")


def downgrade() -> None:
    if _has_index("task_links", "ix_task_links_tracker_link_id"):
        op.drop_index("ix_task_links_tracker_link_id", table_name="task_links")
    if _has_column("task_links", "tracker_link_id"):
        op.drop_column("task_links", "tracker_link_id")
    if _has_column("task_links", "state"):
        op.drop_column("task_links", "state")
