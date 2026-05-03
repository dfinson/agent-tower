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
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.persistence.cost_attribution_repo import CostAttributionRepository
    from backend.persistence.file_access_repo import FileAccessRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
    from backend.persistence.trail_repo import TrailNodeRepository

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
    shell_commands: list[str]


# ---------------------------------------------------------------------------
# Intent-based turn classification
#
# Each turn gets ONE activity label based on its highest-priority action.
# Priority: implementation > verification > git_ops > setup > investigation
#           > delegation > overhead > reasoning > communication
#
# Shell commands are classified by their actual content, not the job prompt.
# ---------------------------------------------------------------------------

# Categories that represent file-write actions
_WRITE_TOOL_CATEGORIES = {"file_write", "git_write"}

# Shell command patterns — matched against actual commands, not job prompt
_RE_SHELL_TEST = re.compile(
    r"\b(pytest|vitest|jest|mocha|npm\s+test|npx\s+vitest|npx\s+jest|"
    r"cargo\s+test|go\s+test|rspec|phpunit|unittest|npm\s+run\s+test)\b",
    re.IGNORECASE,
)
_RE_SHELL_GIT_WRITE = re.compile(
    r"\bgit\s+(add|commit|push|merge|rebase|checkout|cherry-pick|stash|tag|reset)\b",
    re.IGNORECASE,
)
_RE_SHELL_GIT_READ = re.compile(
    r"\bgit\s+(diff|log|status|show|blame|branch)\b",
    re.IGNORECASE,
)
_RE_SHELL_SETUP = re.compile(
    r"\b(uv\s+sync|uv\s+add|pip\s+install|npm\s+install|npm\s+ci|"
    r"yarn\s+install|cargo\s+build|make\s+build|docker|deploy|"
    r"brew\s+install|apt\s+install|apt-get\s+install)\b",
    re.IGNORECASE,
)
_RE_SHELL_INVESTIGATE = re.compile(
    r"\b(find|ls|cat|head|tail|wc|tree|du|file)\b",
    re.IGNORECASE,
)


def _classify_shell_command(cmd: str) -> str:
    """Classify a shell command string into a tool-level intent."""
    if _RE_SHELL_TEST.search(cmd):
        return "verification"
    if _RE_SHELL_GIT_WRITE.search(cmd):
        return "git_ops"
    if _RE_SHELL_SETUP.search(cmd):
        return "setup"
    if _RE_SHELL_GIT_READ.search(cmd):
        return "investigation"
    if _RE_SHELL_INVESTIGATE.search(cmd):
        return "investigation"
    # Unclassified shell — falls through to turn-level logic
    return "shell_other"


def _classify_turn_intent(context: TurnContext) -> str:
    """Assign a single dominant activity to a turn based on its tools.

    Uses a priority ladder: the highest-value action wins the whole turn.
    """
    cats = set(context.get("tool_categories", []))
    shell_cmds = context.get("shell_commands", [])

    # Classify each shell command individually
    shell_intents: set[str] = set()
    for cmd in shell_cmds:
        shell_intents.add(_classify_shell_command(cmd))

    has_writes = bool(cats & _WRITE_TOOL_CATEGORIES)
    has_reads = bool(cats & {"file_read", "git_read"})
    has_search = bool(cats & {"file_search", "browser"})
    has_bookkeeping = "bookkeeping" in cats
    has_thinking = "thinking" in cats
    has_delegation = "agent" in cats

    # Priority 1: If the agent edited files, this is an implementation turn
    if has_writes:
        return "implementation"

    # Priority 2: If the agent ran tests, this is verification
    if "verification" in shell_intents:
        return "verification"

    # Priority 3: Git write operations (commit, push, merge)
    if "git_ops" in shell_intents:
        return "git_ops"

    # Priority 4: Setup/install commands
    if "setup" in shell_intents:
        return "setup"

    # Priority 5: Delegation to sub-agents
    if has_delegation:
        return "delegation"

    # Priority 6: Investigation — reading, searching, browsing, git diff/log
    if has_reads or has_search or "investigation" in shell_intents:
        return "investigation"

    # Priority 7: Unclassified shell commands (arbitrary bash)
    if "shell_other" in shell_intents:
        return "investigation"  # conservative: unknown bash is probably exploration

    # Priority 8: Pure overhead — only bookkeeping tools, no real work
    if has_bookkeeping:
        return "overhead"

    # Priority 9: Reasoning — only Think tool
    if has_thinking:
        return "reasoning"

    # No tools at all — user communication or reasoning
    out_tok = context.get("output_tokens", 0) or 0
    if out_tok > 0:
        return "communication"
    return "reasoning"


