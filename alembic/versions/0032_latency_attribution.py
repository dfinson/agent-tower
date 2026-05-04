"""Add latency attribution table and summary columns.

Creates ``job_latency_attribution`` for per-job latency breakdown
(category, activity, phase, tool_type, turn).  Extends
``job_telemetry_summary`` with latency-specific columns.

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Extend job_telemetry_summary with latency breakdown columns ---
    with op.batch_alter_table("job_telemetry_summary") as batch_op:
        batch_op.add_column(
            sa.Column("llm_wait_ms", sa.Integer, nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("tool_exec_ms", sa.Integer, nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("idle_ms", sa.Integer, nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("parallelism_ratio", sa.Float, nullable=False, server_default="0.0")
        )

    # --- Per-job latency attribution breakdown ---
    op.create_table(
        "job_latency_attribution",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("dimension", sa.String, nullable=False),
        sa.Column("bucket", sa.String, nullable=False),
        sa.Column("wall_clock_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sum_duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("span_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("p50_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("p95_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pct_of_total", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_latency_attr_job", "job_latency_attribution", ["job_id"])
    op.create_index(
        "idx_latency_attr_dimension", "job_latency_attribution", ["dimension", "bucket"]
    )


def downgrade() -> None:
    op.drop_index("idx_latency_attr_dimension", table_name="job_latency_attribution")
    op.drop_index("idx_latency_attr_job", table_name="job_latency_attribution")
    op.drop_table("job_latency_attribution")

    with op.batch_alter_table("job_telemetry_summary") as batch_op:
        batch_op.drop_column("parallelism_ratio")
        batch_op.drop_column("idle_ms")
        batch_op.drop_column("tool_exec_ms")
        batch_op.drop_column("llm_wait_ms")
