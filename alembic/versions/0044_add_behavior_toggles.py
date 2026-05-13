"""Add enable_stall_detection and enable_plan_tracking columns to jobs.

These nullable boolean columns let users opt out of stall detection and
plan tracking on a per-job basis.  NULL means "use the system default"
(enabled), False explicitly disables the behavior.

Revision ID: 0044
Revises: 0043
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("enable_stall_detection", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("enable_plan_tracking", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("enable_plan_tracking")
        batch_op.drop_column("enable_stall_detection")
