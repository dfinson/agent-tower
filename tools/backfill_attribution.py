"""One-off backfill: classify action + purpose for all completed jobs.

Action is deterministic from tool calls (no LLM needed).
Purpose requires understanding intent — uses Copilot sessions on a cheap model.

Usage:
    uv run python tools/backfill_attribution.py [--dry-run] [--job-id JOB_ID] [--sdk copilot|claude]

Writes new dimension rows (action, purpose, action_purpose) to
job_cost_attribution and job_latency_attribution. Stores purpose +
purpose_source on trail_nodes.
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

from backend.services.tool_classifier import classify_tool

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Action classification (deterministic — no LLM)
# ---------------------------------------------------------------------------

_RE_TEST = re.compile(
    r"\b(pytest|vitest|jest|mocha|npm\s+test|npx\s+vitest|npx\s+jest|"
    r"cargo\s+test|go\s+test|rspec|phpunit|unittest|npm\s+run\s+test)\b",
    re.IGNORECASE,
)
_RE_GIT = re.compile(
    r"\bgit\s+(add|commit|push|merge|rebase|checkout|cherry-pick|stash|tag|reset|"
    r"diff|log|status|show|blame|branch)\b",
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
    if _RE_GIT.search(cmd):
        return "vcs"
    if _RE_READ_SHELL.search(cmd):
        return "read"
    return "execute"


def classify_action(tool_categories: list[str], shell_commands: list[str]) -> str:
    """Deterministic action classification from tool calls.

    Returns one of: write, test, read, execute, vcs, delegate, think.
    Uses a priority ladder — highest-value action wins the whole turn.
    """
    cats = set(tool_categories)
    shell_actions = {_shell_action(cmd) for cmd in shell_commands}

    # Priority ladder
    if cats & {"file_write"}:
        return "write"
    if "test" in shell_actions:
        return "test"
    if "vcs" in shell_actions or cats & {"git_write", "git_read"}:
        return "vcs"
    if "execute" in shell_actions:
        return "execute"
    if "agent" in cats:
        return "delegate"
    if cats & {"file_read", "file_search", "browser"} or "read" in shell_actions:
        return "read"
    if "thinking" in cats:
        return "think"
    # No tools at all — pure LLM output
    return "think"


# ---------------------------------------------------------------------------
# Purpose classification (LLM-powered, batch per job)
# ---------------------------------------------------------------------------

PURPOSE_SYSTEM_PROMPT = """\
You classify each turn of a coding agent session by its PURPOSE — why the agent \
took that action in the context of the job.

Allowed values (exactly one per turn):
- advancing: executing toward the goal (writing features, making progress)
- recovering: fixing own mistakes, retrying after a failure, debugging self-caused errors
- orienting: building understanding before acting (reading code, exploring, planning)
- verifying: confirming correctness of completed work (running tests after implementation)
- housekeeping: mechanical overhead not directly advancing the goal (git commit, memory, todos)

Rules:
- Consider the SEQUENCE — early reads before any writes are "orienting", not "advancing"
- A test run immediately after writing code is "verifying"
- A test run that FAILS followed by edits means those edits are "recovering"
- Git commits/pushes after implementation are "housekeeping"
- If a turn re-does something that was just attempted and failed, it's "recovering"
"""

PURPOSE_USER_TEMPLATE = """\
Job goal: "{goal}"

Turns (in order):
{turn_block}

