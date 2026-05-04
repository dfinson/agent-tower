"""Read-only analytics queries on the job_telemetry_summary table.

Split from TelemetrySummaryRepository to separate write-path (event-driven
upserts) from read-path (analytics queries, scorecards, comparisons).
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import text

from backend.models.domain import (
    AggregateStats,
    CostByDayRow,
    CostByModelRow,
    CostByRepoRow,
    ModelComparisonRow,
    TelemetrySummaryRow,
)
from backend.persistence.repository import BaseRepository


class TelemetryAnalyticsRepository(BaseRepository):
    """Read-only analytics queries on job_telemetry_summary."""

    async def get(self, job_id: str) -> TelemetrySummaryRow | None:
        """Load summary row as a plain dict.  Returns None if not found."""
        result = await self._session.execute(
            text("SELECT * FROM job_telemetry_summary WHERE job_id = :job_id"),
            {"job_id": job_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return TelemetrySummaryRow(**dict(row))  # type: ignore[typeddict-item]

    async def query(
        self,
        *,
        period_days: int | None = None,
        sdk: str | None = None,
        model: str | None = None,
        status: str | None = None,
        repo: str | None = None,
        sort: str = "completed_at",
        desc: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TelemetrySummaryRow]:
        """Query summary rows with optional filters."""
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if period_days is not None:
            conditions.append(f"created_at >= datetime('now', '-{int(period_days)} days')")
        if sdk:
            conditions.append("sdk = :sdk")
            params["sdk"] = sdk
        if model:
            conditions.append("model = :model")
            params["model"] = model
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if repo:
            conditions.append("repo = :repo")
            params["repo"] = repo

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        allowed_sorts = {"completed_at", "created_at", "total_cost_usd", "duration_ms", "input_tokens"}
        sort_col = sort if sort in allowed_sorts else "completed_at"
        direction = "DESC" if desc else "ASC"

        result = await self._session.execute(
            text(
                f"SELECT * FROM job_telemetry_summary{where} "  # noqa: S608
                f"ORDER BY {sort_col} {direction} LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        return [cast("TelemetrySummaryRow", dict(r)) for r in result.mappings().all()]

    async def aggregate(self, *, period_days: int = 7) -> AggregateStats:
        """Return aggregate stats for the analytics overview."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_jobs,
                    SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) as review,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status IN ('review', 'completed') THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running,
                    COALESCE(SUM(total_cost_usd), 0) as total_cost_usd,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(SUM(premium_requests), 0) as total_premium_requests,
                    COALESCE(SUM(tool_call_count), 0) as total_tool_calls,
                    COALESCE(SUM(tool_failure_count), 0) as total_tool_failures,
                    COALESCE(SUM(agent_error_count), 0) as total_agent_errors,
                    COALESCE(SUM(cache_read_tokens), 0) as total_cache_read,
                    COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                    COALESCE(SUM(subagent_cost_usd), 0) as total_subagent_cost_usd,
                    COALESCE(SUM(retry_cost_usd), 0) as total_retry_cost_usd,
                    COALESCE(SUM(retry_count), 0) as total_retry_count
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
            """),
        )
        row = result.mappings().first()
        # COUNT/SUM without GROUP BY always returns a row, but guard defensively
        if not row:
            return AggregateStats()
        return cast("AggregateStats", dict(row))

    async def cost_by_day(self, *, period_days: int = 7) -> list[CostByDayRow]:
        """Return daily cost breakdown."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    date(created_at) as date,
                    COALESCE(SUM(total_cost_usd), 0) as cost,
                    COUNT(*) as jobs
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
                GROUP BY date(created_at)
                ORDER BY date(created_at)
            """),
        )
        return cast("list[CostByDayRow]", [dict(r) for r in result.mappings().all()])

    async def cost_by_repo(self, *, period_days: int = 7) -> list[CostByRepoRow]:
        """Return per-repo cost / job count / token breakdown."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    repo,
                    COUNT(*) as job_count,
                    SUM(CASE WHEN status IN ('review', 'completed') THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    COALESCE(SUM(total_cost_usd), 0) as total_cost_usd,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COALESCE(SUM(tool_call_count), 0) as tool_calls,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(SUM(premium_requests), 0) as premium_requests
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
                GROUP BY repo
                ORDER BY total_cost_usd DESC
            """),
        )
        return cast("list[CostByRepoRow]", [dict(r) for r in result.mappings().all()])

    async def cost_by_model(self, *, period_days: int = 7) -> list[CostByModelRow]:
        """Return per-model cost / job count / token breakdown with normalized metrics."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    model,
                    sdk,
                    COUNT(*) as job_count,
                    COALESCE(SUM(total_cost_usd), 0) as total_cost_usd,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COALESCE(SUM(input_tokens), 0) as input_tokens,
                    COALESCE(SUM(output_tokens), 0) as output_tokens,
                    COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(SUM(premium_requests), 0) as premium_requests,
                    COALESCE(SUM(total_turns), 0) as total_turns,
                    COALESCE(SUM(tool_call_count), 0) as total_tool_calls,
                    COALESCE(SUM(diff_lines_added + diff_lines_removed), 0) as total_diff_lines,
                    -- Normalized metrics
                    CASE WHEN COUNT(*) > 0
                        THEN COALESCE(SUM(total_cost_usd), 0) / COUNT(*)
                        ELSE 0 END as cost_per_job,
                    CASE WHEN SUM(duration_ms) > 0
                        THEN COALESCE(SUM(total_cost_usd), 0) / (SUM(duration_ms) / 60000.0)
                        ELSE 0 END as cost_per_minute,
                    CASE WHEN SUM(total_turns) > 0
                        THEN COALESCE(SUM(total_cost_usd), 0) / SUM(total_turns)
                        ELSE 0 END as cost_per_turn,
                    CASE WHEN SUM(tool_call_count) > 0
                        THEN COALESCE(SUM(total_cost_usd), 0) / SUM(tool_call_count)
                        ELSE 0 END as cost_per_tool_call,
                    CASE WHEN SUM(diff_lines_added + diff_lines_removed) > 0
                        THEN COALESCE(SUM(total_cost_usd), 0) / SUM(diff_lines_added + diff_lines_removed)
                        ELSE 0 END as cost_per_diff_line,
                    CASE WHEN SUM(input_tokens + output_tokens) > 0
                        THEN COALESCE(SUM(total_cost_usd), 0) / (SUM(input_tokens + output_tokens) / 1000000.0)
                        ELSE 0 END as cost_per_mtok,
                    CASE WHEN SUM(total_cost_usd) > 0
                        THEN COALESCE(SUM(cache_read_tokens), 0) * 1.0 / NULLIF(SUM(input_tokens), 0)
                        ELSE 0 END as cache_hit_rate
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
                    AND model != ''
                GROUP BY model, sdk
                ORDER BY total_cost_usd DESC
            """),
        )
        return cast("list[CostByModelRow]", [dict(r) for r in result.mappings().all()])

    # ------------------------------------------------------------------
    # Scorecard / resolution-joined queries
    # ------------------------------------------------------------------

    async def scorecard(self, *, period_days: int = 7) -> dict[str, Any]:
        """Budget per SDK, activity with resolution, quota, cost trend.

        Joins ``jobs`` table for resolution data that telemetry_summary lacks.
        """
        activity = await self._session.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_jobs,
                    SUM(CASE WHEN j.state = 'running' THEN 1 ELSE 0 END) as running,
                    SUM(CASE WHEN j.state = 'review' THEN 1 ELSE 0 END) as in_review,
                    SUM(CASE WHEN j.resolution = 'merged' THEN 1 ELSE 0 END) as merged,
                    SUM(CASE WHEN j.resolution = 'pr_created' THEN 1 ELSE 0 END) as pr_created,
                    SUM(CASE WHEN j.resolution = 'discarded' THEN 1 ELSE 0 END) as discarded,
                    SUM(CASE WHEN j.state = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN j.state = 'canceled' THEN 1 ELSE 0 END) as cancelled
                FROM jobs j
                WHERE j.created_at >= datetime('now', '-{int(period_days)} days')
            """),
        )
        activity_row = dict(activity.mappings().first() or {})

        budget = await self._session.execute(
            text(f"""
                SELECT
                    t.sdk,
                    COALESCE(SUM(t.total_cost_usd), 0) as total_cost_usd,
                    COALESCE(SUM(t.premium_requests), 0) as premium_requests,
                    COUNT(*) as job_count,
                    COALESCE(AVG(t.total_cost_usd), 0) as avg_cost_per_job,
                    COALESCE(AVG(t.duration_ms), 0) as avg_duration_ms
                FROM job_telemetry_summary t
                WHERE t.created_at >= datetime('now', '-{int(period_days)} days')
                GROUP BY t.sdk
            """),
        )
        budget_rows = [dict(r) for r in budget.mappings().all()]

        quota_row = await self._session.execute(
            text("""
                SELECT quota_json
                FROM job_telemetry_summary
                WHERE sdk = 'copilot' AND quota_json IS NOT NULL AND quota_json != ''
                ORDER BY updated_at DESC
                LIMIT 1
            """),
        )
        quota_json_raw = None
        qr = quota_row.mappings().first()
        if qr:
            quota_json_raw = qr.get("quota_json")

        cost_trend = await self.cost_by_day(period_days=period_days)

        return {
            "activity": activity_row,
            "budget": budget_rows,
            "quotaJson": quota_json_raw,
            "costTrend": cost_trend,
        }

    async def model_comparison(self, *, period_days: int = 30, repo: str | None = None) -> list[ModelComparisonRow]:
        """Per-model stats joined with resolution data from jobs table."""
        repo_filter = ""
        params: dict[str, Any] = {}
        if repo:
            repo_filter = "AND j.repo = :repo"
            params["repo"] = repo

        result = await self._session.execute(
            text(f"""
                SELECT
                    t.model,
                    t.sdk,
                    COUNT(*) as job_count,
                    COALESCE(AVG(t.total_cost_usd), 0) as avg_cost,
                    COALESCE(AVG(t.duration_ms), 0) as avg_duration_ms,
                    COALESCE(SUM(t.total_cost_usd), 0) as total_cost_usd,
                    COALESCE(SUM(t.premium_requests), 0) as premium_requests,
                    SUM(CASE WHEN j.resolution = 'merged' THEN 1 ELSE 0 END) as merged,
                    SUM(CASE WHEN j.resolution = 'pr_created' THEN 1 ELSE 0 END) as pr_created,
                    SUM(CASE WHEN j.resolution = 'discarded' THEN 1 ELSE 0 END) as discarded,
                    SUM(CASE WHEN j.state = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(CASE WHEN j.verify = 1 THEN t.total_turns ELSE NULL END) as avg_verify_turns,
                    SUM(CASE WHEN j.verify = 1 THEN 1 ELSE 0 END) as verify_job_count,
                    COALESCE(AVG(t.diff_lines_added + t.diff_lines_removed), 0) as avg_diff_lines,
                    CASE WHEN SUM(t.input_tokens) > 0
                        THEN COALESCE(SUM(t.cache_read_tokens), 0) * 1.0 / SUM(t.input_tokens)
                        ELSE 0 END as cache_hit_rate,
                    CASE WHEN COUNT(*) > 0
                        THEN COALESCE(SUM(t.total_cost_usd), 0) / COUNT(*)
                        ELSE 0 END as cost_per_job,
                    CASE WHEN SUM(t.duration_ms) > 0
                        THEN COALESCE(SUM(t.total_cost_usd), 0) / (SUM(t.duration_ms) / 60000.0)
                        ELSE 0 END as cost_per_minute,
                    CASE WHEN SUM(t.total_turns) > 0
                        THEN COALESCE(SUM(t.total_cost_usd), 0) / SUM(t.total_turns)
                        ELSE 0 END as cost_per_turn,
                    CASE WHEN SUM(t.tool_call_count) > 0
                        THEN COALESCE(SUM(t.total_cost_usd), 0) / SUM(t.tool_call_count)
                        ELSE 0 END as cost_per_tool_call
                FROM job_telemetry_summary t
                JOIN jobs j ON j.id = t.job_id
                WHERE t.created_at >= datetime('now', '-{int(period_days)} days')
                    AND t.model != ''
                    {repo_filter}
                GROUP BY t.model, t.sdk
                ORDER BY COUNT(*) DESC
            """),
            params,
        )
        return cast("list[ModelComparisonRow]", [dict(r) for r in result.mappings().all()])

    async def job_context(self, job_id: str) -> dict[str, Any] | None:
        """Job telemetry plus comparison against repo averages."""
        job_row = await self.get(job_id)
        if not job_row:
            return None

        repo = job_row.get("repo", "")
        repo_avg = await self._session.execute(
            text("""
                SELECT
                    COUNT(*) as job_count,
                    COALESCE(AVG(total_cost_usd), 0) as avg_cost,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(AVG(diff_lines_added + diff_lines_removed), 0) as avg_diff_lines
                FROM job_telemetry_summary
                WHERE repo = :repo
                    AND job_id != :job_id
                    AND status = 'completed'
            """),
            {"repo": repo, "job_id": job_id},
        )
        avg_row = dict(repo_avg.mappings().first() or {})

        flags: list[dict[str, str]] = []
        cost_first = job_row.get("cost_first_half_usd") or 0
        cost_second = job_row.get("cost_second_half_usd") or 0
        total_cost = cost_first + cost_second
        # Only flag escalation when the job spent enough for it to matter
        # and the 2nd half is significantly worse than the 1st
        if total_cost >= 0.50 and cost_first > 0 and cost_second > 2.0 * cost_first:
            pct = round(cost_second / total_cost * 100)
            msg = f"Cost escalation: {pct}% of spend in second half of turns"
            flags.append({"type": "turn_escalation", "message": msg})

        reread_count = job_row.get("file_reread_count") or 0
        if reread_count > 50:
            flags.append({"type": "high_rereads", "message": f"High file re-reads: {reread_count} re-reads detected"})

        tool_failures = job_row.get("tool_failure_count") or 0
        if tool_failures >= 5:
            suffix = "s" if tool_failures > 1 else ""
            flags.append({"type": "tool_failures", "message": f"{tool_failures} tool failure{suffix} during this job"})

        return {
            "job": {
                "cost": float(job_row.get("total_cost_usd") or 0),
                "durationMs": float(job_row.get("duration_ms") or 0),
                "diffLinesAdded": int(job_row.get("diff_lines_added") or 0),
                "diffLinesRemoved": int(job_row.get("diff_lines_removed") or 0),
                "sdk": job_row.get("sdk") or "",
                "model": job_row.get("model") or "",
                "totalTurns": int(job_row.get("total_turns") or 0),
                "peakTurnCostUsd": float(job_row.get("peak_turn_cost_usd") or 0),
                "avgTurnCostUsd": float(job_row.get("avg_turn_cost_usd") or 0),
                "costFirstHalfUsd": cost_first,
                "costSecondHalfUsd": cost_second,
            },
            "repoAvg": {
                "jobCount": int(avg_row.get("job_count") or 0),
                "avgCost": float(avg_row.get("avg_cost") or 0),
                "avgDurationMs": float(avg_row.get("avg_duration_ms") or 0),
                "avgDiffLines": float(avg_row.get("avg_diff_lines") or 0),
            }
            if (avg_row.get("job_count") or 0) >= 3
            else None,
            "flags": flags,
        }

    async def turn_escalation_jobs(self, *, period_days: int = 30) -> list[dict[str, Any]]:
        """Find jobs where cost/turn escalates significantly in the second half."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    job_id,
                    total_turns,
                    cost_first_half_usd,
                    cost_second_half_usd,
                    total_cost_usd
                FROM job_telemetry_summary
                WHERE total_turns >= 6
                    AND cost_second_half_usd > 0
                    AND cost_first_half_usd > 0
                    AND cost_second_half_usd >= 0.50
                    AND (cost_second_half_usd / cost_first_half_usd) >= 2.0
                    AND created_at >= datetime('now', '-{int(period_days)} days')
                ORDER BY (cost_second_half_usd - cost_first_half_usd) DESC
                LIMIT 20
            """)
        )
        return [dict(r) for r in result.mappings().all()]

    async def compaction_storm_jobs(self, *, period_days: int = 30) -> list[dict[str, Any]]:
        """Find jobs with excessive context compactions."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    job_id,
                    compactions,
                    tokens_compacted,
                    total_cost_usd,
                    total_turns
                FROM job_telemetry_summary
                WHERE compactions >= 5
                    AND created_at >= datetime('now', '-{int(period_days)} days')
                    AND status IN ('completed', 'failed')
                ORDER BY compactions DESC
                LIMIT 20
            """)
        )
        return [dict(r) for r in result.mappings().all()]

    async def cache_efficiency_periods(self) -> dict[str, Any]:
        """Compare cache hit rates between recent and prior 7-day periods."""
        result = await self._session.execute(
            text("""
                SELECT
                    SUM(CASE WHEN created_at >= datetime('now', '-7 days')
                        THEN cache_read_tokens ELSE 0 END) as recent_cache,
                    SUM(CASE WHEN created_at >= datetime('now', '-7 days')
                        THEN input_tokens ELSE 0 END) as recent_input,
                    SUM(CASE WHEN created_at < datetime('now', '-7 days')
                             AND created_at >= datetime('now', '-14 days')
                        THEN cache_read_tokens ELSE 0 END) as prior_cache,
                    SUM(CASE WHEN created_at < datetime('now', '-7 days')
                             AND created_at >= datetime('now', '-14 days')
                        THEN input_tokens ELSE 0 END) as prior_input,
                    COUNT(CASE WHEN created_at >= datetime('now', '-7 days')
                        THEN 1 END) as recent_jobs,
                    COUNT(CASE WHEN created_at < datetime('now', '-7 days')
                             AND created_at >= datetime('now', '-14 days')
                        THEN 1 END) as prior_jobs
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-14 days')
            """)
        )
        row = result.mappings().first()
        return dict(row) if row else {}
