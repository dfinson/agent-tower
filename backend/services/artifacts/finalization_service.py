"""Idempotent terminal artifact collection orchestration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

import structlog

from backend.models.events import EventKind, new_event
from backend.persistence.database import serialized_write
from backend.persistence.job_repo import JobRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.completers.summarization_service import SummarizationService
    from backend.services.events.event_bus import EventBus
    from backend.services.runtime.telemetry import RuntimeTelemetry

log = structlog.get_logger()


class ArtifactFinalizationService:
    """Collect all terminal artifacts once per job session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        summarization_service: SummarizationService | None,
        telemetry: RuntimeTelemetry,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._summarization_service = summarization_service
        self._telemetry = telemetry
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def finalize(self, job_id: str, *, recover_stale: bool = False) -> str:
        """Finalize artifacts and return the durable collection status."""
        lock = self._locks.setdefault(job_id, asyncio.Lock())
        async with lock:
            now = datetime.now(UTC)
            async with serialized_write(self._session_factory) as session:
                job = await JobRepository(session).claim_artifact_collection(
                    job_id,
                    updated_at=now,
                    allow_stale=recover_stale,
                )
            if job is None:
                async with self._session_factory() as session:
                    current = await JobRepository(session).get(job_id)
                return current.artifact_collection_status if current is not None else "pending"

            try:
                if self._summarization_service is None:
                    raise RuntimeError("Summarization service is unavailable")
                await self._summarization_service.save_snapshot_to_disk(job_id)
                await self._telemetry.store_post_completion_artifacts(job_id)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:2000]
                await self._finish(job_id, status="failed", error=error, session_count=job.session_count)
                log.error("artifact_collection_failed", job_id=job_id, error=error, exc_info=True)
                await self._publish(job_id, status="failed", error=error)
                return "failed"

            await self._finish(job_id, status="completed", error=None, session_count=job.session_count)
            await self._publish(job_id, status="completed", error=None)
            log.info("artifact_collection_completed", job_id=job_id, session_count=job.session_count)
            return "completed"

    async def recover_eligible(self) -> int:
        """Backfill terminal jobs without a completed current-session attempt."""
        async with self._session_factory() as session:
            job_ids = await JobRepository(session).list_artifact_collection_candidates()
        recovered = 0
        for job_id in job_ids:
            if await self.finalize(job_id, recover_stale=True) == "completed":
                recovered += 1
        if job_ids:
            log.info("artifact_collection_recovery_finished", candidates=len(job_ids), completed=recovered)
        return recovered

    async def _finish(self, job_id: str, *, status: str, error: str | None, session_count: int) -> None:
        async with serialized_write(self._session_factory) as session:
            await JobRepository(session).finish_artifact_collection(
                job_id,
                status=status,
                error=error,
                session_count=session_count,
                updated_at=datetime.now(UTC),
            )

    async def _publish(self, job_id: str, *, status: str, error: str | None) -> None:
        await self._event_bus.publish(
            new_event(
                session_id=job_id,
                kind=EventKind.artifacts_updated,
                payload={
                    "job_id": job_id,
                    "collection_status": status,
                    "collection_error": error,
                },
            )
        )
