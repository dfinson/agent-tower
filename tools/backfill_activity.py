"""Backfill: recompute the `activity` dimension for all jobs.

Uses per-tool classification with proportional cost splitting:
each tool call in a turn is classified independently, and the turn's
cost is distributed proportionally across the resulting activities.

Usage:
    uv run python tools/backfill_activity.py [--dry-run] [--job-id JOB_ID]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.services.analytics.cost_attribution import _classify_turn_intent
from backend.services.tools.tool_classifier import classify_tool, classify_tool_activity, refine_shell_category


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


async def get_job_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(
        text("""
            SELECT id FROM jobs
            WHERE state IN ('completed', 'resolved', 'merged', 'review', 'failed')
            ORDER BY created_at ASC
        """)
    )
    return [r[0] for r in result.all()]


async def get_spans(session: AsyncSession, job_id: str) -> list[dict[str, Any]]:
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


def build_turn_data(spans: list[dict]) -> tuple[dict[int, dict], dict[int, dict]]:
    """Build per-turn contexts and cost data from raw spans."""
    turn_contexts: dict[int, dict] = defaultdict(
        lambda: {"phase": None, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                 "cache_read_tokens": 0, "cache_write_tokens": 0,
                 "tool_categories": [], "shell_commands": [], "tool_activity_weights": []}
    )
    turn_costs: dict[int, dict] = defaultdict(_zero_bucket)

    for span in spans:
        turn = span.get("turn_number")
        if turn is None:
            continue
        turn = int(turn)

        if span.get("span_type") == "llm":
            turn_costs[turn]["cost_usd"] += float(span.get("cost_usd") or 0.0)
            turn_costs[turn]["input_tokens"] += int(span.get("input_tokens") or 0)
            turn_costs[turn]["output_tokens"] += int(span.get("output_tokens") or 0)
            turn_costs[turn]["cache_read_tokens"] += int(span.get("cache_read_tokens") or 0)
            turn_costs[turn]["cache_write_tokens"] += int(span.get("cache_write_tokens") or 0)
            turn_contexts[turn]["output_tokens"] += int(span.get("output_tokens") or 0)

        if span.get("span_type") == "tool":
            tool_name = span.get("name") or ""
            tool_args = span.get("tool_args_json")
            cat = span.get("tool_category") or classify_tool(tool_name)
            # Promote shell git commands to git_read/git_write
            if cat == "shell":
                refined = refine_shell_category(tool_args if isinstance(tool_args, str) else None)
                if refined:
                    cat = refined
            tool_activity = classify_tool_activity(tool_name, tool_args)
            args_weight = len(tool_args) if isinstance(tool_args, str) else 1
            turn_contexts[turn]["tool_categories"].append(cat)
            turn_contexts[turn]["tool_activity_weights"].append((tool_activity, args_weight))

            if cat == "shell":
                cmd = ""
                if isinstance(tool_args, str):
                    try:
                        parsed = json.loads(tool_args)
                        cmd = parsed.get("command", "") or parsed.get("cmd", "") or parsed.get("input", "")
                    except (ValueError, TypeError):
                        pass
                elif isinstance(tool_args, dict):
                    cmd = tool_args.get("command", "") or tool_args.get("cmd", "") or tool_args.get("input", "")
                if cmd:
                    turn_contexts[turn]["shell_commands"].append(str(cmd))

        if span.get("execution_phase"):
            turn_contexts[turn]["phase"] = span["execution_phase"]

    return dict(turn_contexts), dict(turn_costs)


async def backfill_job(session: AsyncSession, job_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    spans = await get_spans(session, job_id)
    if not spans:
        return {"turns": 0, "changed": 0}

    turn_contexts, turn_costs = build_turn_data(spans)
    if not turn_contexts:
        return {"turns": 0, "changed": 0}

    # Per-tool classification with args-weighted cost splitting
    by_activity: dict[str, dict] = defaultdict(_zero_bucket)
    for turn_num in sorted(turn_contexts.keys()):
        ctx = turn_contexts[turn_num]
        cost = turn_costs.get(turn_num, _zero_bucket())
        tool_activity_weights = ctx.get("tool_activity_weights", [])

        if tool_activity_weights:
            # Group weights by activity
            activity_weight_sums: dict[str, int] = defaultdict(int)
            activity_call_counts: dict[str, int] = defaultdict(int)
            total_weight = 0
            for activity, weight in tool_activity_weights:
                activity_weight_sums[activity] += weight
                activity_call_counts[activity] += 1
                total_weight += weight
            for activity, weight_sum in activity_weight_sums.items():
                fraction = weight_sum / total_weight if total_weight > 0 else 1 / len(activity_weight_sums)
                fractional_cost = {
                    "cost_usd": float(cost["cost_usd"]) * fraction,
                    "input_tokens": int(int(cost["input_tokens"]) * fraction),
                    "output_tokens": int(int(cost["output_tokens"]) * fraction),
                    "cache_read_tokens": int(int(cost["cache_read_tokens"]) * fraction),
                    "cache_write_tokens": int(int(cost["cache_write_tokens"]) * fraction),
                }
                _accumulate(by_activity[activity], fractional_cost)
                by_activity[activity]["call_count"] += activity_call_counts[activity] - 1  # _accumulate adds 1
        else:
            # No tools — fallback to turn-level (reasoning / communication)
            activity = _classify_turn_intent(ctx)
            _accumulate(by_activity[activity], cost)

    if dry_run:
        return {"turns": len(turn_contexts), "changed": len(by_activity), "activities": dict(by_activity)}

    # Delete old activity rows and write new ones
    await session.execute(
        text("DELETE FROM job_cost_attribution WHERE job_id = :job_id AND dimension = 'activity'"),
        {"job_id": job_id},
    )

    now = datetime.now(UTC).isoformat()
    for bucket, data in by_activity.items():
        await session.execute(
            text("""
                INSERT INTO job_cost_attribution
                    (job_id, dimension, bucket, cost_usd, input_tokens, output_tokens,
                     call_count, cache_read_tokens, cache_write_tokens, model, created_at)
                VALUES (:job_id, 'activity', :bucket, :cost_usd, :input_tokens, :output_tokens,
                        :call_count, :cache_read_tokens, :cache_write_tokens, '', :now)
            """),
            {"job_id": job_id, "bucket": bucket, "now": now, **data},
        )

    await session.commit()
    return {"turns": len(turn_contexts), "changed": len(by_activity)}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill activity dimension with corrected shell classification")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--job-id", help="Backfill a single job")
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "CODEPLANE_DB_URL",
            f"sqlite+aiosqlite:///{Path.home() / '.codeplane' / 'data.db'}",
        ),
    )
    args = parser.parse_args()

    print(f"Database: {args.db_url}")
    print(f"Dry run: {args.dry_run}")
    print()

    engine = create_async_engine(args.db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        if args.job_id:
            job_ids = [args.job_id]
        else:
            job_ids = await get_job_ids(session)

        print(f"Jobs to process: {len(job_ids)}")
        print()

        total_turns = 0
        total_changed = 0
        errors = 0

        for i, job_id in enumerate(job_ids, 1):
            try:
                stats = await backfill_job(session, job_id, dry_run=args.dry_run)
                total_turns += stats["turns"]
                total_changed += stats["changed"]

                status = "DRY" if args.dry_run else "OK"
                extra = ""
                if args.dry_run and "activities" in stats:
                    acts = ", ".join(f"{k}={v['call_count']}" for k, v in sorted(stats["activities"].items()))
                    extra = f" [{acts}]"
                print(f"  [{i}/{len(job_ids)}] {status} {job_id[:12]}… turns={stats['turns']}{extra}")
            except Exception as exc:
                errors += 1
                print(f"  [{i}/{len(job_ids)}] ERROR {job_id[:12]}… {exc}")
                await session.rollback()

    await engine.dispose()

    print()
    print(f"Done. {total_turns} turns across {len(job_ids)} jobs. Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
