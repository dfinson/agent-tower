"""Add trail_state_snapshot column to jobs table.

Per §13.5 of the unified trail service design: periodic snapshot of
TrailJobState enables lossless recovery on session_resumed instead of
lossy reconstruction from trail nodes alone.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column("trail_state_snapshot", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("trail_state_snapshot")
