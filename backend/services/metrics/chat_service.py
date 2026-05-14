"""Chat-driven metrics composer — LLM orchestration.

Two-step flow:
1. User question → LLM generates SQL queries + viz recommendation
2. Execute queries → LLM verifies results + writes narrative

The system prompt contains the full telemetry schema so the LLM can
write correct SQLite queries without guessing.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from backend.services.metrics.query_executor import (
    QueryValidationError,
    execute_query,
)
from backend.services.sidecar.session import SidecarSessionManager

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt — full schema for the LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a data analyst for CodePlane, an AI coding agent control plane.
You answer questions about agent telemetry by writing SQLite queries.

## Available Tables

### job_telemetry_spans
Columns: id, job_id, session_kind, span_type, name, started_at, \
duration_ms, attrs_json, tool_category, tool_target, turn_number, \
execution_phase, is_retry, retries_span_id, input_tokens, output_tokens, \
cache_read_tokens, cache_write_tokens, cost_usd, tool_args_json, \
result_size_bytes, error_kind, turn_id, preceding_context, \
motivation_summary, edit_motivations, created_at

Notes:
- session_kind is 'job' for main sessions, 'sidecar' for utility sessions
- span_type: 'llm_call', 'tool_call', 'turn'
- tool_category: 'file_read', 'file_write', 'shell', 'search', 'browser', etc.
- execution_phase: 'investigation', 'implementation', 'debugging', 'verification', etc.
- cost_usd may be NULL — use COALESCE(cost_usd, 0)
- Timestamps are ISO 8601 strings

### job_telemetry_summary
Columns: job_id, session_kind, sdk, model, repo, branch, status, \
created_at, completed_at, duration_ms, input_tokens, output_tokens, \
cache_read_tokens, cache_write_tokens, total_cost_usd, \
premium_requests, llm_call_count, tool_call_count, \
tool_failure_count, total_turns, retry_count, file_read_count, \
file_write_count, diff_lines_added, diff_lines_removed, \
peak_turn_cost_usd, avg_turn_cost_usd, compactions, \
tokens_compacted, subagent_cost_usd, agent_error_count, \
tool_error_count, description, job_mode, total_cost_with_sidecar_usd

Notes:
- Composite PK: (job_id, session_kind)
- Filter session_kind = 'job' for main session metrics
- repo contains full path — use LIKE '%/repo_name' for matching
- status: 'completed', 'failed', 'cancelled', 'running', 'review', 'pending'

### job_cost_attribution
Columns: id, job_id, dimension, bucket, cost_usd, input_tokens, \
output_tokens, call_count, cache_read_tokens, cache_write_tokens, \
model, created_at

Notes:
- dimension: 'phase', 'tool_category', 'turn', 'activity', 'action', \
'purpose', 'action_purpose', 'model'
- activity buckets: 'implementation', 'debugging', 'investigation', \
'verification', 'git_ops', 'communication', 'setup', 'reasoning', 'overhead'

### jobs
Columns: id, status, error, error_kind, repo_path, branch, sdk, \
created_at, started_at, completed_at, parent_job_id, name, \
description, mode

## Visualization Templates
When recommending a visualization, choose one of:
- stat_card: Single number with label. Data: [{value: N, label: "text"}]
- bar_chart: Categorical bars. Data: [{name: "X", value: N}, ...]
- line_chart: Time series. Data: [{date: "YYYY-MM-DD", value: N}, ...]
- stacked_bar: Multi-series bars. Data: [{name: "X", series1: N, series2: N}, ...]
- donut: Proportional. Data: [{name: "X", value: N}, ...]
- table: Tabular. Data: [{col1: val, col2: val, ...}, ...]
- heatmap: 2D grid. Data: [{x: "X", y: "Y", value: N}, ...]

## Rules
1. Write ONLY SELECT/WITH queries
2. Always filter session_kind = 'job' unless asked about sidecars
3. Use COALESCE(cost_usd, 0) for nullable cost columns
4. For date filtering: WHERE created_at >= datetime('now', '-N days')
5. Keep queries efficient — use appropriate GROUP BY and LIMIT
6. Return JSON in the EXACT format specified in each prompt
"""

_STEP1_TEMPLATE = """\
User question: {question}

{context}

Write SQLite queries to answer this question. Return ONLY valid JSON:
{{
  "queries": [
    {{"sql": "SELECT ...", "purpose": "brief description"}}
  ],
  "viz": "template_name",
  "viz_config": {{"title": "Chart Title", "x_key": "col_name", "y_key": "col_name"}}
}}

If the question cannot be answered with the available tables, return:
{{"error": "explanation of why"}}
"""

_STEP2_TEMPLATE = """\
Original question: {question}

Queries executed and results:
{results_block}

Based on these results:
1. Verify the data answers the question correctly
2. Transform the raw query results into the visualization format for "{viz}" template
3. Write a brief narrative summary (1-2 sentences)

Return ONLY valid JSON:
{{
  "viz_data": [the data array for the visualization template],
  "narrative": "brief summary of the findings",
  "title": "short metric title for dashboard"
}}

If the results don't adequately answer the question, return:
{{"error": "explanation", "suggestion": "try asking about..."}}
"""