async def compute_attribution(
    session: AsyncSession,
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
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

    trail_repo = None
    if session_factory is not None:
        from backend.persistence.trail_repo import TrailNodeRepository

        trail_repo = TrailNodeRepository(session_factory)

    await _compute_attribution(
        job_id=job_id,
        spans_repo=TelemetrySpansRepository(session),
        attr_repo=CostAttributionRepository(session),
        summary_repo=TelemetrySummaryRepository(session),
        file_repo=FileAccessRepository(session),
        session=session,
        trail_repo=trail_repo,
    )


async def _compute_attribution(
    *,
    job_id: str,
    spans_repo: TelemetrySpansRepository,
    attr_repo: CostAttributionRepository,
    summary_repo: TelemetrySummaryRepository,
    file_repo: FileAccessRepository,
    session: AsyncSession,
    trail_repo: TrailNodeRepository | None = None,
) -> None:
    """Core attribution logic with explicit dependencies."""

    spans = await spans_repo.list_for_job(job_id)
    if not spans:
        log.info("cost_attribution_skip_no_spans", job_id=job_id)
        return

    # --- Aggregate by dimension ---
    by_activity: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
    by_turn: dict[int, CostBucket] = defaultdict(lambda: _zero_bucket())
    by_phase: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
    by_activity_phase: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
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
                # Collect shell command text for intent classification
                if cat == "shell":
                    tool_args = span.get("tool_args_json")
                    if isinstance(tool_args, str):
                        try:
                            import json as _json
                            parsed = _json.loads(tool_args)
                            cmd = parsed.get("command", "") or parsed.get("cmd", "")
                        except (ValueError, TypeError):
                            cmd = ""
                    elif isinstance(tool_args, dict):
                        cmd = tool_args.get("command", "") or tool_args.get("cmd", "")
                    else:
                        cmd = ""
                    if cmd:
                        turn_contexts[int(turn)]["shell_commands"].append(str(cmd))

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
        # Single dominant intent per turn — no splitting
        activity = _classify_turn_intent(context)

        turn_cost = float(context.get("cost_usd", 0.0) or 0.0)
        turn_in = int(context.get("input_tokens", 0) or 0)
        turn_out = int(context.get("output_tokens", 0) or 0)

        # Whole turn attributed to a single activity
        _accumulate(by_activity[activity], turn_cost, turn_in, turn_out, call_count=1)

        # One-shot detection: does this turn have file_write tools?
        tool_cats = context.get("tool_categories", [])
        has_edits = any(c in _WRITE_TOOL_CATEGORIES for c in tool_cats)
        if has_edits:
            retries = _count_edit_retries(tool_cats)
            one_shot_by_activity[activity]["edit_turns"] += 1
            one_shot_by_activity[activity]["retries"] += retries
            if retries == 0:
                one_shot_by_activity[activity]["one_shot_turns"] += 1

        # Phase dimension — aggregate by execution phase
        phase = context.get("phase")
        if phase:
            _accumulate(by_phase[phase], turn_cost, turn_in, turn_out)

        # Activity×Phase compound dimension — cross-reference for inline phase
        # bars in the unified cost view.  Bucket format: "activity:phase".
        if phase:
            compound_key = f"{activity}:{phase}"
            _accumulate(
                by_activity_phase[compound_key],
                turn_cost, turn_in, turn_out,
                call_count=1,
            )

    # --- Write attribution rows ---
    rows: list[dict[str, Any]] = []
    for bucket, data in by_activity.items():
        rows.append({"dimension": "activity", "bucket": bucket, **data})
    for turn_num, data in sorted(by_turn.items()):
        rows.append({"dimension": "turn", "bucket": str(turn_num), **data})
    for phase_name, data in by_phase.items():
        rows.append({"dimension": "phase", "bucket": phase_name, **data})
    for compound_key, data in by_activity_phase.items():
        rows.append({"dimension": "activity_phase", "bucket": compound_key, **data})
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
        activity_phase_buckets=len(by_activity_phase),
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

    # --- Diff line counts from trail nodes ---
    diff_added = 0
    diff_removed = 0
    try:
        if trail_repo is not None:
            diff_added, diff_removed = await trail_repo.get_diff_line_counts(job_id)
        else:
            from sqlalchemy import text as sa_text

            result = await session.execute(
                sa_text(
                    "SELECT COALESCE(SUM(diff_additions), 0) AS added, "
                    "COALESCE(SUM(diff_deletions), 0) AS removed "
                    "FROM trail_nodes WHERE job_id = :job_id"
                ),
                {"job_id": job_id},
            )
            row = result.mappings().first()
            if row:
                diff_added = row["added"]
                diff_removed = row["removed"]
    except (DBAPIError, KeyError):
        log.debug("cost_attribution_diff_stats_failed", job_id=job_id, exc_info=True)

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
    return {"phase": None, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "tool_categories": [], "shell_commands": []}


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
