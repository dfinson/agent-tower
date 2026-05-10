"""Service layer for fleet analytics queries.

Wraps the individual analytics repositories behind a single injectable
service, consistent with the project convention that route handlers delegate
to services rather than constructing persistence objects directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.models.domain import (
        AggregateStats,
        CostAttributionRow,
        CostByDayRow,
        CostByModelRow,
        CostByRepoRow,
        CostDimensionRow,
        FileAccessRow,
        FileAccessStatsRow,
        FleetCostRow,
        ModelComparisonRow,
        RetryCostSummary,
        ShellCommandRow,
        TelemetrySummaryRow,
        ToolStatsRow,
    )
    from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsService:
    """Facade over the analytics persistence layer.

    Constructed per-request with a live ``AsyncSession`` (provided by
    the DI container).  Methods mirror the repository APIs that route
    handlers need.
    """

    _log = structlog.get_logger()

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Telemetry summary ---------------------------------------------------

    async def aggregate(self, *, period_days: int) -> AggregateStats:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).aggregate(period_days=period_days)

    async def cost_by_day(self, *, period_days: int) -> list[CostByDayRow]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).cost_by_day(period_days=period_days)

    async def cost_by_model(self, *, period_days: int) -> list[CostByModelRow]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).cost_by_model(period_days=period_days)

    async def cost_by_repo(self, *, period_days: int) -> list[CostByRepoRow]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).cost_by_repo(period_days=period_days)

    async def query_jobs(
        self,
        *,
        period_days: int,
        sdk: str | None = None,
        model: str | None = None,
        status: str | None = None,
        repo: str | None = None,
        sort: str = "completed_at",
        desc: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TelemetrySummaryRow]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).query(
            period_days=period_days,
            sdk=sdk,
            model=model,
            status=status,
            repo=repo,
            sort=sort,
            desc=desc,
            limit=limit,
            offset=offset,
        )

    async def scorecard(self, *, period_days: int) -> dict[str, Any]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).scorecard(period_days=period_days)

    async def model_comparison(
        self, *, period_days: int, repo: str | None = None,
    ) -> list[ModelComparisonRow]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).model_comparison(
            period_days=period_days, repo=repo,
        )

    async def job_context(self, job_id: str) -> dict[str, Any] | None:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).job_context(job_id)

    async def get_summary(self, job_id: str) -> TelemetrySummaryRow | None:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).get(job_id)

    # -- Telemetry spans -----------------------------------------------------

    async def tool_stats(self, *, period_days: int) -> list[ToolStatsRow]:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).tool_stats(period_days=period_days)

    async def tool_mix(self, *, period_days: int) -> dict:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).tool_mix(period_days=period_days)

    async def shell_command_breakdown(self, *, period_days: int) -> list[ShellCommandRow]:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).shell_command_breakdown(
            period_days=period_days,
        )

    async def retry_cost_summary(self, *, period_days: int) -> RetryCostSummary:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).retry_cost_summary(
            period_days=period_days,
        )

    # -- Cost attribution ----------------------------------------------------

    async def cost_drivers_for_job(self, job_id: str) -> list[CostAttributionRow]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).for_job(job_id)

    async def cost_by_dimension(
        self, dimension: str, *, period_days: int,
    ) -> list[CostDimensionRow]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).by_dimension(
            dimension, period_days=period_days,
        )

    async def fleet_cost_summary(self, *, period_days: int) -> list[FleetCostRow]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).fleet_summary(
            period_days=period_days,
        )

    # -- Latency attribution -------------------------------------------------

    async def fleet_latency_summary(
        self, *, period_days: int, dimension: str | None = None
    ) -> list[dict[str, Any]]:
        from backend.persistence.latency_attribution_repo import LatencyAttributionRepository

        rows = await LatencyAttributionRepository(self._session).fleet_summary(
            period_days=period_days, dimension=dimension,
        )
        return [dict(r) for r in rows]

    async def job_duration_percentiles(self, *, period_days: int) -> dict[str, Any]:
        from backend.persistence.latency_attribution_repo import LatencyAttributionRepository

        return await LatencyAttributionRepository(self._session).job_duration_percentiles(
            period_days=period_days,
        )

    # -- File access ---------------------------------------------------------

    async def reread_stats(self, job_id: str) -> FileAccessStatsRow:
        from backend.persistence.file_access_repo import FileAccessRepository

        return await FileAccessRepository(self._session).reread_stats(job_id)

    async def most_accessed_files(
        self,
        *,
        job_id: str | None = None,
        period_days: int | None = None,
    ) -> list[FileAccessRow]:
        from backend.persistence.file_access_repo import FileAccessRepository

        repo = FileAccessRepository(self._session)
        if job_id is not None:
            return await repo.most_accessed_files(job_id=job_id)
        return await repo.most_accessed_files(period_days=period_days or 30)

    # -- Observations --------------------------------------------------------

    async def list_observations(
        self,
        *,
        category: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:  # ObservationsRepository schema varies
        from backend.persistence.observations_repo import ObservationsRepository

        return await ObservationsRepository(self._session).list_active(
            category=category, severity=severity,
        )

    async def dismiss_observation(self, observation_id: int) -> None:
        from backend.persistence.observations_repo import ObservationsRepository

        await ObservationsRepository(self._session).dismiss(observation_id)

    # -- Yield / ROI (Item 2) -----------------------------------------------

    async def yield_summary(
        self, *, period_days: int, repo: str | None = None,
    ) -> dict[str, Any]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).yield_summary(
            period_days=period_days, repo=repo,
        )

    # -- Model efficiency (Item 6) ------------------------------------------

    async def model_efficiency(self, *, period_days: int) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).edit_efficiency_by_model(period_days)

    # -- Cache efficiency (Item 7) ------------------------------------------

    async def cache_efficiency(
        self, *, period_days: int, dimension: str = "phase",
    ) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        repo = CostAttributionRepository(self._session)
        if dimension == "activity":
            return await repo.cache_efficiency_by_activity(period_days)
        return await repo.cache_efficiency_by_phase(period_days)

    # -- Per-repo activity breakdown (Item 4) --------------------------------

    async def cost_by_repo_activity(
        self, *, period_days: int, dimension: str = "activity",
    ) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).by_dimension_per_repo(
            dimension, period_days,
        )

    # -- Monthly budget tracking (Item 5) ------------------------------------

    async def monthly_burn(self) -> dict[str, Any]:
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        return await TelemetryAnalyticsRepository(self._session).monthly_burn()

    async def enriched_scorecard(self, *, period_days: int) -> dict[str, Any]:
        """Scorecard with monthly budget, cost-per-line, and config enrichments."""
        from backend.config import load_config

        scorecard = await self.scorecard(period_days=period_days)
        cfg = load_config()
        scorecard["period"] = period_days
        scorecard["dailySpendLimitUsd"] = cfg.telemetry.daily_spend_limit_usd

        # Monthly budget data (Item 5)
        monthly = await self.monthly_burn()
        monthly_budget = cfg.telemetry.claude_monthly_budget_usd
        scorecard["monthly_budget_usd"] = monthly_budget
        scorecard["month_spend_usd"] = monthly["month_spend_usd"]
        scorecard["projected_month_end_usd"] = monthly["projected_month_end_usd"]
        scorecard["days_elapsed"] = monthly["days_elapsed"]
        scorecard["days_in_month"] = monthly["days_in_month"]
        scorecard["daily_avg_usd"] = monthly["daily_avg_usd"]
        scorecard["pct_monthly_budget_used"] = (
            monthly["month_spend_usd"] / monthly_budget if monthly_budget > 0 else 0.0
        )

        # Cost-per-diff-line (Item 9)
        budget_rows = scorecard.get("budget", [])
        period_total_cost = sum(b.get("total_cost_usd", 0) or 0 for b in budget_rows) if isinstance(budget_rows, list) else 0.0
        total_lines = await self.total_diff_lines(period_days=period_days)
        scorecard["cost_per_diff_line"] = period_total_cost / total_lines if total_lines > 0 else 0.0
        scorecard["total_diff_lines"] = total_lines

        # Compaction cost estimate (Item 13)
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        ta_repo = TelemetryAnalyticsRepository(self._session)
        compaction_tokens = await ta_repo.sum_compacted_tokens(period_days)
        # Use fleet avg input cost if available, else conservative estimate
        avg_input_rate = 0.000003  # ~$3/1M tokens
        scorecard["compaction_cost_usd"] = compaction_tokens * avg_input_rate
        scorecard["compaction_tokens"] = compaction_tokens

        return scorecard

    async def total_diff_lines(self, *, period_days: int) -> int:
        """Total diff lines (added + removed) across all jobs in the period."""
        from sqlalchemy import text as sa_text

        result = await self._session.execute(
            sa_text(
                "SELECT COALESCE(SUM(diff_lines_added + diff_lines_removed), 0) AS total_lines "
                "FROM job_telemetry_summary "
                "WHERE created_at >= datetime('now', '-' || :days || ' days')"
            ),
            {"days": int(period_days)},
        )
        row = result.mappings().first()
        return int((row or {}).get("total_lines", 0))

    # -- File cost (Item 14) -------------------------------------------------

    async def file_cost_fleet(
        self, *, period_days: int = 30, limit: int = 30,
    ) -> list[dict[str, Any]]:
        from backend.persistence.file_cost_repo import FileCostRepository

        return await FileCostRepository(self._session).fleet_top_files(
            period_days=period_days, limit=limit,
        )

    async def file_cost_for_job(self, job_id: str) -> list[dict[str, Any]]:
        from backend.persistence.file_cost_repo import FileCostRepository

        return await FileCostRepository(self._session).for_job(job_id)

    # -- Outcome matrix (Item 15) --------------------------------------------

    async def outcome_cost_matrix(
        self, *, period_days: int = 30,
    ) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).cost_by_activity_and_resolution(
            period_days=period_days,
        )

    # -- Activity × phase matrix (Item 16) -----------------------------------

    async def activity_phase_matrix(
        self, *, period_days: int = 30,
    ) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).fleet_activity_phase_matrix(
            period_days=period_days,
        )

    # -- Executive summary (Item 18) -----------------------------------------

    async def executive_summary(self, *, period_days: int = 30) -> dict[str, Any]:
        """3-bucket executive summary: building / thinking / wasted.

        Uses the action_purpose cross-tab when available, falling back to
        action-only classification if purpose data is sparse.
        """
        from backend.persistence.cost_attribution_repo import CostAttributionRepository
        from backend.persistence.telemetry_analytics_repo import TelemetryAnalyticsRepository

        attr_repo = CostAttributionRepository(self._session)
        summary_repo = TelemetryAnalyticsRepository(self._session)

        # Try action_purpose first (most precise)
        ap_rows = await attr_repo.by_dimension("action_purpose", period_days=period_days, limit=200)

        building = 0.0
        thinking = 0.0

        if ap_rows:
            # Building = advancing × (write|test|execute|delegate)
            # Thinking = (advancing|orienting) × (read|think)
            # Wasted = recovering × all + housekeeping × all
            building_actions = {"write", "test", "execute", "delegate"}
            thinking_actions = {"read", "think"}
            wasted_purposes = {"recovering", "housekeeping"}

            for row in ap_rows:
                bucket = row["bucket"]  # format: "action:purpose"
                parts = bucket.split(":", 1)
                if len(parts) != 2:
                    continue
                action, purpose = parts
                cost = row["cost_usd"]

                if purpose in wasted_purposes:
                    pass  # counted in waste below
                elif purpose == "advancing" and action in building_actions:
                    building += cost
                elif purpose == "verifying":
                    building += cost
                elif purpose in ("advancing", "orienting") and action in thinking_actions:
                    thinking += cost
                else:
                    # Unmatched — split between building and thinking
                    building += cost * 0.5
                    thinking += cost * 0.5
        else:
            # Fallback: use action dimension only
            action_rows = await attr_repo.by_dimension("action", period_days=period_days, limit=50)
            building_actions_fb = {"write", "test", "execute", "delegate", "vcs"}
            thinking_actions_fb = {"read", "think"}
            for row in action_rows:
                if row["bucket"] in building_actions_fb:
                    building += row["cost_usd"]
                elif row["bucket"] in thinking_actions_fb:
                    thinking += row["cost_usd"]

        waste = await summary_repo.fleet_waste_metrics(period_days=period_days)
        wasted = (
            waste["total_retry_cost_usd"]
            + waste["failed_discarded_cost_usd"]
            + waste["compaction_cost_estimate_usd"]
            + waste["reread_cost_estimate_usd"]
        )

        total = building + thinking + wasted

        return {
            "building_usd": building,
            "thinking_usd": thinking,
            "wasted_usd": wasted,
            "total_usd": total,
            "building_pct": round(building / total * 100, 1) if total > 0 else 0,
            "thinking_pct": round(thinking / total * 100, 1) if total > 0 else 0,
            "wasted_pct": round(wasted / total * 100, 1) if total > 0 else 0,
            "waste_breakdown": {
                "retry_usd": waste["total_retry_cost_usd"],
                "failed_jobs_usd": waste["failed_discarded_cost_usd"],
                "compaction_usd": waste["compaction_cost_estimate_usd"],
                "rereads_usd": waste["reread_cost_estimate_usd"],
            },
            "period_days": period_days,
        }
