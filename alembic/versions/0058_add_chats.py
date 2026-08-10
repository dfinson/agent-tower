"""Add chats table.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
    )
    op.create_index("ix_chats_project_id", "chats", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_chats_project_id", table_name="chats")
    op.drop_table("chats")