Respond with ONLY a JSON object: {{"turns": [{{"turn": 1, "purpose": "advancing"}}, ...]}}
No explanation, just the JSON.
"""


def _build_turn_block(turn_contexts: dict[int, dict]) -> str:
    """Build compact turn descriptions for the LLM prompt."""
    lines = []
    for turn_num in sorted(turn_contexts.keys()):
        ctx = turn_contexts[turn_num]
        cats = ctx.get("tool_categories", [])
        shells = ctx.get("shell_commands", [])
        action = classify_action(cats, shells)

        # Summarize compactly
        cat_counts: dict[str, int] = defaultdict(int)
        for c in cats:
            cat_counts[c] += 1
        cat_str = ", ".join(f"{k}×{v}" for k, v in sorted(cat_counts.items()))

        shell_str = ""
        if shells:
            # Show first 3 commands, truncated
            shown = [cmd[:80] for cmd in shells[:3]]
            shell_str = f" | Shell: {shown}"

        lines.append(f"{turn_num}. [{action}] Tools: [{cat_str}]{shell_str}")

    return "\n".join(lines)


async def classify_purposes_llm(
    goal: str,
    turn_contexts: dict[int, dict],
    *,
    adapter: Any,
) -> dict[int, str]:
    """Call LLM via Copilot/Claude adapter to classify purpose for all turns in a job.

    Returns {turn_number: purpose} dict.
    """
    from backend.services.agent_adapter import CompletionResult

    turn_block = _build_turn_block(turn_contexts)
    user_msg = PURPOSE_USER_TEMPLATE.format(goal=goal or "unknown", turn_block=turn_block)
    full_prompt = f"{PURPOSE_SYSTEM_PROMPT}\n\n{user_msg}"

    result: CompletionResult = await adapter.complete(full_prompt)
    raw_text = result.text or ""

    if not raw_text.strip():
        log.warning("purpose_llm_empty_response")
        return {}

    # Parse response
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if match:
            parsed = json.loads(match.group(1))
        else:
            log.warning("purpose_llm_parse_failed", raw=raw_text[:200])
            return {}

    valid_purposes = {"advancing", "recovering", "orienting", "verifying", "housekeeping"}
    result_map: dict[int, str] = {}
    for entry in parsed.get("turns", []):
        turn = entry.get("turn")
        purpose = entry.get("purpose")
        if isinstance(turn, int) and purpose in valid_purposes:
            result_map[turn] = purpose

    return result_map


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
                   cost_usd, duration_ms, execution_phase, is_subagent
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
            SELECT id, seq, anchor_seq, turn_number, kind, is_retry, error_kind,
                   intent, enrichment
            FROM trail_nodes
            WHERE job_id = :job_id
            ORDER BY anchor_seq, seq
        """),
        {"job_id": job_id},
    )
    # turn_number may not exist on older schemas — handle gracefully
    rows = []
    for r in result.mappings().all():
        row = dict(r)
        # Normalize missing turn_number
        if "turn_number" not in row:
            row["turn_number"] = row.get("anchor_seq")
        rows.append(row)
    return rows


async def delete_old_dimensions(session: AsyncSession, job_id: str) -> None:
    """Remove legacy dimension rows for a job (activity, motivation, edit_efficiency, activity_phase)."""
    await session.execute(
        text("""
            DELETE FROM job_cost_attribution
            WHERE job_id = :job_id
              AND dimension IN ('activity', 'motivation', 'edit_efficiency', 'activity_phase')
        """),
        {"job_id": job_id},
    )
    await session.execute(
        text("""
            DELETE FROM job_latency_attribution
            WHERE job_id = :job_id AND dimension = 'activity'
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
            turn_contexts[turn]["tool_categories"].append(cat)

            # Extract shell command text
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


def _create_adapter(sdk: str) -> Any:
    """Instantiate an agent adapter for the given SDK (copilot or claude)."""
    from backend.services.adapter_registry import AdapterRegistry

    registry = AdapterRegistry()
    return registry.get_adapter(sdk)


async def backfill_job(
    session: AsyncSession,
    job_id: str,
    description: str | None,
    *,
    adapter: Any,
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

    # Purpose classification — LLM via adapter
    turn_purposes: dict[int, str] = {}
    if len(turn_contexts) > 0:
        try:
            turn_purposes = await classify_purposes_llm(
                goal=description or "unknown",
                turn_contexts=turn_contexts,
                adapter=adapter,
            )
        except (json.JSONDecodeError, KeyError, OSError, RuntimeError) as exc:
            log.warning("purpose_classification_failed", job_id=job_id, error=str(exc))

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
    trail_nodes = await get_trail_nodes(session, job_id)
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
        "--sdk",
        default="copilot",
        choices=["copilot", "claude"],
        help="SDK adapter to use for LLM calls (default: copilot)",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "CODEPLANE_DB_URL",
            f"sqlite+aiosqlite:///{Path.home() / '.codeplane' / 'data.db'}",
        ),
        help="Database URL",
    )
    args = parser.parse_args()

    # Create adapter — uses Copilot/Claude SDK session for LLM calls
    adapter = _create_adapter(args.sdk)

    print(f"SDK: {args.sdk}")
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
                    adapter=adapter,
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
