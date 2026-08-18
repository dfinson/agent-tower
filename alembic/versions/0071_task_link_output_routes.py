"""Persist configured TaskLink recipe output routes.

Revision ID: 0068
Revises: 0067
"""

import sqlalchemy as sa

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def upgrade() -> None:
    if not _has_column("task_links", "output_routes"):
        with op.batch_alter_table("task_links", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column("output_routes", sa.Text(), nullable=False, server_default="[]"),
            )


def downgrade() -> None:
    if _has_column("task_links", "output_routes"):
        with op.batch_alter_table("task_links", recreate="always") as batch_op:
            batch_op.drop_column("output_routes")
