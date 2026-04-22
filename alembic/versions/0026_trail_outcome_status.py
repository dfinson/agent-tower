"""Add outcome_status column to trail_nodes for structured success/failure tracking.

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trail_nodes",
        sa.Column("outcome_status", sa.String(10), nullable=True),
    )
    op.create_index(
        "ix_trail_nodes_outcome_status",
        "trail_nodes",
        ["job_id", "outcome_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_trail_nodes_outcome_status")
    op.drop_column("trail_nodes", "outcome_status")
