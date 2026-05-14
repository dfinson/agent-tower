"""Cross-job statistical analysis service.

Analyses accumulated telemetry to surface actionable cost observations:
- Tool failure patterns (high failure rates for specific tools)
- Retry waste (retries that cost more than the original attempt)
- Cache efficiency regression (cache hit rate drops between periods)

Run periodically or after each job completion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.persistence.observations_repo import ObservationsRepository
    from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

log = structlog.get_logger()


async def run_analysis(session: AsyncSession) -> int:
    """Run all analysis passes. Returns the number of observations written."""
    from backend.persistence.observations_repo import ObservationsRepository
    from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository
    from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

    obs_repo = ObservationsRepository(session)
    spans_repo = TelemetrySpansRepository(session)
    summary_repo = TelemetryAnalyticsRepository(session)
    count = 0
    count += await _analyse_tool_failures(spans_repo, obs_repo)
    count += await _analyse_retry_waste(spans_repo, obs_repo)
    count += await _analyse_cache_efficiency_regression(summary_repo, obs_repo)
    log.info("statistical_analysis_complete", observations=count)
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


async def _analyse_cache_efficiency_regression(
    summary_repo: TelemetryAnalyticsRepository,
    obs_repo: ObservationsRepository,
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
