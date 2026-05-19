"""Add enrichment columns to secondary_session_entries.

Brings secondary session tool calls to parity with main transcript entries
by storing the same enriched fields (display, result, success, issue, visibility).

Revision ID: 0053
Revises: 0052
"""

from alembic import op
import sqlalchemy as sa

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("secondary_session_entries") as batch_op:
        batch_op.add_column(sa.Column("tool_result", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tool_display", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tool_display_full", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tool_success", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("tool_issue", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tool_visibility", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("secondary_session_entries") as batch_op:
        batch_op.drop_column("tool_visibility")
        batch_op.drop_column("tool_issue")
        batch_op.drop_column("tool_success")
        batch_op.drop_column("tool_display_full")
        batch_op.drop_column("tool_display")
        batch_op.drop_column("tool_result")
