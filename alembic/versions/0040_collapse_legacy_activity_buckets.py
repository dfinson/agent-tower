"""Collapse legacy activity buckets: delegation → investigation, feature_dev → implementation.

'delegation' was removed as an output of _classify_turn_intent — unresolved
sub-agent turns now fall through to 'investigation'.  'feature_dev' was an
older label that is equivalent to 'implementation'.

Revision ID: 0040
Revises: 0039
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _merge_bucket(
    conn: sa.engine.Connection,
    table: str,
    old_bucket: str,
    new_bucket: str,
    value_columns: list[str],
) -> None:
    """Merge rows from old_bucket into new_bucket within a table.

    For jobs that already have a row for new_bucket in the same dimension,
    adds the old values into the existing row, then deletes the old row.
    For jobs that only have old_bucket, renames in place.
    """
    # Merge into existing new_bucket rows
    set_clause = ", ".join(
        f"{col} = {table}.{col} + src.{col}" for col in value_columns
    )
    conn.execute(
        sa.text(f"""
            UPDATE {table}
            SET {set_clause}
            FROM {table} AS src
            WHERE {table}.job_id = src.job_id
              AND {table}.dimension = src.dimension
              AND {table}.bucket = :new_bucket
              AND src.bucket = :old_bucket
        """),
        {"old_bucket": old_bucket, "new_bucket": new_bucket},
    )
    # Delete old_bucket rows that were merged
    conn.execute(
        sa.text(f"""
            DELETE FROM {table}
            WHERE bucket = :old_bucket
              AND job_id IN (
                  SELECT job_id FROM {table} t2
                  WHERE t2.bucket = :new_bucket
                    AND t2.dimension = {table}.dimension
              )
        """),
        {"old_bucket": old_bucket, "new_bucket": new_bucket},
    )
    # Rename remaining old_bucket rows (no conflict)
    conn.execute(
        sa.text(f"""
            UPDATE {table}
            SET bucket = :new_bucket
            WHERE bucket = :old_bucket
        """),
        {"old_bucket": old_bucket, "new_bucket": new_bucket},
    )


def upgrade() -> None:
    conn = op.get_bind()

    cost_cols = [
        "cost_usd", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "call_count",
    ]
    latency_cols = ["wall_clock_ms", "sum_duration_ms", "span_count"]

    # delegation → investigation
    _merge_bucket(conn, "job_cost_attribution", "delegation", "investigation", cost_cols)
    _merge_bucket(conn, "job_latency_attribution", "delegation", "investigation", latency_cols)

    # feature_dev → implementation
    _merge_bucket(conn, "job_cost_attribution", "feature_dev", "implementation", cost_cols)
    _merge_bucket(conn, "job_latency_attribution", "feature_dev", "implementation", latency_cols)


def downgrade() -> None:
    # Non-reversible: we cannot distinguish which investigation rows
    # were originally delegation, or which implementation rows were feature_dev.
    pass
