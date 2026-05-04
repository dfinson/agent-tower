"""Post-job latency attribution pipeline.

Runs after a job completes (alongside cost attribution) to compute
latency breakdowns by dimension (activity, category, phase, turn, tool_type)
and write them to the latency attribution table.  Also updates summary
columns for idle time and parallelism ratio.

The **activity** dimension mirrors cost attribution exactly — each turn is
classified by intent (implementation, investigation, verification, etc.)
and all span durations within that turn are attributed to that activity.
"""

from __future__ import annotations

import json as _json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.api_schemas import ExecutionPhase
from backend.services.cost_attribution import TurnContext, _classify_turn_intent
from backend.services.tool_classifier import classify_tool

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.persistence.latency_attribution_repo import LatencyAttributionRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

log = structlog.get_logger()


def _percentile(sorted_values: list[int], pct: float) -> int:
    """Compute percentile from a pre-sorted list."""
    if not sorted_values:
        return 0
    idx = int(len(sorted_values) * pct)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


def _compute_wall_clock(intervals: list[tuple[float, float]]) -> int:
    """Compute wall-clock time from possibly overlapping (start, end) intervals.

    Merges overlapping intervals and sums the non-overlapping spans.
    Returns milliseconds.
    """
    if not intervals:
        return 0
    sorted_intervals = sorted(intervals)
    merged: list[tuple[float, float]] = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return int(sum(end - start for start, end in merged))


async def compute_latency_attribution(
    session: AsyncSession,
    job_id: str,
) -> None:
    """Compute and store latency attribution for a completed job.

    Reads all spans for the job, aggregates duration by dimension,
    computes percentiles, and writes attribution rows.
    """
    from backend.persistence.latency_attribution_repo import LatencyAttributionRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

    await _compute_latency(
        job_id=job_id,
        spans_repo=TelemetrySpansRepository(session),
        latency_repo=LatencyAttributionRepository(session),
        summary_repo=TelemetrySummaryRepository(session),
        session=session,
    )


