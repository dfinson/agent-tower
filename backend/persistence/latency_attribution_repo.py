"""Persistence for per-job latency attribution breakdown.

Each row represents one slice of a job's latency — by category (llm/tool/idle),
activity, phase, or turn — enabling cross-job analysis of time bottlenecks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text

from backend.models.domain import FleetLatencyRow, LatencyAttributionRow
from backend.persistence.repository import BaseRepository


class LatencyAttributionRepository(BaseRepository):
    """Read/write for job_latency_attribution rows."""

    async def insert_batch(
        self,
        *,
        job_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """Replace all latency attribution rows for a job (delete + re-insert)."""
        await self.delete_for_job(job_id)
        if not rows:
            return
        now = datetime.now(UTC).isoformat()
        for row in rows:
            await self._session.execute(
                text("""
                    INSERT INTO job_latency_attribution
                        (job_id, dimension, bucket, wall_clock_ms, sum_duration_ms,
                         span_count, p50_ms, p95_ms, max_ms, pct_of_total, created_at)
                    VALUES
                        (:job_id, :dimension, :bucket, :wall_clock_ms, :sum_duration_ms,
                         :span_count, :p50_ms, :p95_ms, :max_ms, :pct_of_total, :now)
                """),
                {
                    "job_id": job_id,
                    "dimension": row.get("dimension", ""),
                    "bucket": row.get("bucket", ""),
                    "wall_clock_ms": row.get("wall_clock_ms", 0),
                    "sum_duration_ms": row.get("sum_duration_ms", 0),
                    "span_count": row.get("span_count", 0),
                    "p50_ms": row.get("p50_ms", 0),
                    "p95_ms": row.get("p95_ms", 0),
                    "max_ms": row.get("max_ms", 0),
                    "pct_of_total": row.get("pct_of_total", 0.0),
                    "now": now,
                },
            )
        await self._session.flush()

    async def delete_for_job(self, job_id: str) -> None:
        """Remove all latency attribution rows for a job (idempotent)."""
        await self._session.execute(
            text("DELETE FROM job_latency_attribution WHERE job_id = :job_id"),
            {"job_id": job_id},
        )
        await self._session.flush()

    async def for_job(self, job_id: str) -> list[LatencyAttributionRow]:
        """Fetch all latency attribution rows for a job."""
        result = await self._session.execute(
            text("""
                SELECT dimension, bucket, wall_clock_ms, sum_duration_ms,
                       span_count, p50_ms, p95_ms, max_ms, pct_of_total
                FROM job_latency_attribution
                WHERE job_id = :job_id
                ORDER BY dimension, wall_clock_ms DESC
            """),
            {"job_id": job_id},
        )
        return cast("list[LatencyAttributionRow]", [dict(r) for r in result.mappings().all()])

    async def fleet_summary(
        self, *, period_days: int = 30, dimension: str | None = None
    ) -> list[FleetLatencyRow]:
        """Fleet-wide latency breakdown aggregated across jobs."""
        dim_filter = "AND dimension = :dimension" if dimension else ""
        params: dict[str, Any] = {"limit": 100}
        if dimension:
            params["dimension"] = dimension
        result = await self._session.execute(
            text(f"""
                SELECT
                    dimension,
                    bucket,
                    AVG(wall_clock_ms) as avg_wall_clock_ms,
                    AVG(sum_duration_ms) as avg_sum_duration_ms,
                    SUM(span_count) as total_span_count,
                    COUNT(DISTINCT job_id) as job_count,
                    AVG(pct_of_total) as avg_pct_of_total
                FROM job_latency_attribution
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
                    {dim_filter}
                GROUP BY dimension, bucket
                ORDER BY avg_wall_clock_ms DESC
                LIMIT :limit
            """),
            params,
        )
        return cast("list[FleetLatencyRow]", [dict(r) for r in result.mappings().all()])

    async def job_duration_percentiles(self, *, period_days: int = 30) -> dict[str, Any]:
        """Compute avg/p50/p95 job durations from telemetry summaries."""
        result = await self._session.execute(
            text(f"""
                SELECT
                    AVG(duration_ms) as avg_ms,
                    COUNT(*) as job_count
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
                    AND duration_ms > 0
            """),
        )
        row = result.mappings().first()
        if not row or not row["job_count"]:
            return {"avg_ms": 0, "p50_ms": 0, "p95_ms": 0}

        # SQLite doesn't have native percentile functions — fetch sorted durations
        dur_result = await self._session.execute(
            text(f"""
                SELECT duration_ms
                FROM job_telemetry_summary
                WHERE created_at >= datetime('now', '-{int(period_days)} days')
                    AND duration_ms > 0
                ORDER BY duration_ms
            """),
        )
        durations = [r["duration_ms"] for r in dur_result.mappings().all()]
        n = len(durations)
        p50 = durations[n // 2] if n else 0
        p95 = durations[int(n * 0.95)] if n else 0

        return {
            "avg_ms": float(row["avg_ms"] or 0),
            "p50_ms": int(p50),
            "p95_ms": int(p95),
        }
