"""Add job_file_cost table for file-centric cost attribution.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_file_cost",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("file_path", sa.String, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("read_cost", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("write_cost", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("turn_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_file_cost_job", "job_file_cost", ["job_id"])
    op.create_index("idx_file_cost_path", "job_file_cost", ["file_path"])


def downgrade() -> None:
    op.drop_index("idx_file_cost_path")
    op.drop_index("idx_file_cost_job")
    op.drop_table("job_file_cost")
