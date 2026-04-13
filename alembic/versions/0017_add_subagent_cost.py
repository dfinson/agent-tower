"""Add subagent_cost_usd column to job_telemetry_summary.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_telemetry_summary",
        sa.Column("subagent_cost_usd", sa.Float(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("job_telemetry_summary", "subagent_cost_usd")
