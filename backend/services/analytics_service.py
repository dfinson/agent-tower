"""Service layer for fleet analytics queries.

Wraps the individual analytics repositories behind a single injectable
service, consistent with the project convention that route handlers delegate
to services rather than constructing persistence objects directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.models.domain import (
        AggregateStats,
        CostByDayRow,
        CostByModelRow,
        CostByRepoRow,
        TelemetrySummaryRow,
    )
    from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsService:
    """Facade over the analytics persistence layer.

    Constructed per-request with a live ``AsyncSession`` (provided by
    the DI container).  Methods mirror the repository APIs that route
    handlers need.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Telemetry summary ---------------------------------------------------

    async def aggregate(self, *, period_days: int) -> AggregateStats:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).aggregate(period_days=period_days)

    async def cost_by_day(self, *, period_days: int) -> list[CostByDayRow]:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).cost_by_day(period_days=period_days)

    async def cost_by_model(self, *, period_days: int) -> list[CostByModelRow]:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).cost_by_model(period_days=period_days)

    async def cost_by_repo(self, *, period_days: int) -> list[CostByRepoRow]:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).cost_by_repo(period_days=period_days)

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
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).query(
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
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).scorecard(period_days=period_days)

    async def model_comparison(
        self, *, period_days: int, repo: str | None = None,
    ) -> list[dict[str, Any]]:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).model_comparison(
            period_days=period_days, repo=repo,
        )

    async def job_context(self, job_id: str) -> dict[str, Any] | None:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).job_context(job_id)

    async def get_summary(self, job_id: str) -> TelemetrySummaryRow | None:
        from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

        return await TelemetrySummaryRepository(self._session).get(job_id)

    # -- Telemetry spans -----------------------------------------------------

    async def tool_stats(self, *, period_days: int) -> list[dict[str, Any]]:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).tool_stats(period_days=period_days)

    async def shell_command_breakdown(self, *, period_days: int) -> list[dict[str, Any]]:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).shell_command_breakdown(
            period_days=period_days,
        )

    async def retry_cost_summary(self, *, period_days: int) -> dict[str, Any]:
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

        return await TelemetrySpansRepository(self._session).retry_cost_summary(
            period_days=period_days,
        )

    # -- Cost attribution ----------------------------------------------------

    async def cost_drivers_for_job(self, job_id: str) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).for_job(job_id)

    async def cost_by_dimension(
        self, dimension: str, *, period_days: int,
    ) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).by_dimension(
            dimension, period_days=period_days,
        )

    async def fleet_cost_summary(self, *, period_days: int) -> list[dict[str, Any]]:
        from backend.persistence.cost_attribution_repo import CostAttributionRepository

        return await CostAttributionRepository(self._session).fleet_summary(
            period_days=period_days,
        )

    # -- File access ---------------------------------------------------------

    async def reread_stats(self, job_id: str) -> dict[str, Any]:
        from backend.persistence.file_access_repo import FileAccessRepository

        return await FileAccessRepository(self._session).reread_stats(job_id)

    async def most_accessed_files(
        self,
        *,
        job_id: str | None = None,
        period_days: int | None = None,
    ) -> list[dict[str, Any]]:
        from backend.persistence.file_access_repo import FileAccessRepository

        repo = FileAccessRepository(self._session)
        if job_id is not None:
            return await repo.most_accessed_files(job_id=job_id)
        return await repo.most_accessed_files(period_days=period_days)

    # -- Observations --------------------------------------------------------

    async def list_observations(
        self,
        *,
        category: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        from backend.persistence.observations_repo import ObservationsRepository

        return await ObservationsRepository(self._session).list_active(
            category=category, severity=severity,
        )

    async def dismiss_observation(self, observation_id: int) -> None:
        from backend.persistence.observations_repo import ObservationsRepository

        await ObservationsRepository(self._session).dismiss(observation_id)
