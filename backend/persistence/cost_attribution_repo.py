"""Persistence for per-job cost attribution breakdown.

Each row represents one slice of a job's cost — by phase, tool category,
or other dimension — enabling cross-job analysis of what drives cost.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text

from backend.models.domain import CostAttributionRow, CostDimensionRow, FleetCostRow
from backend.persistence.repository import BaseRepository


class CostAttributionRepository(BaseRepository):
    """Read/write for job_cost_attribution rows."""

    async def insert(
        self,
        *,
        job_id: str,
        dimension: str,
        bucket: str,
        cost_usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        call_count: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        model: str | None = None,
    ) -> None:
        """Insert a single attribution row."""
        now = datetime.now(UTC).isoformat()
        await self._session.execute(
            text("""
                INSERT INTO job_cost_attribution
                    (job_id, dimension, bucket, cost_usd, input_tokens, output_tokens,
                     call_count, cache_read_tokens, cache_write_tokens, model, created_at)
                VALUES
                    (:job_id, :dimension, :bucket, :cost_usd, :input_tokens, :output_tokens,
                     :call_count, :cache_read_tokens, :cache_write_tokens, :model, :now)
            """),
            {
                "job_id": job_id,
                "dimension": dimension,
                "bucket": bucket,
                "cost_usd": cost_usd,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "call_count": call_count,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
                "model": model,
                "now": now,
            },
        )
        await self._session.flush()

    async def delete_for_job(self, job_id: str) -> None:
        """Remove all attribution rows for a job (idempotent)."""
        await self._session.execute(
            text("DELETE FROM job_cost_attribution WHERE job_id = :job_id"),
            {"job_id": job_id},
        )
        await self._session.flush()

    async def insert_batch(
        self,
        *,
        job_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """Replace all attribution rows for a job (delete + re-insert)."""
        await self.delete_for_job(job_id)
        if not rows:
            return
        now = datetime.now(UTC).isoformat()
        for row in rows:
            await self._session.execute(
                text("""
                    INSERT INTO job_cost_attribution
                        (job_id, dimension, bucket, cost_usd, input_tokens, output_tokens,
                         call_count, cache_read_tokens, cache_write_tokens, model, created_at)
                    VALUES
                        (:job_id, :dimension, :bucket, :cost_usd, :input_tokens, :output_tokens,
                         :call_count, :cache_read_tokens, :cache_write_tokens, :model, :now)
                """),
                {
                    "job_id": job_id,
                    "dimension": row.get("dimension", ""),
                    "bucket": row.get("bucket", ""),
                    "cost_usd": row.get("cost_usd", 0.0),
                    "input_tokens": row.get("input_tokens", 0),
                    "output_tokens": row.get("output_tokens", 0),
                    "call_count": row.get("call_count", 0),
                    "cache_read_tokens": row.get("cache_read_tokens", 0),
                    "cache_write_tokens": row.get("cache_write_tokens", 0),
                    "model": row.get("model"),
                    "now": now,
                },
            )
        await self._session.flush()

    async def for_job(self, job_id: str) -> list[CostAttributionRow]:
        """Fetch all attribution rows for a job."""
        result = await self._session.execute(
            text("""
                SELECT id, job_id, dimension, bucket, cost_usd,
                       input_tokens, output_tokens, call_count, created_at
                FROM job_cost_attribution
                WHERE job_id = :job_id
                ORDER BY dimension, cost_usd DESC
            """),
            {"job_id": job_id},
        )
        return cast("list[CostAttributionRow]", [dict(r) for r in result.mappings().all()])

    async def by_dimension(
        self,
        dimension: str,
        *,
        period_days: int = 30,
        limit: int = 50,
    ) -> list[CostDimensionRow]:
        """Aggregate attribution across jobs for a given dimension."""
        result = await self._session.execute(
            text("""
                SELECT
                    bucket,
                    SUM(cost_usd) as cost_usd,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(call_count) as call_count,
                    COUNT(DISTINCT job_id) as job_count
                FROM job_cost_attribution
                WHERE dimension = :dimension
                    AND created_at >= datetime('now', '-' || :days || ' days')
                GROUP BY bucket
                ORDER BY cost_usd DESC
                LIMIT :limit
            """),
            {"dimension": dimension, "days": int(period_days), "limit": limit},
        )
        return cast("list[CostDimensionRow]", [dict(r) for r in result.mappings().all()])

    async def fleet_summary(self, *, period_days: int = 30) -> list[FleetCostRow]:
        """Cross-job summary: top cost buckets across all dimensions."""
        result = await self._session.execute(
            text("""
                SELECT
                    dimension,
                    bucket,
                    SUM(cost_usd) as cost_usd,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(call_count) as call_count,
                    COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) as cache_write_tokens,
                    COUNT(DISTINCT job_id) as job_count,
                    AVG(cost_usd) as avg_cost_per_job
                FROM job_cost_attribution
                WHERE created_at >= datetime('now', '-' || :days || ' days')
                GROUP BY dimension, bucket
                ORDER BY cost_usd DESC
                LIMIT 100
            """),
            {"days": int(period_days)},
        )
        return cast("list[FleetCostRow]", [dict(r) for r in result.mappings().all()])

    async def edit_efficiency_by_model(
        self, period_days: int,
    ) -> list[dict[str, Any]]:
        """Edit efficiency aggregated per model."""
        result = await self._session.execute(
            text("""
                SELECT
                    a.model,
                    SUM(a.call_count) AS edit_turns,
                    SUM(a.input_tokens) AS one_shot_turns,
                    SUM(a.output_tokens) AS retries,
                    CASE WHEN SUM(a.call_count) > 0
                        THEN SUM(a.input_tokens) * 1.0 / SUM(a.call_count)
                        ELSE 0 END AS one_shot_rate,
                    CASE WHEN SUM(a.call_count) > 0
                        THEN SUM(a.output_tokens) * 1.0 / SUM(a.call_count)
                        ELSE 0 END AS retry_rate,
                    COUNT(DISTINCT a.job_id) AS job_count
                FROM job_cost_attribution a
                JOIN jobs j ON j.id = a.job_id
                WHERE a.dimension = 'edit_efficiency'
                    AND j.created_at >= datetime('now', '-' || :days || ' days')
                    AND a.model IS NOT NULL AND a.model != ''
                GROUP BY a.model
                ORDER BY one_shot_rate DESC
            """),
            {"days": int(period_days)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def cache_efficiency_by_phase(
        self, period_days: int,
    ) -> list[dict[str, Any]]:
        """Cache hit rate aggregated by execution phase from spans."""
        result = await self._session.execute(
            text("""
                SELECT
                    s.execution_phase AS bucket,
                    SUM(s.input_tokens) AS total_input_tokens,
                    COALESCE(SUM(s.cache_read_tokens), 0) AS total_cache_read_tokens,
                    COALESCE(SUM(s.cache_write_tokens), 0) AS total_cache_write_tokens,
                    CASE WHEN SUM(s.input_tokens) > 0
                        THEN COALESCE(SUM(s.cache_read_tokens), 0) * 1.0 / SUM(s.input_tokens)
                        ELSE 0 END AS cache_hit_rate,
                    COUNT(DISTINCT s.job_id) AS job_count
                FROM telemetry_spans s
                JOIN jobs j ON j.id = s.job_id
                WHERE s.span_type = 'llm'
                    AND j.created_at >= datetime('now', '-' || :days || ' days')
                    AND s.execution_phase IS NOT NULL
                GROUP BY s.execution_phase
                ORDER BY cache_hit_rate DESC
            """),
            {"days": int(period_days)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def cache_efficiency_by_activity(
        self, period_days: int,
    ) -> list[dict[str, Any]]:
        """Cache hit rate aggregated by activity bucket from attribution."""
        result = await self._session.execute(
            text("""
                SELECT
                    a.bucket,
                    SUM(a.input_tokens) AS total_input_tokens,
                    COALESCE(SUM(a.cache_read_tokens), 0) AS total_cache_read_tokens,
                    COALESCE(SUM(a.cache_write_tokens), 0) AS total_cache_write_tokens,
                    CASE WHEN SUM(a.input_tokens) > 0
                        THEN COALESCE(SUM(a.cache_read_tokens), 0) * 1.0 / SUM(a.input_tokens)
                        ELSE 0 END AS cache_hit_rate,
                    COUNT(DISTINCT a.job_id) AS job_count
                FROM job_cost_attribution a
                JOIN jobs j ON j.id = a.job_id
                WHERE a.dimension = 'activity'
                    AND j.created_at >= datetime('now', '-' || :days || ' days')
                GROUP BY a.bucket
                ORDER BY cache_hit_rate DESC
            """),
            {"days": int(period_days)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def by_dimension_per_repo(
        self, dimension: str, period_days: int,
    ) -> list[dict[str, Any]]:
        """Activity cost broken down by repo."""
        result = await self._session.execute(
            text("""
                SELECT
                    j.repo,
                    a.bucket,
                    SUM(a.cost_usd) AS cost_usd,
                    SUM(a.input_tokens) AS input_tokens,
                    SUM(a.output_tokens) AS output_tokens,
                    COALESCE(SUM(a.cache_read_tokens), 0) AS cache_read_tokens,
                    COALESCE(SUM(a.cache_write_tokens), 0) AS cache_write_tokens,
                    SUM(a.call_count) AS call_count,
                    COUNT(DISTINCT a.job_id) AS job_count
                FROM job_cost_attribution a
                JOIN jobs j ON j.id = a.job_id
                WHERE a.dimension = :dimension
                    AND j.created_at >= datetime('now', '-' || :days || ' days')
                GROUP BY j.repo, a.bucket
                ORDER BY cost_usd DESC
            """),
            {"dimension": dimension, "days": int(period_days)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def communication_heavy_jobs(
        self, period_days: int,
    ) -> list[dict[str, Any]]:
        """Jobs where communication + reasoning cost > threshold of total."""
        result = await self._session.execute(
            text("""
                SELECT
                    a.job_id,
                    SUM(CASE WHEN a.bucket IN ('communication', 'reasoning')
                        THEN a.cost_usd ELSE 0 END) AS comm_cost,
                    SUM(a.cost_usd) AS total_cost,
                    CASE WHEN SUM(a.cost_usd) > 0
                        THEN SUM(CASE WHEN a.bucket IN ('communication', 'reasoning')
                            THEN a.cost_usd ELSE 0 END) / SUM(a.cost_usd)
                        ELSE 0 END AS comm_pct
                FROM job_cost_attribution a
                JOIN jobs j ON j.id = a.job_id
                WHERE a.dimension = 'activity'
                    AND j.created_at >= datetime('now', '-' || :days || ' days')
                GROUP BY a.job_id
                HAVING comm_pct > 0.30
                ORDER BY comm_cost DESC
            """),
            {"days": int(period_days)},
        )
        return [dict(r) for r in result.mappings().all()]
