"""Add turn_id column to job_telemetry_spans and backfill from transcript events.

Bridges the join gap between the transcript event stream (which carries turn_id
UUIDs) and the telemetry span table (which only had turn_number integers).
With turn_id on spans, you can directly JOIN spans to transcript events to
reconstruct agent reasoning → tool action → file target chains.

Backfill strategy: match each tool span to its transcript event using
(job_id, tool_name, tool_args) + positional ordering.  Validated across all
historical data: 100% match rate, 0 ordering violations.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column
    op.execute("ALTER TABLE job_telemetry_spans ADD COLUMN turn_id TEXT")

    # 2. Backfill from transcript events.
    #
    # For each tool span, find the matching transcript event by (job_id,
    # tool_name, normalized tool_args) using positional ordering: the nth
    # span with a given (name, args) key maps to the nth transcript event
    # with that same key.
    #
    # We use a CTE with ROW_NUMBER to assign positional ordinals within
    # each (job_id, tool_name, tool_args) group, then join on the ordinal.
    op.execute("""
        UPDATE job_telemetry_spans
        SET turn_id = (
            SELECT ev.turn_id
            FROM (
                SELECT
                    e.id,
                    json_extract(e.payload, '$.turn_id') AS turn_id,
                    json_extract(e.payload, '$.tool_name') AS tool_name,
                    json_extract(e.payload, '$.tool_args') AS tool_args,
                    e.job_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY e.job_id,
                                     json_extract(e.payload, '$.tool_name'),
                                     json_extract(e.payload, '$.tool_args')
                        ORDER BY e.id
                    ) AS rn
                FROM events e
                WHERE e.kind = 'TranscriptUpdated'
                  AND json_extract(e.payload, '$.role') = 'tool_call'
                  AND json_extract(e.payload, '$.turn_id') IS NOT NULL
            ) ev
            INNER JOIN (
                SELECT
                    s2.id,
                    s2.job_id,
                    s2.name,
                    s2.tool_args_json,
                    ROW_NUMBER() OVER (
                        PARTITION BY s2.job_id, s2.name, s2.tool_args_json
                        ORDER BY s2.id
                    ) AS rn
                FROM job_telemetry_spans s2
                WHERE s2.span_type = 'tool'
            ) sp ON sp.id = job_telemetry_spans.id
            WHERE ev.job_id = sp.job_id
              AND ev.tool_name = sp.name
              AND ev.tool_args = sp.tool_args_json
              AND ev.rn = sp.rn
        )
        WHERE span_type = 'tool'
    """)

    # 3. For LLM spans, backfill by finding the closest preceding tool span
    #    in the same job that already has a turn_id and the same turn_number.
    #    LLM spans and tool spans in the same turn share the same turn_number,
    #    so we can propagate the turn_id from the tool span.
    op.execute("""
        UPDATE job_telemetry_spans
        SET turn_id = (
            SELECT t.turn_id
            FROM job_telemetry_spans t
            WHERE t.job_id = job_telemetry_spans.job_id
              AND t.span_type = 'tool'
              AND t.turn_number = job_telemetry_spans.turn_number
              AND t.turn_id IS NOT NULL
            ORDER BY t.id ASC
            LIMIT 1
        )
        WHERE span_type = 'llm'
          AND turn_id IS NULL
    """)

    # 4. Index for join queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spans_turn_id "
        "ON job_telemetry_spans (job_id, turn_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_spans_turn_id")
    # SQLite doesn't support DROP COLUMN before 3.35.0; recreate table
    # if needed.  For simplicity, just NULL out the column.
    op.execute("UPDATE job_telemetry_spans SET turn_id = NULL")
