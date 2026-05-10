"""Post-job cost attribution pipeline.

Runs after a job completes to compute cost breakdowns by dimension
(phase, tool category, turn) and write them to the attribution table.
Also computes derived summary stats (turn economics, file I/O waste,
intent-refined activity classification, and edit one-shot rate).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypedDict

import structlog
from sqlalchemy.exc import DBAPIError

from backend.models.api_schemas import ExecutionPhase
from backend.services.tool_classifier import classify_shell_command, classify_tool

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.models.domain import TelemetrySpanRow
    from backend.persistence.cost_attribution_repo import CostAttributionRepository
    from backend.persistence.file_access_repo import FileAccessRepository
    from backend.persistence.file_cost_repo import FileCostRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
    from backend.persistence.trail_repo import TrailNodeRepository

log = structlog.get_logger()


class CostBucket(TypedDict):
    """Aggregated cost metrics for a single attribution dimension."""

    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    call_count: int


class TurnContext(TypedDict):
    """Per-turn cost context including phase and tool breakdown."""

    phase: str | None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
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


def _classify_turn_intent(context: TurnContext) -> str:
    """Assign a single dominant activity to a turn based on its tools.

    Uses a priority ladder: the highest-value action wins the whole turn.
    """
    cats = set(context.get("tool_categories", []))
    shell_cmds = context.get("shell_commands", [])

    # Classify each shell command individually
    shell_intents: set[str] = set()
    for cmd in shell_cmds:
        shell_intents.add(classify_shell_command(cmd))

    has_writes = bool(cats & {"file_write"})
    has_git = bool(cats & {"git_write", "git_read"})
    has_reads = bool(cats & {"file_read"})
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

    # Priority 3: Git operations (commit, push, diff, status — dedicated tools or shell)
    if "git_ops" in shell_intents or has_git:
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


# ---------------------------------------------------------------------------
# Sub-classification: implementation → feature_dev / refactoring / debugging
# Adapted from CodeBurn's refineByKeywords first-match-position approach.
# ---------------------------------------------------------------------------

import re as _re

_FEATURE_RE = _re.compile(
    r"\b(add|create|implement|new|build|feature|introduce|support|enable)\b",
    _re.IGNORECASE,
)
_DEBUG_RE = _re.compile(
    r"\b(fix|bug|error|broken|failing|crash|debug|issue|wrong|incorrect)\b",
    _re.IGNORECASE,
)
_REFACTOR_RE = _re.compile(
    r"\b(refactor|clean\s*up|rename|reorganize|simplify|restructure|extract|deduplicate)\b",
    _re.IGNORECASE,
)

_SUB_CLASSIFIERS = [
    ("refactoring", _REFACTOR_RE),
    ("debugging", _DEBUG_RE),
    ("feature_dev", _FEATURE_RE),
]


def _sub_classify_implementation(description: str | None, motivation: str | None) -> str:
    """Sub-classify 'implementation' into feature_dev / debugging / refactoring.

    Uses CodeBurn's first-match-position approach: find the earliest regex
    match across all candidates; tie-break by candidate order (refactoring
    wins ties over debugging, debugging over feature_dev).
    """
    text = (description or "") + " " + (motivation or "")
    if not text.strip():
        return "implementation"

    best_pos = len(text) + 1
    best_label = "implementation"

    for label, pattern in _SUB_CLASSIFIERS:
        m = pattern.search(text)
        if m and m.start() < best_pos:
            best_pos = m.start()
            best_label = label

    return best_label


def _classify_motivation(
    turn_num: int,
    trail_nodes: list[dict],
    turn_context: TurnContext,
) -> str:
    """Classify a turn's motivation from trail node metadata (Item 17)."""
    nodes = [n for n in trail_nodes if n.get("turn_number") == turn_num]

    # Priority 1: Error recovery — is_retry or error_kind present
    if any(n.get("is_retry") or n.get("error_kind") for n in nodes):
        return "error_recovery"

    # Priority 2: Test-driven — shell commands include test runners
    shell_cmds = turn_context.get("shell_commands", [])
    if any(classify_shell_command(cmd) == "verification" for cmd in shell_cmds):
        return "test_driven_iteration"

    # Priority 3: Plan execution — trail node has plan_item_id
    if any(n.get("plan_item_id") for n in nodes):
        return "plan_execution"

    # Priority 4: User-directed — first turn or immediately after user message
    if turn_num <= 1:
        return "user_directed"

    # Priority 5: Context gathering — turn is pure reads, no writes
    cats = set(turn_context.get("tool_categories", []))
    if cats and not (cats & {"file_write", "git_write"}):
        return "context_gathering"

    # Default: agent exploration
    return "agent_exploration"


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
    from backend.persistence.file_cost_repo import FileCostRepository
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
        file_cost_repo=FileCostRepository(session),
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
    file_cost_repo: FileCostRepository,
    session: AsyncSession,
    trail_repo: TrailNodeRepository | None = None,
) -> None:
    """Core attribution logic with explicit dependencies."""

    spans = await spans_repo.list_for_job(job_id)
    if not spans:
        log.info("cost_attribution_skip_no_spans", job_id=job_id)
        return

    # --- Load job metadata for sub-classification and model tagging ---
    from sqlalchemy import text as sa_text

    job_meta = await session.execute(
        sa_text(
            "SELECT j.description, "
            "COALESCE(t.model, '') AS model "
            "FROM jobs j "
            "LEFT JOIN job_telemetry_summary t ON t.job_id = j.id "
            "WHERE j.id = :jid"
        ),
        {"jid": job_id},
    )
    job_row = job_meta.mappings().first()
    job_description = (job_row or {}).get("description")
    job_model = (job_row or {}).get("model", "") or ""

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
        cache_r = span.get("cache_read_tokens") or 0
        cache_w = span.get("cache_write_tokens") or 0

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
            _accumulate(by_turn[turn], cost, in_tok, out_tok, cache_read=cache_r, cache_write=cache_w)
            turn_contexts[int(turn)]["cost_usd"] += float(cost or 0)
            turn_contexts[int(turn)]["input_tokens"] += int(in_tok or 0)
            turn_contexts[int(turn)]["output_tokens"] += int(out_tok or 0)
            turn_contexts[int(turn)]["cache_read_tokens"] += int(cache_r or 0)
            turn_contexts[int(turn)]["cache_write_tokens"] += int(cache_w or 0)

    # --- One-shot rate tracking ---
    # Track edit→shell→edit retry patterns per turn, aggregated by activity.
    one_shot_by_activity: dict[str, dict[str, int]] = defaultdict(
        lambda: {"edit_turns": 0, "one_shot_turns": 0, "retries": 0}
    )

    for _turn_num, context in turn_contexts.items():
        # Single dominant intent per turn — no splitting
        activity = _classify_turn_intent(context)

        # Sub-classify implementation turns using job description/motivation
        if activity == "implementation":
            activity = _sub_classify_implementation(job_description, None)

        turn_cost = float(context.get("cost_usd", 0.0) or 0.0)
        turn_in = int(context.get("input_tokens", 0) or 0)
        turn_out = int(context.get("output_tokens", 0) or 0)
        turn_cache_r = int(context.get("cache_read_tokens", 0) or 0)
        turn_cache_w = int(context.get("cache_write_tokens", 0) or 0)

        # Whole turn attributed to a single activity
        _accumulate(by_activity[activity], turn_cost, turn_in, turn_out, cache_read=turn_cache_r, cache_write=turn_cache_w, call_count=1)

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
            _accumulate(by_phase[phase], turn_cost, turn_in, turn_out, cache_read=turn_cache_r, cache_write=turn_cache_w)

        # Activity×Phase compound dimension — cross-reference for inline phase
        # bars in the unified cost view.  Bucket format: "activity:phase".
        if phase:
            compound_key = f"{activity}:{phase}"
            _accumulate(
                by_activity_phase[compound_key],
                turn_cost,
                turn_in,
                turn_out,
                cache_read=turn_cache_r,
                cache_write=turn_cache_w,
                call_count=1,
            )

    # --- Motivation dimension (Item 17) ---
    trail_list: list[dict] = []
    try:
        if trail_repo is not None:
            trail_nodes = await trail_repo.get_by_job(job_id, limit=1000)
            trail_list = [
                {
                    "turn_number": getattr(n, "turn_number", None) or getattr(n, "anchor_seq", None),
                    "is_retry": getattr(n, "is_retry", False),
                    "error_kind": getattr(n, "error_kind", None),
                    "plan_item_id": getattr(n, "plan_item_id", None),
                }
                for n in trail_nodes
            ]
    except Exception:
        log.debug("cost_attribution_trail_fetch_failed", job_id=job_id, exc_info=True)

    by_motivation: dict[str, CostBucket] = defaultdict(lambda: _zero_bucket())
    for turn_num_m, context_m in turn_contexts.items():
        motivation = _classify_motivation(turn_num_m, trail_list, context_m)
        turn_cost_m = float(context_m.get("cost_usd", 0.0) or 0.0)
        turn_in_m = int(context_m.get("input_tokens", 0) or 0)
        turn_out_m = int(context_m.get("output_tokens", 0) or 0)
        turn_cache_r_m = int(context_m.get("cache_read_tokens", 0) or 0)
        turn_cache_w_m = int(context_m.get("cache_write_tokens", 0) or 0)
        _accumulate(
            by_motivation[motivation], turn_cost_m, turn_in_m, turn_out_m,
            cache_read=turn_cache_r_m, cache_write=turn_cache_w_m, call_count=1,
        )

    # --- Write attribution rows ---
    rows: list[dict[str, Any]] = []
    for bucket, data in by_activity.items():
        rows.append({"dimension": "activity", "bucket": bucket, "model": job_model, **data})
    for turn_num, data in sorted(by_turn.items()):
        rows.append({"dimension": "turn", "bucket": str(turn_num), "model": job_model, **data})
    for phase_name, data in by_phase.items():
        rows.append({"dimension": "phase", "bucket": phase_name, "model": job_model, **data})
    for compound_key, data in by_activity_phase.items():
        rows.append({"dimension": "activity_phase", "bucket": compound_key, "model": job_model, **data})
    for motivation_bucket, mdata in by_motivation.items():
        rows.append({"dimension": "motivation", "bucket": motivation_bucket, "model": job_model, **mdata})
    # One-shot rate rows (dimension="edit_efficiency")
    for activity_bucket, stats in one_shot_by_activity.items():
        if stats["edit_turns"] > 0:
            rows.append(
                {
                    "dimension": "edit_efficiency",
                    "bucket": activity_bucket,
                    "model": job_model,
                    "cost_usd": 0.0,
                    "input_tokens": stats["one_shot_turns"],
                    "output_tokens": stats["retries"],
                    "call_count": stats["edit_turns"],
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                }
            )

    await attr_repo.insert_batch(job_id=job_id, rows=rows)
    log.info(
        "cost_attribution_written",
        job_id=job_id,
        activity_buckets=len(by_activity),
        turn_buckets=len(by_turn),
        phase_buckets=len(by_phase),
        activity_phase_buckets=len(by_activity_phase),
        motivation_buckets=len(by_motivation),
        spans_missing_phase=spans_missing_phase,
    )

    # --- File-centric cost attribution (Item 14) ---
    try:
        file_access_rows = await file_repo.raw_accesses_for_job(job_id)
        if file_access_rows:
            files_by_turn: dict[int, list[dict]] = defaultdict(list)
            for fa in file_access_rows:
                turn = fa.get("turn_number")
                if turn is not None:
                    files_by_turn[int(turn)].append(fa)

            file_costs: dict[str, dict] = defaultdict(
                lambda: {"cost_usd": 0.0, "read_cost": 0.0, "write_cost": 0.0, "turn_count": 0}
            )
            for turn_num_f, turn_files in files_by_turn.items():
                turn_cost_f = float(by_turn.get(turn_num_f, _zero_bucket())["cost_usd"])
                if turn_cost_f <= 0 or not turn_files:
                    continue
                unique_files = set(f["file_path"] for f in turn_files)
                share = turn_cost_f / len(unique_files)
                seen_files: set[str] = set()
                for fa in turn_files:
                    fp = fa["file_path"]
                    if fp not in seen_files:
                        seen_files.add(fp)
                        file_costs[fp]["cost_usd"] += share
                        if fa.get("access_type") == "read":
                            file_costs[fp]["read_cost"] += share
                        else:
                            file_costs[fp]["write_cost"] += share
                        file_costs[fp]["turn_count"] += 1

            if file_costs:
                await file_cost_repo.insert_batch(
                    job_id=job_id,
                    rows=[{"file_path": fp, **data} for fp, data in file_costs.items()],
                )
    except Exception:
        log.debug("file_cost_attribution_failed", job_id=job_id, exc_info=True)

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
    return {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "call_count": 0,
    }


def _zero_turn_context() -> TurnContext:
    return {
        "phase": None,
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "tool_categories": [],
        "shell_commands": [],
    }


def _infer_execution_phases(spans: list[dict[str, Any]] | list[TelemetrySpanRow]) -> list[str | None]:
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


def _accumulate(
    bucket: CostBucket,
    cost: float,
    in_tok: int,
    out_tok: int,
    *,
    cache_read: int = 0,
    cache_write: int = 0,
    call_count: int = 1,
) -> None:
    bucket["cost_usd"] += float(cost or 0)
    bucket["input_tokens"] += int(in_tok or 0)
    bucket["output_tokens"] += int(out_tok or 0)
    bucket["cache_read_tokens"] += int(cache_read or 0)
    bucket["cache_write_tokens"] += int(cache_write or 0)
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
