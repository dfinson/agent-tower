"""Add durable terminal artifact collection status to jobs.

Revision ID: 0057
Revises: 0056
"""

import sqlalchemy as sa

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("artifact_collection_status", sa.String(), nullable=False, server_default="pending"),
    )
    op.add_column("jobs", sa.Column("artifact_collection_error", sa.Text(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("artifact_collection_session_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("jobs", sa.Column("artifact_collection_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "artifact_collection_updated_at")
    op.drop_column("jobs", "artifact_collection_session_count")
    op.drop_column("jobs", "artifact_collection_error")
    op.drop_column("jobs", "artifact_collection_status")
