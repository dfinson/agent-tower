"""Post-job cost attribution pipeline.

Runs after a job completes to compute cost breakdowns by dimension
(phase, tool category, turn) and write them to the attribution table.
Also computes derived summary stats (turn economics, file I/O waste,
intent-refined activity classification, and edit one-shot rate).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypedDict

import structlog
from sqlalchemy.exc import DBAPIError

from backend.models.api_schemas import ExecutionPhase
from backend.services.tool_classifier import classify_tool

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.persistence.cost_attribution_repo import CostAttributionRepository
    from backend.persistence.file_access_repo import FileAccessRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

log = structlog.get_logger()


class CostBucket(TypedDict):
    """Aggregated cost metrics for a single attribution dimension."""

    cost_usd: float
    input_tokens: int
    output_tokens: int
    call_count: int


class TurnContext(TypedDict):
    """Per-turn cost context including phase and tool breakdown."""

    phase: str | None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    tool_categories: list[str]

_TOOL_CATEGORY_TO_ACTIVITY = {
    "file_write": "code_changes",
    "git_write": "code_changes",
    "git_read": "code_reading",
    "file_read": "code_reading",
    "file_search": "search_discovery",
    "browser": "search_discovery",
    "shell": "command_execution",
    "agent": "delegation",
    "thinking": "reasoning",
    "bookkeeping": "bookkeeping",
    "other": "other_tools",
}

# ---------------------------------------------------------------------------
# Keyword-based intent classification (adapted from CodeBurn, MIT license)
# ---------------------------------------------------------------------------

_RE_DEBUG = re.compile(
    r"\b(fix|bug|error|broken|failing|crash|issue|debug|traceback|exception|"
    r"stack\s*trace|not\s+working|wrong|unexpected)\b",
    re.IGNORECASE,
)
_RE_FEATURE = re.compile(
    r"\b(add|create|implement|new|build|feature|introduce|set\s*up|scaffold|generate)\b",
    re.IGNORECASE,
)
_RE_REFACTOR = re.compile(
    r"\b(refactor|clean\s*up|rename|reorganize|simplify|extract|restructure|move|migrate|split)\b",
    re.IGNORECASE,
)
_RE_TEST = re.compile(
    r"\b(test|pytest|vitest|jest|mocha|spec|coverage|npm\s+test|npx\s+vitest|npx\s+jest)\b",
    re.IGNORECASE,
)
_RE_GIT = re.compile(
    r"\bgit\s+(push|pull|commit|merge|rebase|checkout|branch|stash|tag|cherry-pick)\b",
    re.IGNORECASE,
)
_RE_BUILD = re.compile(
    r"\b(npm\s+run\s+build|npm\s+publish|pip\s+install|docker|deploy|make\s+build|"
    r"npm\s+run\s+dev|npm\s+start|cargo\s+build|brew\s+install|apt\s+install)\b",
    re.IGNORECASE,
)

# Categories that shell commands can refine into
_SHELL_TOOL_CATEGORIES = {"shell"}
# Categories that file-write tools can refine into
_WRITE_TOOL_CATEGORIES = {"file_write", "git_write"}


def _refine_activity_by_intent(
    activity: str,
    tool_categories: list[str],
    prompt: str,
) -> str:
    """Refine a coarse activity label using keyword matching on the job prompt.

    Only refines ``code_changes`` and ``command_execution`` — the two coarse
    buckets that benefit most from intent disambiguation.
    """
    if not prompt:
        return activity

    has_writes = any(c in _WRITE_TOOL_CATEGORIES for c in tool_categories)
    has_shell = any(c in _SHELL_TOOL_CATEGORIES for c in tool_categories)

    if activity == "command_execution" and has_shell:
        if _RE_TEST.search(prompt):
            return "testing"
        if _RE_GIT.search(prompt):
            return "git_ops"
        if _RE_BUILD.search(prompt):
            return "build_deploy"

    if activity == "code_changes" and has_writes:
        if _RE_DEBUG.search(prompt):
            return "debugging"
        if _RE_REFACTOR.search(prompt):
            return "refactoring"
        if _RE_FEATURE.search(prompt):
            return "feature_dev"
        if _RE_TEST.search(prompt):
            return "testing"

    return activity


async def compute_attribution(session: AsyncSession, job_id: str) -> None:
    """Compute and store cost attribution for a completed job.

    Reads all spans for the job, aggregates by dimension, writes
    attribution rows, and updates summary turn stats.  Uses keyword-based
    intent analysis on the job prompt to refine coarse activity buckets
    (e.g. ``code_changes`` → ``debugging``, ``refactoring``, ``feature_dev``).
    Also detects edit→shell→edit retry loops for one-shot rate computation.
    """
    from backend.persistence.cost_attribution_repo import CostAttributionRepository
    from backend.persistence.file_access_repo import FileAccessRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

    await _compute_attribution(
        job_id=job_id,
        spans_repo=TelemetrySpansRepository(session),
        attr_repo=CostAttributionRepository(session),
        summary_repo=TelemetrySummaryRepository(session),
        file_repo=FileAccessRepository(session),
        session=session,
    )


async def _compute_attribution(
    *,
    job_id: str,
    spans_repo: TelemetrySpansRepository,
    attr_repo: CostAttributionRepository,
    summary_repo: TelemetrySummaryRepository,
    file_repo: FileAccessRepository,
    session: AsyncSession,
) -> None:
    """Core attribution logic with explicit dependencies."""

    spans = await spans_repo.list_for_job(job_id)
    if not spans:
        log.info("cost_attribution_skip_no_spans", job_id=job_id)
        return

    # Fetch job prompt for keyword-based intent classification
    job_prompt = ""
    try:
        from sqlalchemy import text as sa_text

        result = await session.execute(
            sa_text("SELECT prompt FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        )
        row = result.mappings().first()
        if row:
            job_prompt = row.get("prompt", "") or ""
    except (DBAPIError, KeyError):
        log.warning("cost_attribution_prompt_fetch_failed", job_id=job_id, exc_info=True)

    # --- Aggregate by dimension ---
    by_activity: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
    by_turn: dict[int, CostBucket] = defaultdict(lambda: _zero_bucket())
    by_phase: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
    turn_contexts: dict[int, TurnContext] = defaultdict(_zero_turn_context)
    normalized_phases = _infer_execution_phases(spans)
    spans_missing_phase = 0

    for span, phase in zip(spans, normalized_phases, strict=False):
        attrs = span.get("attrs", {})
        cost = span.get("cost_usd") or attrs.get("cost", 0.0)
        in_tok = span.get("input_tokens") or attrs.get("input_tokens", 0)
        out_tok = span.get("output_tokens") or attrs.get("output_tokens", 0)

        if phase is not None:
            turn = span.get("turn_number")
            if turn is not None:
                turn_contexts[int(turn)]["phase"] = phase
        else:
            spans_missing_phase += 1

        if span.get("span_type") == "tool":
            cat = classify_tool(span.get("name") or "") or "other"
            turn = span.get("turn_number")
            if turn is not None:
                turn_contexts[int(turn)]["tool_categories"].append(cat)

        # Turn dimension (LLM spans carry the cost)
        turn = span.get("turn_number")
        if turn is not None and span.get("span_type") == "llm":
            _accumulate(by_turn[turn], cost, in_tok, out_tok)
            turn_contexts[int(turn)]["cost_usd"] += float(cost or 0)
            turn_contexts[int(turn)]["input_tokens"] += int(in_tok or 0)
            turn_contexts[int(turn)]["output_tokens"] += int(out_tok or 0)

    # --- One-shot rate tracking ---
    # Track edit→shell→edit retry patterns per turn, aggregated by activity.
    one_shot_by_activity: dict[str, dict[str, int]] = defaultdict(
        lambda: {"edit_turns": 0, "one_shot_turns": 0, "retries": 0}
    )

    for _turn_num, context in turn_contexts.items():
        weights = _derive_activity_weights(
            phase=context.get("phase"),
            tool_categories=context.get("tool_categories", []),
            output_tokens=context.get("output_tokens", 0),
        )
        if not weights:
            continue

        # Apply keyword-based intent refinement
        refined_weights: dict[str, int] = {}
        tool_cats = context.get("tool_categories", [])
        for raw_bucket, weight in weights.items():
            refined = _refine_activity_by_intent(raw_bucket, tool_cats, job_prompt)
            refined_weights[refined] = refined_weights.get(refined, 0) + weight

        turn_cost = float(context.get("cost_usd", 0.0) or 0.0)
        turn_in = int(context.get("input_tokens", 0) or 0)
        turn_out = int(context.get("output_tokens", 0) or 0)

        allocations = _allocate_weighted_totals(
            weights=refined_weights,
            cost_usd=turn_cost,
            input_tokens=turn_in,
            output_tokens=turn_out,
        )
        for bucket, allocated in allocations.items():
            _accumulate(
                by_activity[bucket],
                float(allocated["cost_usd"]),
                int(allocated["input_tokens"]),
                int(allocated["output_tokens"]),
                call_count=1,
            )

        # One-shot detection: does this turn have file_write tools?
        has_edits = any(c in _WRITE_TOOL_CATEGORIES for c in tool_cats)
        if has_edits:
            retries = _count_edit_retries(context.get("tool_categories", []))
            # Attribute to the dominant refined activity
            dominant = max(refined_weights, key=lambda k: refined_weights[k])
            one_shot_by_activity[dominant]["edit_turns"] += 1
            one_shot_by_activity[dominant]["retries"] += retries
            if retries == 0:
                one_shot_by_activity[dominant]["one_shot_turns"] += 1

        # Phase dimension — aggregate by execution phase
        phase = context.get("phase")
        if phase:
            _accumulate(by_phase[phase], turn_cost, turn_in, turn_out)

    # --- Write attribution rows ---
    rows: list[dict[str, Any]] = []
    for bucket, data in by_activity.items():
        rows.append({"dimension": "activity", "bucket": bucket, **data})
    for turn_num, data in sorted(by_turn.items()):
        rows.append({"dimension": "turn", "bucket": str(turn_num), **data})
    for phase_name, data in by_phase.items():
        rows.append({"dimension": "phase", "bucket": phase_name, **data})
    # One-shot rate rows (dimension="edit_efficiency")
    for activity_bucket, stats in one_shot_by_activity.items():
        if stats["edit_turns"] > 0:
            rows.append({
                "dimension": "edit_efficiency",
                "bucket": activity_bucket,
                "cost_usd": 0.0,
                "input_tokens": stats["one_shot_turns"],
                "output_tokens": stats["retries"],
                "call_count": stats["edit_turns"],
            })

    await attr_repo.insert_batch(job_id=job_id, rows=rows)
    log.info(
        "cost_attribution_written",
        job_id=job_id,
        activity_buckets=len(by_activity),
        turn_buckets=len(by_turn),
        phase_buckets=len(by_phase),
        spans_missing_phase=spans_missing_phase,
    )

    # --- Compute turn economics for summary ---
    turn_costs = [d["cost_usd"] for d in by_turn.values()]
    total_turns = len(turn_costs)
    if total_turns > 0:
        peak = max(turn_costs)
        avg = sum(turn_costs) / total_turns
        sorted_turns = sorted(by_turn.keys())
        mid = total_turns // 2
        first_half = sum(by_turn[t]["cost_usd"] for t in sorted_turns[:mid])
        second_half = sum(by_turn[t]["cost_usd"] for t in sorted_turns[mid:])
    else:
        peak = avg = first_half = second_half = 0.0

    # --- File I/O stats ---
    file_stats = await file_repo.reread_stats(job_id)

    # --- Diff line counts from trail nodes (step boundaries with SHA refs) ---
    diff_added = 0
    diff_removed = 0
    try:
        from sqlalchemy import text as sa_text

        # Get the latest step node with file data for this job
        result = await session.execute(
            sa_text(
                "SELECT files FROM trail_nodes "
                "WHERE job_id = :job_id AND files IS NOT NULL "
                "ORDER BY seq DESC LIMIT 1"
            ),
            {"job_id": job_id},
        )
        row = result.mappings().first()
        if row and row.get("files"):
            import json as _json

            files_data = _json.loads(row["files"])
            for f in files_data:
                if isinstance(f, dict):
                    diff_added += f.get("additions", 0)
                    diff_removed += f.get("deletions", 0)
    except (DBAPIError, KeyError, ValueError):
        log.warning("diff_lines_extraction_failed", job_id=job_id, exc_info=True)

    await summary_repo.set_turn_stats(
        job_id,
        unique_files_read=file_stats.get("unique_files", 0),
        file_reread_count=file_stats.get("reread_count", 0),
        peak_turn_cost_usd=peak,
        avg_turn_cost_usd=avg,
        cost_first_half_usd=first_half,
        cost_second_half_usd=second_half,
        diff_lines_added=diff_added,
        diff_lines_removed=diff_removed,
    )

    log.info(
        "cost_attribution_summary_updated",
        job_id=job_id,
        total_turns=total_turns,
        peak_turn_cost=round(peak, 6),
        rerereads=file_stats.get("reread_count", 0),
    )


def _zero_bucket() -> CostBucket:
    return {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "call_count": 0}


def _zero_turn_context() -> TurnContext:
    return {"phase": None, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "tool_categories": []}


def _infer_execution_phases(spans: list[dict[str, Any]]) -> list[str | None]:
    valid_phases = {phase.value for phase in ExecutionPhase}
    inferred: list[str | None] = []

    last_known: str | None = None
    for span in spans:
        raw_phase = span.get("execution_phase")
        phase = raw_phase if raw_phase in valid_phases else None
        if phase is None:
            phase = last_known
        else:
            last_known = phase
        inferred.append(phase)

    next_known: str | None = None
    for index in range(len(spans) - 1, -1, -1):
        raw_phase = spans[index].get("execution_phase")
        if raw_phase in valid_phases:
            next_known = raw_phase
        elif inferred[index] is None and next_known is not None:
            inferred[index] = next_known

    return inferred


def _derive_activity_weights(
    *,
    phase: str | None,
    tool_categories: list[str],
    output_tokens: int = 0,
) -> dict[str, int]:
    # Always derive activity from actual tool usage, regardless of phase.
    # The phase dimension (verification, setup, wrap_up) is tracked separately
    # via the phase-dimension attribution rows — collapsing all activity into
    # a single phase bucket makes the activity breakdown useless for those phases.
    weights: dict[str, int] = {}
    for category in tool_categories:
        activity = _TOOL_CATEGORY_TO_ACTIVITY.get(category, "other_tools")
        weights[activity] = weights.get(activity, 0) + 1

    if not weights:
        # Zero tool calls — the agent spent this turn composing a message to
        # the user (output_tokens > 0) or doing internal reasoning.  Explicit
        # thinking tool calls (Think, Computer) already land in the "reasoning"
        # bucket above, so a zero-tool turn with output is user communication.
        if output_tokens > 0:
            return {"user_communication": 1}
        return {"reasoning": 1}
    return weights


def _allocate_weighted_totals(
    *,
    weights: dict[str, int],
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, dict[str, float | int]]:
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {}

    allocations: dict[str, dict[str, float | int]] = {}
    remaining_cost = float(cost_usd)
    remaining_input = int(input_tokens)
    remaining_output = int(output_tokens)
    items = list(weights.items())
    for index, (bucket, weight) in enumerate(items):
        is_last = index == len(items) - 1
        if is_last:
            alloc_cost = remaining_cost
            alloc_input = remaining_input
            alloc_output = remaining_output
        else:
            share = weight / total_weight
            alloc_cost = cost_usd * share
            alloc_input = int(input_tokens * share)
            alloc_output = int(output_tokens * share)
            remaining_cost -= alloc_cost
            remaining_input -= alloc_input
            remaining_output -= alloc_output
        allocations[bucket] = {
            "cost_usd": alloc_cost,
            "input_tokens": alloc_input,
            "output_tokens": alloc_output,
        }

    return allocations


def _accumulate(bucket: CostBucket, cost: float, in_tok: int, out_tok: int, *, call_count: int = 1) -> None:
    bucket["cost_usd"] += float(cost or 0)
    bucket["input_tokens"] += int(in_tok or 0)
    bucket["output_tokens"] += int(out_tok or 0)
    bucket["call_count"] += int(call_count or 0)


def _count_edit_retries(tool_categories: list[str]) -> int:
    """Detect edit→shell→edit retry loops in a turn's tool sequence.

    Walks the tool category sequence looking for the pattern:
    file_write → shell → file_write (agent edited, ran test/build, had to edit again).
    Each occurrence of this pattern counts as one retry.

    Adapted from CodeBurn's ``countRetries`` (MIT license).
    """
    saw_edit = False
    saw_shell_after_edit = False
    retries = 0

    for cat in tool_categories:
        is_edit = cat in _WRITE_TOOL_CATEGORIES
        is_shell = cat == "shell"

        if is_edit:
            if saw_shell_after_edit:
                retries += 1
            saw_edit = True
            saw_shell_after_edit = False
        if is_shell and saw_edit:
            saw_shell_after_edit = True

    return retries
