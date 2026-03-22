"""Persistence for job telemetry snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from backend.models.db import JobMetricsRow
from backend.persistence.repository import BaseRepository


class MetricsRepository(BaseRepository):
    """Read/write cumulative telemetry snapshots for jobs."""

    async def save_snapshot(self, job_id: str, snapshot: dict[str, object]) -> None:
        """Upsert the metrics snapshot for *job_id*.

        A single row is kept per job (primary key = job_id).  Each call
        overwrites the previous snapshot so the row always reflects the
        full cumulative metrics at the end of the latest session.
        """
        result = await self._session.execute(select(JobMetricsRow).where(JobMetricsRow.job_id == job_id))
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            row = JobMetricsRow(
                job_id=job_id,
                snapshot_json=json.dumps(snapshot),
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.snapshot_json = json.dumps(snapshot)
            row.updated_at = now
        await self._session.flush()

    async def load_snapshot(self, job_id: str) -> dict[str, object] | None:
        """Return the persisted metrics snapshot for *job_id*, or ``None``."""
        result = await self._session.execute(select(JobMetricsRow).where(JobMetricsRow.job_id == job_id))
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return json.loads(str(row.snapshot_json))
