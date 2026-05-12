"""One-off backfill: classify action + purpose for all completed jobs.

Both action and purpose are determined by fast deterministic heuristics —
NO LLM calls needed. Processes 183 jobs in seconds.

Purpose heuristics use a priority ladder applied per-turn:
  1. is_retry / error_kind on trail nodes → recovering
  2. Turn follows a test failure (retry pattern) → recovering
  3. Test execution after writes (same turn or previous turn wrote) → verifying
  4. Only reads/searches, no writes → orienting
  5. Git commit/push or bookkeeping-only tools → housekeeping
  6. Has file_write or non-trivial shell execution → building
  7. Pure LLM reasoning with no tools → orienting

Usage:
    uv run python tools/backfill_attribution.py [--dry-run] [--job-id JOB_ID]

Writes new dimension rows (action, purpose, action_purpose) to
job_cost_attribution. Stores purpose + purpose_source on trail_nodes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.services.tool_classifier import classify_tool, refine_shell_category

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Action classification (deterministic — no LLM)
# ---------------------------------------------------------------------------

_RE_TEST = re.compile(
    r"\b(pytest|vitest|jest|mocha|npm\s+test|npx\s+vitest|npx\s+jest|"
    r"cargo\s+test|go\s+test|rspec|phpunit|unittest|npm\s+run\s+test)\b",
    re.IGNORECASE,
)
_RE_GIT_WRITE = re.compile(
    r"\bgit\s+(add|commit|push|merge|rebase|checkout|cherry-pick|stash|tag|reset)\b",
    re.IGNORECASE,
)
_RE_GIT_READ = re.compile(
    r"\bgit\s+(diff|log|status|show|blame|branch)\b",
    re.IGNORECASE,
)
_RE_READ_SHELL = re.compile(
    r"\b(cat|head|tail|less|more|grep|find|ls|tree|wc|du|stat|file|strings|awk|sed)\b",
    re.IGNORECASE,
)

# Priority ladder for action classification
_ACTION_PRIORITY = ["write", "test", "vcs", "execute", "delegate", "read", "think"]


def _shell_action(cmd: str) -> str:
    """Classify a shell command into an action bucket."""
    if _RE_TEST.search(cmd):
        return "test"
    if _RE_GIT_WRITE.search(cmd):
        return "vcs"
    if _RE_GIT_READ.search(cmd):
        return "read"
    if _RE_READ_SHELL.search(cmd):
        return "read"
    return "execute"


def classify_action(tool_categories: list[str], shell_commands: list[str]) -> str:
    """Deterministic action classification from tool calls.

    Returns one of: write, test, read, execute, vcs, delegate, think.
    Uses a priority ladder — highest-value action wins the whole turn.
    Git read operations (diff, log, status) map to 'read', not 'vcs'.
    """
    cats = set(tool_categories)
    shell_actions = {_shell_action(cmd) for cmd in shell_commands}

    # Priority ladder
    if cats & {"file_write"}:
        return "write"
    if "test" in shell_actions:
        return "test"
    if "vcs" in shell_actions or cats & {"git_write"}:
        return "vcs"
    if "execute" in shell_actions:
        return "execute"
    if "agent" in cats:
        return "delegate"
    if cats & {"file_read", "file_search", "browser", "git_read"} or "read" in shell_actions:
        return "read"
    if "thinking" in cats:
        return "think"
    # No tools at all — pure LLM output
    return "think"


# ---------------------------------------------------------------------------
# Purpose classification (deterministic heuristics — no LLM)
#
# The key insight: purpose is about WHY the agent did something in context,
# not WHAT it did (that's action). We use structural signals:
#
# Signal 1 — Retry/error markers: is_retry=True or error_kind present on any
#            trail node for this turn → RECOVERING
# Signal 2 — Post-failure pattern: if the previous turn ran a test and the
#            current turn edits (without a new user message), → RECOVERING
# Signal 3 — Verification: turn runs tests AND a recent prior turn wrote files
#            → VERIFYING. A test run with no prior writes is just exploration.
# Signal 4 — Git/housekeeping: turn's ONLY actions are git commits/pushes or
#            bookkeeping (memory, todos) → HOUSEKEEPING
# Signal 5 — Pure reads: no writes at all (file_read, file_search, browser,
#            read-only shell) → ORIENTING
# Signal 6 — Has writes: file_write or non-trivial shell → BUILDING
# Signal 7 — No tools (pure reasoning) → ORIENTING
# ---------------------------------------------------------------------------

_RE_GIT_WRITE = re.compile(
    r"\bgit\s+(add|commit|push|merge|rebase|checkout|cherry-pick|stash|tag|reset)\b",
    re.IGNORECASE,
)

_BOOKKEEPING_CATEGORIES = {"bookkeeping", "thinking"}
_WRITE_CATEGORIES = {"file_write"}
_READ_ONLY_CATEGORIES = {"file_read", "file_search", "browser"}


def classify_purpose_heuristic(
    turn_num: int,
    turn_contexts: dict[int, dict],
    trail_nodes_by_turn: dict[int, list[dict]],
    actions_by_turn: dict[int, str],
) -> str:
    """Deterministic purpose classification for a single turn.

    Uses structural signals from trail nodes, tool categories, shell commands,
    and the sequence of preceding turns to determine why the agent acted.
    """
    ctx = turn_contexts.get(turn_num, {})
    cats = set(ctx.get("tool_categories", []))
    shells: list[str] = ctx.get("shell_commands", [])
    nodes = trail_nodes_by_turn.get(turn_num, [])

    # --- Signal 1: Retry/error markers → RECOVERING ---
    if any(n.get("is_retry") for n in nodes):
        return "recovering"
    if any(n.get("error_kind") for n in nodes):
        return "recovering"

    # --- Signal 2: Post-failure pattern ---
    # If the previous turn ran tests and this turn writes, it's fixing a failure.
    prev_turn = turn_num - 1
    if prev_turn in actions_by_turn:
        prev_action = actions_by_turn[prev_turn]
        this_action = actions_by_turn.get(turn_num, "think")
        if prev_action == "test" and this_action == "write":
            return "recovering"

    # --- Signal 3: Verification ---
    # Turn runs tests. If any of the preceding 3 turns wrote files, this is verifying.
    has_test = any(_RE_TEST.search(cmd) for cmd in shells)
    if has_test:
        lookback = range(max(1, turn_num - 3), turn_num)
        prior_wrote = any(actions_by_turn.get(t) == "write" for t in lookback)
        if prior_wrote:
            return "verifying"
        # Test run with no prior writes — exploring test behavior
        return "orienting"

    # --- Signal 3b: Early exploration ---
    # If NO preceding turn in this job has written yet, this turn is orienting
    # (agent is still building understanding before acting)
    this_action = actions_by_turn.get(turn_num, "think")
    any_prior_write = any(
        actions_by_turn.get(t) == "write"
        for t in range(min(actions_by_turn.keys(), default=turn_num), turn_num)
    )
    if not any_prior_write and this_action in ("read", "think"):
        return "orienting"

    # --- Signal 4: Git/housekeeping-only turns ---
    # If all shell commands are git writes and no non-housekeeping tool categories
    has_git_write = any(_RE_GIT_WRITE.search(cmd) for cmd in shells) or "git_write" in cats
    all_shells_are_git = shells and all(_RE_GIT_WRITE.search(cmd) or _RE_GIT_READ.search(cmd) for cmd in shells)

    # Categories that don't prevent housekeeping classification
    housekeeping_safe = _BOOKKEEPING_CATEGORIES | {"git_write", "git_read"}
    if all_shells_are_git:
        housekeeping_safe = housekeeping_safe | {"shell"}

    non_housekeeping = cats - housekeeping_safe
    if has_git_write and not non_housekeeping and not any(
        c in _WRITE_CATEGORIES for c in cats
    ):
        return "housekeeping"
    if cats and cats <= (_BOOKKEEPING_CATEGORIES | {"git_read"}):
        return "housekeeping"
    # Pure bookkeeping tools (memory, todos) without shell/file ops
    if cats and cats <= (_BOOKKEEPING_CATEGORIES | {"shell"}) and all_shells_are_git:
        return "housekeeping"

    # --- Signal 5: Pure reads → ORIENTING ---
    has_writes = bool(cats & _WRITE_CATEGORIES)
    # Shell is only "execute" if it runs something beyond read-only commands
    # If no shell text was extracted, defer to the action classifier's judgment
    has_productive_shell = "shell" in cats and not has_test and not has_git_write and (
        bool(shells) and not all(_RE_READ_SHELL.search(cmd) for cmd in shells)
    )
    has_delegation = "agent" in cats

    if not has_writes and not has_productive_shell and not has_delegation:
        # Any mix of reads, searches, read-only shells → orienting
        return "orienting"

    # --- Signal 6: Has writes → BUILDING ---
    if has_writes:
        return "building"

    # Execute/delegate without writes
    if has_delegation or has_productive_shell:
        return "building"

    return "building"


def classify_purposes_for_job(
    turn_contexts: dict[int, dict],
    trail_nodes: list[dict],
    actions_by_turn: dict[int, str],
) -> dict[int, str]:
    """Classify purpose for all turns in a job using deterministic heuristics.

    Returns {turn_number: purpose} dict.
    """
    # Group trail nodes by turn
    trail_nodes_by_turn: dict[int, list[dict]] = defaultdict(list)
    for node in trail_nodes:
        turn = node.get("turn_number") or node.get("anchor_seq")
        if turn is not None:
            trail_nodes_by_turn[int(turn)].append(node)

    result: dict[int, str] = {}
    for turn_num in sorted(turn_contexts.keys()):
        result[turn_num] = classify_purpose_heuristic(
            turn_num, turn_contexts, trail_nodes_by_turn, actions_by_turn
        )

    return result


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_completed_job_ids(session: AsyncSession) -> list[tuple[str, str | None]]:
    """Return (job_id, description) for all completed/resolved jobs."""
    result = await session.execute(
        text("""
            SELECT id, description FROM jobs
            WHERE state IN ('completed', 'resolved', 'merged')
            ORDER BY created_at ASC
        """)
    )
    return [(r["id"], r["description"]) for r in result.mappings().all()]


async def get_job_spans(session: AsyncSession, job_id: str) -> list[dict[str, Any]]:
    """Get all spans for a job ordered by time."""
    result = await session.execute(
        text("""
            SELECT span_type, name, turn_number, tool_category, tool_args_json,
                   input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                   cost_usd, duration_ms, execution_phase
            FROM job_telemetry_spans
            WHERE job_id = :job_id
            ORDER BY started_at ASC
        """),
        {"job_id": job_id},
    )
    return [dict(r) for r in result.mappings().all()]


async def get_trail_nodes(session: AsyncSession, job_id: str) -> list[dict[str, Any]]:
    """Get trail nodes for a job."""
    result = await session.execute(
        text("""
            SELECT id, seq, anchor_seq, kind, is_retry, error_kind,
                   intent, enrichment
            FROM trail_nodes
            WHERE job_id = :job_id
            ORDER BY anchor_seq, seq
        """),
        {"job_id": job_id},
    )
    rows = []
    for r in result.mappings().all():
        row = dict(r)
        # Use anchor_seq as the turn number (1-based sequence within job)
        row["turn_number"] = row.get("anchor_seq")
        rows.append(row)
    return rows


async def delete_old_dimensions(session: AsyncSession, job_id: str) -> None:
    """Remove old dimension rows for a job before re-writing."""
    await session.execute(
        text("""
            DELETE FROM job_cost_attribution
            WHERE job_id = :job_id
              AND dimension IN ('activity', 'motivation', 'edit_efficiency',
                                'activity_phase', 'action', 'purpose', 'action_purpose')
        """),
        {"job_id": job_id},
    )
    await session.execute(
        text("""
            DELETE FROM job_latency_attribution
            WHERE job_id = :job_id AND dimension IN ('activity', 'action')
        """),
        {"job_id": job_id},
    )


async def write_attribution_rows(
    session: AsyncSession,
    job_id: str,
    turn_actions: dict[int, str],
    turn_purposes: dict[int, str],
    turn_costs: dict[int, dict],
) -> int:
    """Write action, purpose, action_purpose dimension rows. Returns row count."""
    now = datetime.now(UTC).isoformat()
    rows_written = 0

    # Aggregate by action
    by_action: dict[str, dict] = defaultdict(lambda: _zero_bucket())
    by_purpose: dict[str, dict] = defaultdict(lambda: _zero_bucket())
    by_cross: dict[str, dict] = defaultdict(lambda: _zero_bucket())

    for turn_num, action in turn_actions.items():
        cost = turn_costs.get(turn_num, _zero_bucket())
        _accumulate(by_action[action], cost)

        purpose = turn_purposes.get(turn_num)
        if purpose:
            _accumulate(by_purpose[purpose], cost)
            cross_key = f"{action}:{purpose}"
            _accumulate(by_cross[cross_key], cost)

    # Write cost attribution rows
    for bucket, data in by_action.items():
        await session.execute(
            text("""
                INSERT INTO job_cost_attribution
                    (job_id, dimension, bucket, cost_usd, input_tokens, output_tokens,
                     call_count, cache_read_tokens, cache_write_tokens, model, created_at)
                VALUES (:job_id, 'action', :bucket, :cost_usd, :input_tokens, :output_tokens,
                        :call_count, :cache_read_tokens, :cache_write_tokens, '', :now)
            """),
            {"job_id": job_id, "bucket": bucket, "now": now, **data},
        )
        rows_written += 1

    for bucket, data in by_purpose.items():
        await session.execute(
            text("""
                INSERT INTO job_cost_attribution
                    (job_id, dimension, bucket, cost_usd, input_tokens, output_tokens,
                     call_count, cache_read_tokens, cache_write_tokens, model, created_at)
                VALUES (:job_id, 'purpose', :bucket, :cost_usd, :input_tokens, :output_tokens,
                        :call_count, :cache_read_tokens, :cache_write_tokens, '', :now)
            """),
            {"job_id": job_id, "bucket": bucket, "now": now, **data},
        )
        rows_written += 1

    for bucket, data in by_cross.items():
        await session.execute(
            text("""
                INSERT INTO job_cost_attribution
                    (job_id, dimension, bucket, cost_usd, input_tokens, output_tokens,
                     call_count, cache_read_tokens, cache_write_tokens, model, created_at)
                VALUES (:job_id, 'action_purpose', :bucket, :cost_usd, :input_tokens, :output_tokens,
                        :call_count, :cache_read_tokens, :cache_write_tokens, '', :now)
            """),
            {"job_id": job_id, "bucket": bucket, "now": now, **data},
        )
        rows_written += 1

    # Write latency attribution (action dimension)
    # Latency uses duration_ms from tool spans aggregated per turn
    # For simplicity, reuse cost rows with zero cost — latency is tracked separately
    # by the latency repo, so we skip latency for now (handled in a future pass)

    return rows_written


async def update_trail_purpose(
    session: AsyncSession,
    job_id: str,
    turn_purposes: dict[int, str],
    trail_nodes: list[dict],
) -> int:
    """Store purpose on trail_nodes. Returns update count."""
    updated = 0
    for node in trail_nodes:
        turn = node.get("turn_number") or node.get("anchor_seq")
        if turn and turn in turn_purposes:
            await session.execute(
                text("""
                    UPDATE trail_nodes
                    SET purpose = :purpose, purpose_source = 'backfill'
                    WHERE id = :node_id
                """),
                {"purpose": turn_purposes[turn], "node_id": node["id"]},
            )
            updated += 1
    return updated


def _zero_bucket() -> dict:
    return {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "call_count": 0,
    }


def _accumulate(target: dict, source: dict) -> None:
    target["cost_usd"] += source.get("cost_usd", 0.0) or 0.0
    target["input_tokens"] += source.get("input_tokens", 0) or 0
    target["output_tokens"] += source.get("output_tokens", 0) or 0
    target["cache_read_tokens"] += source.get("cache_read_tokens", 0) or 0
    target["cache_write_tokens"] += source.get("cache_write_tokens", 0) or 0
    target["call_count"] += 1


# ---------------------------------------------------------------------------
# Main backfill logic
# ---------------------------------------------------------------------------


def _build_turn_contexts(spans: list[dict]) -> tuple[dict[int, dict], dict[int, dict]]:
    """Build per-turn tool/shell contexts and cost data from spans.

    Returns (turn_contexts, turn_costs).
    """
    turn_contexts: dict[int, dict] = defaultdict(
        lambda: {"tool_categories": [], "shell_commands": [], "phase": None}
    )
    turn_costs: dict[int, dict] = defaultdict(_zero_bucket)

    for span in spans:
        turn = span.get("turn_number")
        if turn is None:
            continue
        turn = int(turn)

        # Accumulate cost (from LLM spans)
        if span.get("span_type") == "llm":
            turn_costs[turn]["cost_usd"] += float(span.get("cost_usd") or 0.0)
            turn_costs[turn]["input_tokens"] += int(span.get("input_tokens") or 0)
            turn_costs[turn]["output_tokens"] += int(span.get("output_tokens") or 0)
            turn_costs[turn]["cache_read_tokens"] += int(span.get("cache_read_tokens") or 0)
            turn_costs[turn]["cache_write_tokens"] += int(span.get("cache_write_tokens") or 0)

        # Collect tool categories
        if span.get("span_type") == "tool":
            cat = span.get("tool_category") or classify_tool(span.get("name") or "")
            # Promote shell git commands to git_read/git_write
            if cat == "shell":
                tool_args = span.get("tool_args_json")
                refined = refine_shell_category(tool_args if isinstance(tool_args, str) else None)
                if refined:
                    cat = refined
            turn_contexts[turn]["tool_categories"].append(cat)

            # Extract shell command text for non-git shell commands
            if cat == "shell":
                tool_args = span.get("tool_args_json")
                cmd = ""
                if isinstance(tool_args, str):
                    try:
                        parsed = json.loads(tool_args)
                        cmd = parsed.get("command", "") or parsed.get("cmd", "")
                    except (ValueError, TypeError):
                        pass
                elif isinstance(tool_args, dict):
                    cmd = tool_args.get("command", "") or tool_args.get("cmd", "")
                if cmd:
                    turn_contexts[turn]["shell_commands"].append(str(cmd))

        # Phase
        if span.get("execution_phase"):
            turn_contexts[turn]["phase"] = span["execution_phase"]

    return dict(turn_contexts), dict(turn_costs)


async def backfill_job(
    session: AsyncSession,
    job_id: str,
    description: str | None,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill action + purpose attribution for a single job.

    Returns stats dict with keys: turns, actions_written, purposes_classified, rows_written.
    """
    spans = await get_job_spans(session, job_id)
    if not spans:
        return {"turns": 0, "actions_written": 0, "purposes_classified": 0, "rows_written": 0}

    turn_contexts, turn_costs = _build_turn_contexts(spans)
    if not turn_contexts:
        return {"turns": 0, "actions_written": 0, "purposes_classified": 0, "rows_written": 0}

    # Action classification — deterministic
    turn_actions: dict[int, str] = {}
    for turn_num, ctx in turn_contexts.items():
        turn_actions[turn_num] = classify_action(
            ctx["tool_categories"], ctx["shell_commands"]
        )

    # Purpose classification — deterministic heuristics (no LLM)
    trail_nodes = await get_trail_nodes(session, job_id)
    turn_purposes = classify_purposes_for_job(turn_contexts, trail_nodes, turn_actions)

    if dry_run:
        return {
            "turns": len(turn_contexts),
            "actions_written": len(turn_actions),
            "purposes_classified": len(turn_purposes),
            "rows_written": 0,
        }

    # Delete old dimensions and write new ones
    await delete_old_dimensions(session, job_id)
    rows_written = await write_attribution_rows(
        session, job_id, turn_actions, turn_purposes, turn_costs
    )

    # Update trail nodes with purpose
    await update_trail_purpose(session, job_id, turn_purposes, trail_nodes)

    await session.commit()

    return {
        "turns": len(turn_contexts),
        "actions_written": len(turn_actions),
        "purposes_classified": len(turn_purposes),
        "rows_written": rows_written,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill action×purpose attribution")
    parser.add_argument("--dry-run", action="store_true", help="Classify but don't write to DB")
    parser.add_argument("--job-id", help="Backfill a single job instead of all")
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "CODEPLANE_DB_URL",
            f"sqlite+aiosqlite:///{Path.home() / '.codeplane' / 'data.db'}",
        ),
        help="Database URL",
    )
    args = parser.parse_args()

    print(f"Database: {args.db_url}")
    print(f"Dry run: {args.dry_run}")
    print()

    engine = create_async_engine(args.db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        if args.job_id:
            jobs = [(args.job_id, None)]
            # Fetch description
            result = await session.execute(
                text("SELECT description FROM jobs WHERE id = :jid"),
                {"jid": args.job_id},
            )
            row = result.mappings().first()
            if row:
                jobs = [(args.job_id, row["description"])]
        else:
            jobs = await get_completed_job_ids(session)

        print(f"Jobs to process: {len(jobs)}")
        print()

        total_stats = {"turns": 0, "actions_written": 0, "purposes_classified": 0, "rows_written": 0}
        errors = 0

        for i, (job_id, description) in enumerate(jobs, 1):
            try:
                stats = await backfill_job(
                    session,
                    job_id,
                    description,
                    dry_run=args.dry_run,
                )
                for k in total_stats:
                    total_stats[k] += stats[k]

                status = "DRY" if args.dry_run else "OK"
                print(
                    f"[{i}/{len(jobs)}] {status} {job_id[:12]}… "
                    f"turns={stats['turns']} actions={stats['actions_written']} "
                    f"purposes={stats['purposes_classified']}"
                )
            except Exception as exc:
                errors += 1
                print(f"[{i}/{len(jobs)}] ERROR {job_id[:12]}… {exc}")
                # Don't abort — continue with next job
                await session.rollback()

    await engine.dispose()

    print()
    print("=" * 60)
    print(f"Total: {total_stats}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
