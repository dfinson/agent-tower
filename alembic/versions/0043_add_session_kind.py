"""Add session_kind column for sidecar telemetry tracking.

Adds a session_kind column to job_telemetry_summary and
job_telemetry_spans so sidecar sessions (preflight, memory_extraction,
memory_compaction, narrator, sister) can record their own cost/usage
independently of the parent job.

The summary table's PK changes from (job_id) to (job_id, session_kind)
so a single job can have multiple telemetry rows — one per session kind.
SQLite requires table recreation for PK changes, so we use Alembic's
batch_alter_table.

Revision ID: 0043
Revises: 0042
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- job_telemetry_summary ---
    # SQLite can't alter PKs in-place. batch_alter_table recreates the table
    # with the new schema, migrating data automatically.
    with op.batch_alter_table(
        "job_telemetry_summary",
        recreate="always",
        # Declare the NEW composite PK so the recreated table uses it.
        table_args=(
            sa.PrimaryKeyConstraint("job_id", "session_kind"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        ),
    ) as batch_op:
        batch_op.add_column(
            sa.Column("session_kind", sa.Text(), nullable=False, server_default="job"),
        )

    # Indexes on the recreated table
    op.create_index(
        "ix_telemetry_summary_session_kind",
        "job_telemetry_summary",
        ["session_kind"],
    )

    # --- job_telemetry_spans ---
    op.add_column(
        "job_telemetry_spans",
        sa.Column("session_kind", sa.Text(), nullable=False, server_default="job"),
    )
    op.create_index(
        "ix_telemetry_spans_session_kind",
        "job_telemetry_spans",
        ["session_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_spans_session_kind", table_name="job_telemetry_spans")
    op.drop_column("job_telemetry_spans", "session_kind")

    op.drop_index("ix_telemetry_summary_session_kind", table_name="job_telemetry_summary")
    # Recreate with original single-column PK
    with op.batch_alter_table(
        "job_telemetry_summary",
        recreate="always",
        table_args=(
            sa.PrimaryKeyConstraint("job_id"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        ),
    ) as batch_op:
        batch_op.drop_column("session_kind")
