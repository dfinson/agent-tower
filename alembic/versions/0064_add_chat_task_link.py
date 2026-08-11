"""Add task_link_id to chats.

Revision ID: 0064
Revises: 0063
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("chats") as batch_op:
        batch_op.add_column(sa.Column("task_link_id", sa.String(), nullable=True))
        batch_op.create_index("ix_chats_task_link_id", ["task_link_id"])
        batch_op.create_foreign_key(
            "fk_chats_task_link_id_task_links",
            "task_links",
            ["task_link_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("chats") as batch_op:
        batch_op.drop_constraint("fk_chats_task_link_id_task_links", type_="foreignkey")
        batch_op.drop_index("ix_chats_task_link_id")
        batch_op.drop_column("task_link_id")
