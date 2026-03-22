"""Add job_metrics table for persisted telemetry snapshots.

Revision ID: 0004_add_job_metrics
Revises: a3f1c8d70001
Create Date: 2026-03-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_job_metrics"
down_revision: Union[str, None] = "a3f1c8d70001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_metrics",
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_metrics")