class MetricsChatService:
    """Orchestrates the two-step LLM flow for metrics questions."""

    def __init__(
        self,
        sidecar: SidecarSessionManager,
        session_factory: Any,
    ) -> None:
        self._sidecar = sidecar
        self._session_factory = session_factory

    async def ask(
        self,
        question: str,
        *,
        period_days: int | None = None,
        conversation_summary: str = "",
    ) -> ChatResponse:
        """Process a user question end-to-end.

        Returns a ``ChatResponse`` with the narrative, viz data, and
        SQL queries used.
        """
        context_parts: list[str] = []
        if period_days:
            context_parts.append(
                f"Default period filter: last {period_days} days "
                f"(WHERE created_at >= datetime('now', '-{period_days} days'))"
            )
        if conversation_summary:
            context_parts.append(f"Previous context:\n{conversation_summary}")

        context = "\n".join(context_parts)

        # Step 1: Generate SQL
        step1_prompt = (
            _SYSTEM_PROMPT
            + "\n\n"
            + _STEP1_TEMPLATE.format(question=question, context=context)
        )

        try:
            step1_raw = await self._sidecar.complete(step1_prompt, timeout=30.0)
        except Exception as exc:
            log.error("metrics_chat_step1_failed", error=str(exc))
            return ChatResponse(
                narrative=f"Failed to generate queries: {exc}",
                error=True,
            )

        step1 = _parse_json(step1_raw)
        if step1 is None:
            return ChatResponse(
                narrative="The model returned an unparseable response. Please try rephrasing.",
                error=True,
                raw_response=step1_raw,
            )

        if "error" in step1:
            return ChatResponse(
                narrative=step1["error"],
                error=True,
            )

        queries = step1.get("queries", [])
        viz = step1.get("viz", "table")
        viz_config = step1.get("viz_config", {})

        if not queries:
            return ChatResponse(
                narrative="No queries generated. Try being more specific.",
                error=True,
            )

        # Execute queries
        results_block_parts: list[str] = []
        all_results: list[dict[str, Any]] = []
        executed_sql: list[str] = []

        for i, q in enumerate(queries):
            sql = q.get("sql", "")
            purpose = q.get("purpose", "")
            try:
                rows = await execute_query(
                    self._session_factory, sql, timeout_seconds=30.0
                )
                results_block_parts.append(
                    f"Query {i + 1} ({purpose}):\n"
                    f"SQL: {sql}\n"
                    f"Results ({len(rows)} rows): {json.dumps(rows[:50])}\n"
                )
                all_results.extend(rows)
                executed_sql.append(sql)
            except QueryValidationError as exc:
                results_block_parts.append(
                    f"Query {i + 1} ({purpose}):\n"
                    f"SQL: {sql}\n"
                    f"ERROR: {exc}\n"
                )

        if not executed_sql:
            return ChatResponse(
                narrative="All queries failed validation or execution.",
                error=True,
                sql_queries=[q.get("sql", "") for q in queries],
            )

        # Step 2: Verify + format results
        step2_prompt = (
            _SYSTEM_PROMPT
            + "\n\n"
            + _STEP2_TEMPLATE.format(
                question=question,
                results_block="\n".join(results_block_parts),
                viz=viz,
            )
        )

        try:
            step2_raw = await self._sidecar.complete(step2_prompt, timeout=30.0)
        except Exception as exc:
            log.error("metrics_chat_step2_failed", error=str(exc))
            # Fall back to raw results
            return ChatResponse(
                narrative="Got results but couldn't format them. Showing raw data.",
                viz="table",
                viz_config={"title": "Raw Results"},
                viz_data=all_results[:100],
                sql_queries=executed_sql,
            )

        step2 = _parse_json(step2_raw)
        if step2 is None:
            return ChatResponse(
                narrative="Results obtained but formatting failed. Showing raw data.",
                viz="table",
                viz_config={"title": "Raw Results"},
                viz_data=all_results[:100],
                sql_queries=executed_sql,
                raw_response=step2_raw,
            )

        if "error" in step2:
            return ChatResponse(
                narrative=step2["error"],
                suggestion=step2.get("suggestion"),
                error=True,
                sql_queries=executed_sql,
            )

        return ChatResponse(
            narrative=step2.get("narrative", ""),
            title=step2.get("title", "Custom Metric"),
            viz=viz,
            viz_config=viz_config,
            viz_data=step2.get("viz_data", all_results),
            sql_queries=executed_sql,
        )


class ChatResponse:
    """Result from a metrics chat question."""

    __slots__ = (
        "narrative",
        "title",
        "viz",
        "viz_config",
        "viz_data",
        "sql_queries",
        "suggestion",
        "error",
        "raw_response",
        "message_id",
    )

    def __init__(
        self,
        *,
        narrative: str = "",
        title: str = "",
        viz: str = "table",
        viz_config: dict[str, Any] | None = None,
        viz_data: list[Any] | None = None,
        sql_queries: list[str] | None = None,
        suggestion: str | None = None,
        error: bool = False,
        raw_response: str | None = None,
    ) -> None:
        self.narrative = narrative
        self.title = title
        self.viz = viz
        self.viz_config = viz_config or {}
        self.viz_data = viz_data or []
        self.sql_queries = sql_queries or []
        self.suggestion = suggestion
        self.error = error
        self.raw_response = raw_response
        self.message_id = uuid.uuid4().hex[:12]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "messageId": self.message_id,
            "narrative": self.narrative,
            "error": self.error,
        }
        if self.title:
            d["title"] = self.title
        if not self.error:
            d["viz"] = self.viz
            d["vizConfig"] = self.viz_config
            d["vizData"] = self.viz_data
        if self.sql_queries:
            d["sqlQueries"] = self.sql_queries
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d

    def condensed_summary(self) -> str:
        """One-line summary for conversation memory."""
        if self.error:
            return f"[error] {self.narrative[:200]}"
        return f"{self.title}: {self.narrative[:200]}"


def _parse_json(raw: str) -> dict[str, Any] | None:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None