async def _compute_latency(
    *,
    job_id: str,
    spans_repo: TelemetrySpansRepository,
    latency_repo: LatencyAttributionRepository,
    summary_repo: TelemetrySummaryRepository,
    session: AsyncSession,
) -> None:
    """Core latency attribution logic."""
    spans = await spans_repo.list_for_job(job_id)
    if not spans:
        log.info("latency_attribution_skip_no_spans", job_id=job_id)
        return

    # Get job total duration from summary
    summary = await summary_repo.get(job_id)
    total_duration_ms = int(summary.get("duration_ms", 0)) if summary else 0

    # Collect durations by each dimension
    by_category: dict[str, list[int]] = defaultdict(list)  # llm/tool/approval
    by_phase: dict[str, list[int]] = defaultdict(list)
    by_turn: dict[int, list[int]] = defaultdict(list)
    by_tool_type: dict[str, list[int]] = defaultdict(list)

    # Also collect intervals for wall-clock computation
    category_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    turn_intervals: dict[int, list[tuple[float, float]]] = defaultdict(list)

    # Per-turn: collect durations and intervals for activity attribution
    turn_durations: dict[int, list[int]] = defaultdict(list)
    turn_span_intervals: dict[int, list[tuple[float, float]]] = defaultdict(list)

    # Build turn contexts for intent classification (mirrors cost attribution)
    turn_contexts: dict[int, TurnContext] = defaultdict(
        lambda: TurnContext(
            phase=None, cost_usd=0.0, input_tokens=0, output_tokens=0,
            tool_categories=[], shell_commands=[],
        )
    )

    total_span_sum_ms = 0

    for span in spans:
        duration_ms = int(float(span.get("duration_ms", 0) or 0))
        if duration_ms <= 0:
            continue

        offset_sec = float(span.get("started_at", 0) or 0)
        start_ms = offset_sec * 1000
        end_ms = start_ms + duration_ms
        total_span_sum_ms += duration_ms

        span_type = span.get("span_type", "")
        turn = span.get("turn_number")

        # Category dimension: llm / tool / approval
        if span_type == "llm":
            category = "llm"
        elif span_type == "tool":
            category = "tool"
        elif span_type == "approval":
            category = "approval_wait"
        else:
            category = "other"

        by_category[category].append(duration_ms)
        category_intervals[category].append((start_ms, end_ms))

        # Turn dimension
        if turn is not None:
            turn_int = int(turn)
            by_turn[turn_int].append(duration_ms)
            turn_intervals[turn_int].append((start_ms, end_ms))
            turn_durations[turn_int].append(duration_ms)
            turn_span_intervals[turn_int].append((start_ms, end_ms))

        # Phase dimension
        phase = span.get("execution_phase")
        if phase and phase in {p.value for p in ExecutionPhase}:
            by_phase[phase].append(duration_ms)

        # Tool type dimension (only for tool spans)
        if span_type == "tool":
            tool_name = span.get("name") or ""
            tool_cat = classify_tool(tool_name) or "other"
            by_tool_type[tool_cat].append(duration_ms)

            # Build turn context for intent classification
            if turn is not None:
                turn_int = int(turn)
                turn_contexts[turn_int]["tool_categories"].append(tool_cat)
                # Collect shell command text
                if tool_cat == "shell":
                    tool_args = span.get("tool_args_json")
                    if isinstance(tool_args, str):
                        try:
                            parsed = _json.loads(tool_args)
                            cmd = parsed.get("command", "") or parsed.get("cmd", "")
                        except (ValueError, TypeError):
                            cmd = ""
                    elif isinstance(tool_args, dict):
                        cmd = tool_args.get("command", "") or tool_args.get("cmd", "")
                    else:
                        cmd = ""
                    if cmd:
                        turn_contexts[turn_int]["shell_commands"].append(str(cmd))

        # Track LLM output tokens for communication classification
        if span_type == "llm" and turn is not None:
            out_tok = span.get("output_tokens") or 0
            turn_contexts[int(turn)]["output_tokens"] += int(out_tok or 0)

    # --- Activity dimension: classify each turn's intent, aggregate durations ---
    by_activity: dict[str, list[int]] = defaultdict(list)
    activity_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for turn_num, context in turn_contexts.items():
        activity = _classify_turn_intent(context)
        by_activity[activity].extend(turn_durations.get(turn_num, []))
        activity_intervals[activity].extend(turn_span_intervals.get(turn_num, []))

    # Also attribute spans with no turn to "other"
    for span in spans:
        duration_ms = int(float(span.get("duration_ms", 0) or 0))
        if duration_ms <= 0:
            continue
        turn = span.get("turn_number")
        if turn is None:
            by_activity["other"].append(duration_ms)
            offset_sec = float(span.get("started_at", 0) or 0)
            start_ms = offset_sec * 1000
            activity_intervals["other"].append((start_ms, start_ms + duration_ms))

    # Compute attribution rows
    rows: list[dict[str, Any]] = []

    def _build_rows(
        dimension: str,
        data: dict[Any, list[int]],
        intervals: dict[Any, list[tuple[float, float]]] | None = None,
    ) -> None:
        for bucket_key, durations in data.items():
            sorted_durs = sorted(durations)
            sum_ms = sum(durations)
            wall_ms = (
                _compute_wall_clock(intervals[bucket_key])
                if intervals and bucket_key in intervals
                else sum_ms
            )
            pct = (wall_ms / total_duration_ms * 100) if total_duration_ms > 0 else 0.0
            rows.append({
                "dimension": dimension,
                "bucket": str(bucket_key),
                "wall_clock_ms": wall_ms,
                "sum_duration_ms": sum_ms,
                "span_count": len(durations),
                "p50_ms": _percentile(sorted_durs, 0.5),
                "p95_ms": _percentile(sorted_durs, 0.95),
                "max_ms": sorted_durs[-1] if sorted_durs else 0,
                "pct_of_total": round(pct, 2),
            })

    _build_rows("category", by_category, category_intervals)
    _build_rows("activity", by_activity, activity_intervals)
    _build_rows("phase", by_phase)
    _build_rows("turn", by_turn, turn_intervals)
    _build_rows("tool_type", by_tool_type)

    await latency_repo.insert_batch(job_id=job_id, rows=rows)

    # Compute summary-level latency fields
    llm_sum = sum(by_category.get("llm", []))
    tool_sum = sum(by_category.get("tool", []))
    idle_ms = max(0, total_duration_ms - _compute_wall_clock(
        [iv for ivs in category_intervals.values() for iv in ivs]
    ))
    parallelism_ratio = (
        total_span_sum_ms / total_duration_ms if total_duration_ms > 0 else 0.0
    )

    # Update summary columns
    from sqlalchemy import text as sa_text

    await session.execute(
        sa_text("""
            UPDATE job_telemetry_summary
            SET llm_wait_ms = :llm_wait_ms,
                tool_exec_ms = :tool_exec_ms,
                idle_ms = :idle_ms,
                parallelism_ratio = :parallelism_ratio
            WHERE job_id = :job_id
        """),
        {
            "job_id": job_id,
            "llm_wait_ms": llm_sum,
            "tool_exec_ms": tool_sum,
            "idle_ms": idle_ms,
            "parallelism_ratio": round(parallelism_ratio, 3),
        },
    )
    await session.flush()

    log.info(
        "latency_attribution_written",
        job_id=job_id,
        category_buckets=len(by_category),
        turn_buckets=len(by_turn),
        total_duration_ms=total_duration_ms,
        idle_ms=idle_ms,
        parallelism_ratio=round(parallelism_ratio, 3),
    )
