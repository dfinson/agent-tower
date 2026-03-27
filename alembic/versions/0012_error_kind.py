"""Add error_kind classification columns.

Revision ID: 0012_error_kind
Revises: 0011_merge_review_and_observations_heads
Create Date: 2026-03-27

Distinguishes agent errors (bad args / typos) from genuine tool failures
(permission denied, I/O error, etc.).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0012_error_kind"
down_revision: Union[str, None] = "0011_merge_review_and_observations_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-span classification: 'agent_error', 'tool_error', or NULL (success)
    op.execute("ALTER TABLE job_telemetry_spans ADD COLUMN error_kind TEXT")

    # Summary-level counter for agent errors (complements existing tool_failure_count)
    op.execute(
        "ALTER TABLE job_telemetry_summary ADD COLUMN agent_error_count INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN before 3.35, but for forward compat:
    op.execute("ALTER TABLE job_telemetry_spans DROP COLUMN error_kind")
    op.execute("ALTER TABLE job_telemetry_summary DROP COLUMN agent_error_count")
