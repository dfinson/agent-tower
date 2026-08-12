"""Add tracker summary read model (Story 3.3, AD-7).

Revision ID: 0065
Revises: 0064
"""

import sqlalchemy as sa

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tracker_summaries",
        sa.Column(
            "tracker_link_id",
            sa.String(),
            sa.ForeignKey("tracker_links.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tickets_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("last_synced_at", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tracker_summaries")
