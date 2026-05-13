"""Collapse 'debugging' activity bucket into 'implementation'.

The 'debugging' category was a subjective label based on keyword matching
in job descriptions. It represents the same token spend as implementation
(file writes). This migration renames all existing 'debugging' rows to
'implementation' and merges their values where both already exist.

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- job_cost_attribution: merge debugging → implementation ---
    # For jobs that have BOTH a 'debugging' and 'implementation' row in the same
    # dimension, add the debugging values into implementation, then delete debugging.
    conn.execute(
        sa.text("""
            UPDATE job_cost_attribution
            SET cost_usd = job_cost_attribution.cost_usd + src.cost_usd,
                input_tokens = job_cost_attribution.input_tokens + src.input_tokens,
                output_tokens = job_cost_attribution.output_tokens + src.output_tokens,
                cache_read_tokens = job_cost_attribution.cache_read_tokens + src.cache_read_tokens,
                cache_write_tokens = job_cost_attribution.cache_write_tokens + src.cache_write_tokens,
                call_count = job_cost_attribution.call_count + src.call_count
            FROM job_cost_attribution AS src
            WHERE job_cost_attribution.job_id = src.job_id
              AND job_cost_attribution.dimension = src.dimension
              AND job_cost_attribution.bucket = 'implementation'
              AND src.bucket = 'debugging'
        """)
    )
    conn.execute(
        sa.text("""
            DELETE FROM job_cost_attribution
            WHERE bucket = 'debugging'
              AND job_id IN (
                  SELECT job_id FROM job_cost_attribution
                  WHERE bucket = 'implementation' AND dimension = job_cost_attribution.dimension
              )
        """)
    )
    # For jobs that only have 'debugging' (no 'implementation' row), just rename.
    conn.execute(
        sa.text("""
            UPDATE job_cost_attribution
            SET bucket = 'implementation'
            WHERE bucket = 'debugging'
        """)
    )

    # --- job_latency_attribution: merge debugging → implementation ---
    conn.execute(
        sa.text("""
            UPDATE job_latency_attribution
            SET wall_clock_ms = job_latency_attribution.wall_clock_ms + src.wall_clock_ms,
                sum_duration_ms = job_latency_attribution.sum_duration_ms + src.sum_duration_ms,
                span_count = job_latency_attribution.span_count + src.span_count
            FROM job_latency_attribution AS src
            WHERE job_latency_attribution.job_id = src.job_id
              AND job_latency_attribution.dimension = src.dimension
              AND job_latency_attribution.bucket = 'implementation'
              AND src.bucket = 'debugging'
        """)
    )
    conn.execute(
        sa.text("""
            DELETE FROM job_latency_attribution
            WHERE bucket = 'debugging'
              AND job_id IN (
                  SELECT job_id FROM job_latency_attribution
                  WHERE bucket = 'implementation' AND dimension = job_latency_attribution.dimension
              )
        """)
    )
    conn.execute(
        sa.text("""
            UPDATE job_latency_attribution
            SET bucket = 'implementation'
            WHERE bucket = 'debugging'
        """)
    )


def downgrade() -> None:
    # Cannot reliably split implementation back into debugging — no-op.
    pass
