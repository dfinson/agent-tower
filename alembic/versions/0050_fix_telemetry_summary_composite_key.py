"""Fix telemetry summary composite key for ON CONFLICT clause.

The model declares (job_id, session_kind) as composite PK but the
physical table only has job_id as PK.  SQLite doesn't support adding
columns to a PK after creation.  Add a UNIQUE constraint on the pair
so the ON CONFLICT(job_id, session_kind) clause works correctly.

Revision ID: 0050
Revises: 0049
Create Date: 2026-05-17

"""

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT, so we use
    # CREATE UNIQUE INDEX which serves the same purpose for ON CONFLICT.
    op.create_index(
        "uq_telemetry_summary_job_session",
        "job_telemetry_summary",
        ["job_id", "session_kind"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_telemetry_summary_job_session", table_name="job_telemetry_summary")
