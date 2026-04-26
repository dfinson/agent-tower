"""Cross-job statistical analysis service.

Analyses accumulated telemetry to surface actionable cost observations:
- File reread hotspots (same file read many times across jobs)
- Tool failure patterns (high failure rates for specific tools)
- Turn cost escalation (cost/turn increases significantly late in jobs)
- Retry waste (retries that cost more than the original attempt)
- Compaction storms (excessive context compactions signaling context pressure)
- Cache efficiency regression (cache hit rate drops between periods)

Run periodically or after each job completion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.file_access_repo import FileAccessRepository
from backend.persistence.observations_repo import ObservationsRepository
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

log = structlog.get_logger()


async def run_analysis(session: AsyncSession) -> int:
    """Run all analysis passes. Returns the number of observations written."""
    obs_repo = ObservationsRepository(session)
    file_repo = FileAccessRepository(session)
    spans_repo = TelemetrySpansRepository(session)
    summary_repo = TelemetrySummaryRepository(session)
    count = 0
    count += await _analyse_file_rereads(file_repo, obs_repo)
    count += await _analyse_tool_failures(spans_repo, obs_repo)
    count += await _analyse_turn_escalation(summary_repo, obs_repo)
    count += await _analyse_retry_waste(spans_repo, obs_repo)
    count += await _analyse_compaction_storms(summary_repo, obs_repo)
    count += await _analyse_cache_efficiency_regression(summary_repo, obs_repo)
    log.info("statistical_analysis_complete", observations=count)
    return count


async def _analyse_file_rereads(file_repo: FileAccessRepository, obs_repo: ObservationsRepository) -> int:
    """Find files read excessively across jobs."""
    rows = await file_repo.reread_hotspots()
    count = 0
    for r in rows:
        await obs_repo.upsert(
            category="file_reread",
            severity="warning" if r["total_reads"] >= 50 else "info",
            title=f"Excessive rereads: {r['file_path']}",
            detail=(
                f"File '{r['file_path']}' was read {r['total_reads']} times "
                f"across {r['job_count']} jobs in the last 30 days."
            ),
            evidence={
                "file_path": r["file_path"],
                "total_reads": r["total_reads"],
                "job_count": r["job_count"],
                "total_bytes": r["total_bytes"],
            },
            job_count=r["job_count"],
        )
        count += 1
    return count


async def _analyse_tool_failures(spans_repo: TelemetrySpansRepository, obs_repo: ObservationsRepository) -> int:
    """Find tools with high failure rates."""
    rows = await spans_repo.tool_failure_hotspots()
    count = 0
    for r in rows:
        failure_rate = r["failures"] / r["total_calls"] * 100
        await obs_repo.upsert(
            category="tool_failure",
            severity="critical" if failure_rate >= 50 else "warning",
            title=f"High failure rate: {r['name']} ({failure_rate:.0f}%)",
            detail=(
                f"Tool '{r['name']}' failed {r['failures']}/{r['total_calls']} times "
                f"({failure_rate:.1f}%) across {r['job_count']} jobs."
            ),
            evidence={
                "tool_name": r["name"],
                "total_calls": r["total_calls"],
                "failures": r["failures"],
                "failure_rate_pct": round(failure_rate, 1),
                "job_count": r["job_count"],
            },
            job_count=r["job_count"],
        )
        count += 1
    return count


async def _analyse_turn_escalation(summary_repo: TelemetrySummaryRepository, obs_repo: ObservationsRepository) -> int:
    """Find jobs where cost/turn escalates significantly in the second half."""
    rows = await summary_repo.turn_escalation_jobs()
    if len(rows) < 3:
        return 0

    total_waste = sum(max(0, r["cost_second_half_usd"] - r["cost_first_half_usd"]) for r in rows)
    await obs_repo.upsert(
        category="turn_escalation",
        severity="warning" if total_waste >= 1.0 else "info",
        title=f"Cost escalation in {len(rows)} jobs",
        detail=(f"{len(rows)} jobs had 2nd-half costs ≥2x 1st-half costs. Estimated waste: ${total_waste:.2f}."),
        evidence={
            "affected_jobs": [dict(r) for r in rows[:5]],
            "total_jobs": len(rows),
        },
        job_count=len(rows),
        total_waste_usd=total_waste,
    )
    return 1


async def _analyse_retry_waste(spans_repo: TelemetrySpansRepository, obs_repo: ObservationsRepository) -> int:
    """Find tools where retries are common and costly."""
    rows = await spans_repo.retry_hotspots()
    count = 0
    for r in rows:
        retry_pct = r["retry_count"] / r["total_calls"] * 100
        if retry_pct < 10:
            continue
        await obs_repo.upsert(
            category="retry_waste",
            severity="warning" if retry_pct >= 30 else "info",
            title=f"Frequent retries: {r['tool_name']} ({retry_pct:.0f}%)",
            detail=(
                f"Tool '{r['tool_name']}' was retried {r['retry_count']}/{r['total_calls']} "
                f"times ({retry_pct:.1f}%) across {r['job_count']} jobs."
            ),
            evidence={
                "tool_name": r["tool_name"],
                "retry_count": r["retry_count"],
                "total_calls": r["total_calls"],
                "retry_pct": round(retry_pct, 1),
                "job_count": r["job_count"],
            },
            job_count=r["job_count"],
        )
        count += 1
    return count


async def _analyse_compaction_storms(summary_repo: TelemetrySummaryRepository, obs_repo: ObservationsRepository) -> int:
    """Detect jobs with excessive context compactions."""
    rows = await summary_repo.compaction_storm_jobs()
    if len(rows) < 2:
        return 0

    total_tokens_wasted = sum(int(r["tokens_compacted"] or 0) for r in rows)
    max_compactions = max(int(r["compactions"] or 0) for r in rows)
    await obs_repo.upsert(
        category="compaction_storm",
        severity="warning" if max_compactions >= 10 else "info",
        title=f"Excessive compactions in {len(rows)} jobs",
        detail=(
            f"{len(rows)} jobs required ≥5 context compactions. "
            f"Total tokens compacted: {total_tokens_wasted:,}. "
            f"Peak: {max_compactions} compactions in a single job."
        ),
        evidence={
            "affected_jobs": [
                {
                    "job_id": r["job_id"],
                    "compactions": int(r["compactions"]),
                    "tokens_compacted": int(r["tokens_compacted"] or 0),
                }
                for r in rows[:5]
            ],
            "total_jobs": len(rows),
            "total_tokens_compacted": total_tokens_wasted,
        },
        job_count=len(rows),
    )
    return 1


async def _analyse_cache_efficiency_regression(
    summary_repo: TelemetrySummaryRepository, obs_repo: ObservationsRepository,
) -> int:
    """Detect drops in cache hit rate compared to the prior period."""
    row = await summary_repo.cache_efficiency_periods()
    if not row:
        return 0

    recent_input = int(row.get("recent_input") or 0)
    recent_cache = int(row.get("recent_cache") or 0)
    prior_input = int(row.get("prior_input") or 0)
    prior_cache = int(row.get("prior_cache") or 0)

    # Need sufficient data in both periods
    if recent_input < 10000 or prior_input < 10000:
        return 0

    recent_rate = recent_cache / recent_input * 100
    prior_rate = prior_cache / prior_input * 100

    # Alert if cache rate dropped by ≥15 percentage points
    drop = prior_rate - recent_rate
    if drop < 15:
        return 0

    await obs_repo.upsert(
        category="cache_regression",
        severity="warning" if drop >= 25 else "info",
        title=f"Cache hit rate dropped {drop:.0f}pp (last 7d vs prior 7d)",
        detail=(
            f"Cache read rate fell from {prior_rate:.1f}% to {recent_rate:.1f}% "
            f"({drop:.1f} percentage point drop). This may indicate a provider "
            f"change, prompt mutation, or caching misconfiguration."
        ),
        evidence={
            "recent_rate_pct": round(recent_rate, 1),
            "prior_rate_pct": round(prior_rate, 1),
            "drop_pp": round(drop, 1),
            "recent_input_tokens": recent_input,
            "prior_input_tokens": prior_input,
        },
    )
    return 1
