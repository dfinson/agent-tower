"""Telemetry and artifact persistence extracted from RuntimeService.

This module handles:
- Initializing telemetry rows for new jobs
- Finalizing telemetry at job completion (cost attribution, statistical analysis)
- Storing post-completion artifacts (telemetry report, plan, approvals, logs)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import DBAPIError

from backend.models.api_schemas import ExecutionPhase
from backend.models.domain import JobState
from backend.models.events import DomainEvent, DomainEventKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.agent_adapter import AgentAdapterInterface
    from backend.services.event_bus import EventBus
    from backend.services.job_service import JobService
    from backend.services.trail import TrailService

log = structlog.get_logger()


class RuntimeTelemetry:
    """Encapsulates telemetry initialization, finalization, and artifact storage."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        make_job_service: object,  # callable(session) -> JobService
        resolve_adapter: object,  # callable(sdk) -> AgentAdapterInterface
        trail_service: TrailService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._make_job_service = make_job_service  # type: ignore[assignment]
        self._resolve_adapter = resolve_adapter  # type: ignore[assignment]
        self._trail_service = trail_service

    def set_trail_service(self, svc: TrailService) -> None:
        self._trail_service = svc

    async def init_telemetry_row(self, job_id: str, config: object) -> None:
        """Create the initial telemetry summary row for a job."""
        from backend.models.domain import SessionConfig

        assert isinstance(config, SessionConfig)
        try:
            async with self._session_factory() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                repo_path = ""
                branch_name = ""
                sdk_name = ""
                try:
                    svc = self._make_job_service(session)
                    job_for_tel = await svc.get_job(job_id)
                    if job_for_tel is not None:
                        repo_path = job_for_tel.repo or ""
                        branch_name = job_for_tel.branch or ""
                        sdk_name = job_for_tel.sdk or ""
                except DBAPIError:
                    log.warning("telemetry_init_job_lookup_failed", job_id=job_id, exc_info=True)
                await TelemetrySummaryRepository(session).init_job(
                    job_id,
                    sdk=sdk_name or "unknown",
                    model=config.model or "",
                    repo=repo_path,
                    branch=branch_name,
                )
                await session.commit()
        except (Exception, BaseException):
            log.warning("telemetry_init_failed", job_id=job_id, exc_info=True)

    async def finalize_job_telemetry(self, job_id: str, wall_start: float, config: object) -> None:
        """Finalize telemetry row, run cost attribution, store artifacts."""
        import time as _time

        from backend.models.domain import SessionConfig
        from backend.services import telemetry as tel
        from backend.services.parsing_utils import best_effort

        assert isinstance(config, SessionConfig)
        tel.end_job_span(job_id)

        # Emit finalization phase
        async with best_effort(log, "execution_phase_event", job_id=job_id):
            self._resolve_adapter(config.sdk).set_execution_phase(job_id, ExecutionPhase.finalization)
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=datetime.now(UTC),
                    kind=DomainEventKind.execution_phase_changed,
                    payload={"phase": ExecutionPhase.finalization},
                )
            )

        # Finalize the summary row with terminal status and duration.
        try:
            async with self._session_factory() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                _TELEMETRY_STATUS: dict[JobState, str] = {
                    JobState.failed: "failed",
                    JobState.canceled: "cancelled",
                    JobState.completed: "completed",
                }
                status = "review"
                async with best_effort(log, "telemetry_finalize_status_lookup", job_id=job_id):
                    svc = self._make_job_service(session)
                    job_final = await svc.get_job(job_id)
                    if job_final is not None:
                        status = _TELEMETRY_STATUS.get(job_final.state, "review")
                duration = int((_time.monotonic() - wall_start) * 1000)

                await TelemetrySummaryRepository(session).finalize(
                    job_id,
                    status=status,
                    duration_ms=duration,
                )
                await session.commit()

            # Run post-job cost attribution pipeline
            async with best_effort(log, "cost_attribution", level="warning", job_id=job_id):
                async with self._session_factory() as session:
                    from backend.services.cost_attribution import compute_attribution

                    await compute_attribution(session, job_id, session_factory=self._session_factory)
                    await session.commit()

            # Run statistical analysis (fire-and-forget, non-blocking)
            async with best_effort(log, "statistical_analysis", job_id=job_id):
                async with self._session_factory() as session:
                    from backend.services.statistical_analysis import run_analysis

                    await run_analysis(session)
                    await session.commit()

            # Signal clients that final telemetry is available
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=datetime.now(UTC),
                    kind=DomainEventKind.telemetry_updated,
                    payload={"job_id": job_id},
                )
            )
        except DBAPIError:
            log.warning("telemetry_finalize_failed", job_id=job_id, exc_info=True)

        # Store post-completion artifacts
        await self.store_post_completion_artifacts(job_id)

    async def store_post_completion_artifacts(self, job_id: str) -> None:
        """Persist internal state (telemetry, plan, approvals) as downloadable artifacts."""
        from backend.services.parsing_utils import best_effort

        try:
            # Look up job slug for human-friendly artifact names
            slug = ""
            async with best_effort(log, "slug_extraction", job_id=job_id):
                async with self._session_factory() as session:
                    svc = self._make_job_service(session)
                    job = await svc.get_job(job_id)
                if job is not None:
                    slug = (job.worktree_name or job.title or "").strip()

            async with self._session_factory() as session:
                from backend.persistence.artifact_repo import ArtifactRepository
                from backend.services.artifact_service import ArtifactService

                artifact_svc = ArtifactService(ArtifactRepository(session))

                # Telemetry report
                async with best_effort(log, "telemetry_artifact", job_id=job_id):
                    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                    summary = await TelemetrySummaryRepository(session).get(job_id)
                    if summary is not None:
                        await artifact_svc.store_telemetry_report(
                            job_id,
                            summary,
                            slug=slug,
                        )

                # Agent plan steps
                if self._trail_service is not None:
                    steps = self._trail_service.get_plan_steps(job_id)
                    if steps:
                        async with best_effort(log, "plan_artifact", job_id=job_id):
                            await artifact_svc.store_agent_plan(job_id, steps, slug=slug)

                # Approval history
                async with best_effort(log, "approval_artifact", job_id=job_id):
                    from backend.persistence.approval_repo import ApprovalRepository

                    approval_repo = ApprovalRepository(session)
                    approvals = await approval_repo.list_for_job(job_id)
                    if approvals:
                        approval_dicts = [
                            {
                                "id": a.id,
                                "description": a.description,
                                "proposed_action": a.proposed_action,
                                "requested_at": a.requested_at.isoformat(),
                                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
                                "resolution": a.resolution,
                            }
                            for a in approvals
                        ]
                        await artifact_svc.store_approval_history(
                            job_id,
                            approval_dicts,
                            slug=slug,
                        )

                # Agent log artifact
                async with best_effort(log, "log_artifact", job_id=job_id):
                    from backend.persistence.event_repo import EventRepository

                    event_repo = EventRepository(session)
                    log_events = await event_repo.list_all_by_job(job_id, [DomainEventKind.log_line_emitted])
                    if log_events:
                        await artifact_svc.store_log_artifact(
                            job_id,
                            [e.payload for e in log_events],
                            slug=slug,
                        )

                await session.commit()
        except DBAPIError:
            log.warning("post_completion_artifacts_failed", job_id=job_id, exc_info=True)
