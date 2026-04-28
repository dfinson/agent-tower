"""Long-running job execution manager.

RuntimeService orchestrates the full lifecycle of agent jobs: session creation,
event streaming, heartbeat monitoring, diff tracking, approval flow,
cancellation, and post-job cleanup.

Progress tracking (plan management, turn classification, title generation,
activity grouping) is handled by ``TrailService`` — see
``backend/services/trail_service.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
from dataclasses import dataclass, replace as dataclass_replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy.exc import DBAPIError

from backend.config import DEFAULT_SELF_REVIEW_PROMPT, DEFAULT_VERIFY_PROMPT, build_session_config
from backend.models.api_schemas import ExecutionPhase, TranscriptRole
from backend.models.domain import (
    TERMINAL_STATES,
    ApprovalResolution,
    CodePlaneError,
    Job,
    JobNotFoundError,
    JobSpec,
    JobState,
    Resolution,
    ServiceInitError,
    SessionConfig,
    SessionEvent,
    SessionEventKind,
    StateConflictError,
)
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.job_repo import JobRepository
from backend.services.job_service import JobService
from backend.services.runtime_handoff import (
    build_followup_handoff_prompt_for_job,
    build_resume_handoff_prompt_for_job,
    load_handoff_context_for_job,
)
from backend.services.runtime_telemetry import RuntimeTelemetry
from backend.validators import REF_PATTERN

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from backend.services.step_tracker import StepTracker
    from backend.services.terminal_service import TerminalService
    from backend.services.trail import TrailService


class _AgentSession:
    """Thin wrapper around the adapter for a single running agent session."""

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._adapter: AgentAdapterInterface | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def execute(
        self,
        config: SessionConfig,
        adapter: AgentAdapterInterface,
    ) -> AsyncIterator[SessionEvent]:
        self._adapter = adapter
        self._session_id = await adapter.create_session(config)
        async for event in adapter.stream_events(self._session_id):
            yield event

    async def send_message(self, message: str) -> None:
        if self._adapter and self._session_id:
            await self._adapter.send_message(self._session_id, message)

    async def interrupt(self) -> None:
        if self._adapter and self._session_id:
            await self._adapter.interrupt_session(self._session_id)

    def pause_tools(self) -> None:
        if self._adapter and self._session_id:
            self._adapter.pause_tools(self._session_id)

    def resume_tools(self) -> None:
        if self._adapter and self._session_id:
            self._adapter.resume_tools(self._session_id)

    async def abort(self) -> None:
        if self._adapter and self._session_id:
            await self._adapter.abort_session(self._session_id)


class _EventAction(enum.Enum):
    """Action directive returned by ``_process_agent_event``."""

    skip = enum.auto()
    publish = enum.auto()
    abort = enum.auto()


@dataclass(frozen=True, slots=True)
class _SessionAttemptResult:
    """Outcome of a single ``_execute_session_attempt`` call."""

    session_id: str | None = None
    error_reason: str | None = None
    made_progress: bool = False
    downgrade: tuple[str, str] | None = None  # (requested, actual) model names


@dataclass(frozen=True, slots=True)
class _RecoverySnapshot:
    """Pre-recovery job state for rollback on failure."""

    state: JobState
    session_count: int
    completed_at: datetime | None
    resolution: str | None
    failure_reason: str | None
    archived_at: datetime | None
    merge_status: str | None
    pr_url: str | None


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.services.adapter_registry import AdapterRegistry
    from backend.services.agent_adapter import AgentAdapterInterface
    from backend.services.approval_service import ApprovalService
    from backend.services.diff_service import DiffService
    from backend.services.event_bus import EventBus
    from backend.services.git_service import GitService
    from backend.services.merge_service import MergeService
    from backend.services.platform_adapter import PlatformRegistry
    from backend.services.sister_session import SisterSessionManager
    from backend.services.summarization_service import SummarizationService

log = structlog.get_logger()

_SERVER_RESTART_RECOVERY_INSTRUCTION = (
    "The CodePlane server restarted while this job was in progress. "
    "Resume this existing job in place from the current worktree and prior context. "
    "Do not start over or create a duplicate job."
)

_DEFAULT_RESUME_INSTRUCTION = "Continue the current task from where you left off and finish it."

# Heartbeat configuration
_HEARTBEAT_INTERVAL_S = 30


def _session_event_counts_as_resume_progress(event: SessionEvent) -> bool:
    """Return True once a resumed session has produced real agent work."""
    if event.kind in (
        SessionEventKind.file_changed,
        SessionEventKind.approval_request,
        SessionEventKind.model_downgraded,
    ):
        return True
    if event.kind != SessionEventKind.transcript:
        return False
    role = str(event.payload.get("role", ""))
    return role != TranscriptRole.operator


def _normalize_resume_instruction(instruction: str | None) -> str:
    """Return a default continue instruction when the operator doesn't provide one."""
    normalized = (instruction or "").strip()
    return normalized or _DEFAULT_RESUME_INSTRUCTION


class RuntimeService:
    """Manages active job tasks, capacity enforcement, and queueing."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        adapter_registry: AdapterRegistry,
        config: CPLConfig,
        approval_service: ApprovalService | None = None,
        diff_service: DiffService | None = None,
        git_service: GitService | None = None,
        merge_service: MergeService | None = None,
        summarization_service: SummarizationService | None = None,
        platform_registry: PlatformRegistry | None = None,
        sister_sessions: SisterSessionManager | None = None,
        step_tracker: StepTracker | None = None,
        trail_service: TrailService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._adapter_registry = adapter_registry
        self._config = config
        self._approval_service = approval_service
        self._diff_service = diff_service
        self._git_service = git_service
        self._merge_service = merge_service
        self._summarization_service = summarization_service
        self._platform_registry = platform_registry
        self._sister_sessions = sister_sessions
        self._step_tracker = step_tracker
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._agent_sessions: dict[str, _AgentSession] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        self._last_activity: dict[str, float] = {}
        self._waiting_for_approval: set[str] = set()
        self._session_ids: dict[str, str] = {}
        self._permission_overrides: dict[str, str] = {}  # job_id → permission_mode
        self._dequeue_lock = asyncio.Lock()
        self._shutting_down = False
        self._snapshot_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_starts: dict[str, tuple[str | None, str | None]] = {}
        self._queued_override_prompts: dict[str, str] = {}
        self._queued_resume_session_ids: dict[str, str] = {}
        # Contents to suppress when the SDK echoes them back (already published locally)
        self._echo_suppress: dict[str, set[str]] = {}
        # Trail service (unified timeline, plan, activity tracking)
        self._trail_service = trail_service
        # Observer terminals: job_id → terminal session ID
        self._terminal_service: TerminalService | None = None
        self._observer_terminals: dict[str, str] = {}
        # Telemetry subsystem (extracted)
        self._telemetry = RuntimeTelemetry(
            session_factory=session_factory,
            event_bus=event_bus,
            make_job_service=self._make_job_service,
            resolve_adapter=self._resolve_adapter,
            trail_service=trail_service,
        )

    def set_trail_service(self, svc: TrailService) -> None:
        """Wire the TrailService for plan/activity tracking (late binding)."""
        self._trail_service = svc
        self._telemetry.set_trail_service(svc)

    def set_terminal_service(self, svc: TerminalService) -> None:
        """Wire the TerminalService for agent observer terminals."""
        self._terminal_service = svc
        svc.set_observer_interrupt_callback(self._handle_observer_interrupt)

    async def _handle_observer_interrupt(self, job_id: str) -> bool:
        """Callback from TerminalService when Ctrl+C is received on an observer terminal."""
        return await self.interrupt(job_id)

    def _resolve_adapter(self, sdk: str) -> AgentAdapterInterface:
        """Resolve the adapter for a given SDK via the registry."""
        return self._adapter_registry.get_adapter(sdk)

    def _make_job_service(self, session: AsyncSession) -> JobService:
        return JobService(
            job_repo=JobRepository(session),
            git_service=self._git_service,
            config=self._config,
            event_bus=self._event_bus,
        )

    async def _finalize_diff_safe(self, job_id: str, worktree_path: str | None, base_ref: str | None) -> None:
        """Finalize the diff snapshot, swallowing exceptions."""
        if self._diff_service is None or not worktree_path or not base_ref:
            return
        try:
            await self._diff_service.finalize(job_id, worktree_path, base_ref)
        except (Exception, asyncio.CancelledError):
            log.warning("diff_finalize_failed", job_id=job_id, exc_info=True)

    @property
    def running_count(self) -> int:
        """Number of currently running job tasks."""
        return len(self._tasks)

    @property
    def max_concurrent(self) -> int:
        return self._config.runtime.max_concurrent_jobs

    async def setup_and_start(
        self,
        job: Job,
        permission_mode: str | None = None,
        session_token: str | None = None,
    ) -> Job:
        """Background task: create worktree for a ``preparing`` job then start it.

        Uses a dedicated DB session so this can run after the HTTP response.
        Publishes ``job_state_changed`` when transitioning to ``queued``.
        If any step fails, the job is transitioned to ``failed`` so the user
        sees the error instead of a stuck-in-preparing state.
        """

        try:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                updated_job = await svc.setup_workspace(job.id)
                await session.commit()

            if updated_job.state == JobState.failed:
                await self._publish_state_event(job.id, JobState.preparing, JobState.failed)
                return updated_job

            # Publish preparing → queued transition
            await self._publish_state_event(job.id, JobState.preparing, JobState.queued)

            await self.start_or_enqueue(
                updated_job,
                permission_mode=permission_mode,
                session_token=session_token,
            )
            return updated_job
        except Exception:
            log.error("setup_and_start_failed", job_id=job.id, exc_info=True)
            await self._fail_job(job.id, "Job setup failed")
            raise

    async def start_or_enqueue(
        self,
        job: Job,
        override_prompt: str | None = None,
        resume_sdk_session_id: str | None = None,
        permission_mode: str | None = None,
        session_token: str | None = None,
    ) -> None:
        """Start the job if capacity allows, otherwise keep it queued."""
        if permission_mode:
            self._permission_overrides[job.id] = permission_mode

        # Adopt or create the sister session for this job
        if self._sister_sessions is not None:
            try:
                if session_token:
                    self._sister_sessions.adopt(session_token, job.id)
                else:
                    self._sister_sessions.create_for_job(job.id)
            except Exception:
                log.warning("sister_session_setup_failed", job_id=job.id, exc_info=True)

        if self._shutting_down:
            log.warning("job_rejected_shutting_down", job_id=job.id)
            return
        async with self._dequeue_lock:
            if self.running_count < self.max_concurrent:
                await self._start_job(job, override_prompt=override_prompt, resume_sdk_session_id=resume_sdk_session_id)
                return

            # At capacity — queue the job
            if job.state != JobState.queued:
                self._pending_starts[job.id] = (override_prompt, resume_sdk_session_id)
                log.info("job_waiting_for_capacity", job_id=job.id, state=job.state, running=self.running_count)
                return

            if override_prompt is not None:
                self._queued_override_prompts[job.id] = override_prompt
            if resume_sdk_session_id is not None:
                self._queued_resume_session_ids[job.id] = resume_sdk_session_id
            log.info("job_enqueued", job_id=job.id, running=self.running_count)

    async def _ensure_resumable_worktree(self, job_repo: JobRepository, job: Job) -> Job:
        """Ensure a job has a usable worktree before resuming or recovering it."""
        from pathlib import Path

        from backend.services.git_service import GitError, GitService

        if not job.worktree_path or job.worktree_path == job.repo:
            return job

        wt = Path(job.worktree_path)
        if wt.exists():
            return job

        if not job.branch:
            raise StateConflictError(
                f"Job {job.id} cannot be resumed because its worktree is missing "
                "and no branch is available to restore it."
            )

        git = GitService(self._config)
        try:
            new_wt = await git.reattach_worktree(job.repo, job.id, job.branch)
            await job_repo.update_worktree_path(job.id, new_wt)
            job.worktree_path = new_wt
            log.info("worktree_reattached", job_id=job.id, path=new_wt)
            return job
        except GitError as exc:
            raise StateConflictError(
                f"Job {job.id} cannot be resumed because its worktree could not be restored: {exc}"
            ) from exc

    async def _recover_active_job(
        self,
        job_id: str,
        *,
        instruction: str = _SERVER_RESTART_RECOVERY_INSTRUCTION,
    ) -> Job:
        """Restart an active job after backend restart without marking it failed."""

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)
            if job is None:
                raise JobNotFoundError(f"Job {job_id} does not exist.")
            if job.state not in (JobState.running, JobState.waiting_for_approval):
                raise StateConflictError(f"Job {job_id} is not active and cannot be recovered (current: {job.state}).")

            snapshot = _RecoverySnapshot(
                state=job.state,
                session_count=job.session_count,
                completed_at=job.completed_at,
                resolution=job.resolution,
                failure_reason=job.failure_reason,
                archived_at=job.archived_at,
                merge_status=job.merge_status,
                pr_url=job.pr_url,
            )

            job = await self._ensure_resumable_worktree(job_repo, job)

            new_session_count = job.session_count + 1
            if job.sdk_session_id:
                override_prompt = instruction
                resume_sdk_session_id: str | None = job.sdk_session_id
            else:
                override_prompt = await self._build_resume_handoff_prompt_for_job(
                    session,
                    job,
                    instruction,
                    new_session_count,
                )
                resume_sdk_session_id = None

            await job_repo.reset_for_recovery(job_id, new_session_count, new_state=JobState.running)
            await session.commit()

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            reloaded = await job_repo.get(job_id)
        if reloaded is None:
            raise JobNotFoundError(f"Job {job_id} not found after recovery reset")

        try:
            await self.start_or_enqueue(
                reloaded,
                override_prompt=override_prompt,
                resume_sdk_session_id=resume_sdk_session_id,
            )
        except Exception:
            log.error("recovery_start_failed", job_id=job_id, exc_info=True)
            await self._rollback_recovery(job_id, snapshot)
            raise

        if snapshot.state == JobState.waiting_for_approval:
            await self._publish_state_event(job_id, JobState.waiting_for_approval, JobState.running)

        now = datetime.now(UTC)
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.session_resumed,
                payload={
                    "session_number": new_session_count,
                    "instruction": instruction,
                    "timestamp": now.isoformat(),
                    "reason": "process_restarted",
                },
            )
        )

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            final_job = await job_repo.get(job_id)
        if final_job is None:
            raise JobNotFoundError(f"Job {job_id} not found after recovery start")
        return final_job

    async def _rollback_recovery(self, job_id: str, snapshot: _RecoverySnapshot) -> None:
        """Restore job state after a failed recovery attempt."""
        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            await job_repo.restore_after_failed_resume(
                job_id,
                previous_state=snapshot.state,
                previous_session_count=snapshot.session_count,
                completed_at=snapshot.completed_at,
                resolution=snapshot.resolution,
                failure_reason=snapshot.failure_reason,
                archived_at=snapshot.archived_at,
                merge_status=snapshot.merge_status,
                pr_url=snapshot.pr_url,
            )
            await session.commit()

    async def _start_job(
        self, job: Job, override_prompt: str | None = None, resume_sdk_session_id: str | None = None
    ) -> None:
        """Create an asyncio task to execute the job."""
        if job.id in self._tasks:
            return  # Already running (in-memory guard)

        # DB-level compare-and-swap: prevents double-start if recovery and
        # an HTTP request race on the same job.  Only the winner proceeds.
        async with self._session_factory() as session:
            repo = JobRepository(session)
            claimed = await repo.claim_for_start(job.id)
            await session.commit()
        if not claimed:
            log.warning("job_start_claim_lost", job_id=job.id)
            return

        agent_session = _AgentSession()
        self._agent_sessions[job.id] = agent_session

        # The DB CAS already set the state to running; publish the event
        # if the domain object's state hasn't caught up yet.
        if job.state != JobState.running:
            await self._publish_state_event(job.id, job.state, JobState.running)

        try:
            session_config = build_session_config(
                job,
                self._config,
                self._permission_overrides.pop(job.id, None),
            )
            if override_prompt is not None:
                session_config = dataclass_replace(session_config, prompt=override_prompt)
            if resume_sdk_session_id is not None:
                session_config = dataclass_replace(session_config, resume_sdk_session_id=resume_sdk_session_id)

            task = asyncio.create_task(
                self._run_job_guarded(job.id, agent_session, session_config, session_number=job.session_count),
                name=f"job-{job.id}",
            )
        except Exception:
            # Task creation failed after the DB CAS set state to running.
            # Revert to the pre-claim state so the job isn't orphaned.
            self._agent_sessions.pop(job.id, None)
            log.error("job_start_task_creation_failed", job_id=job.id, exc_info=True)
            async with self._session_factory() as session:
                repo = JobRepository(session)
                await repo.update_state(job.id, job.state, datetime.now(UTC))
                await session.commit()
            raise
        self._tasks[job.id] = task
        # Pre-register prompt for echo suppression so the SDK user.message
        # echo of the initial prompt is discarded (shown via the synthetic entry).
        self._echo_suppress.setdefault(job.id, set()).add(session_config.prompt)
        log.info("job_started", job_id=job.id)

    async def _run_job_guarded(
        self,
        job_id: str,
        agent_session: _AgentSession,
        config: SessionConfig,
        session_number: int = 1,
    ) -> None:
        """Wrapper that guarantees ``_cleanup_job_state`` runs even when
        ``CancelledError`` hits before the inner try/except in ``_run_job``."""
        try:
            await self._run_job(job_id, agent_session, config, session_number=session_number)
        except asyncio.CancelledError:
            if self._shutting_down:
                log.info("shutdown_task_cancelled", job_id=job_id)
            else:
                await self._cancel_safety_net(job_id)
        finally:
            log.debug("_run_job_guarded_finally", job_id=job_id, in_tasks=job_id in self._tasks)
            # The inner _run_job finally handles cleanup in the normal case.
            # This catches the case where CancelledError hit during setup,
            # before the inner try was entered.
            if job_id in self._tasks:
                heartbeat = self._heartbeat_tasks.pop(job_id, None)
                if heartbeat:
                    heartbeat.cancel()
                await self._cleanup_job_state(job_id)

    async def _cancel_safety_net(self, job_id: str) -> None:
        """Last-resort cancel handler when CancelledError escapes ``_run_job``.

        Clears task-level cancellation, then attempts to transition the job to
        ``canceled`` in the DB so it doesn't stay stuck in ``running``.
        """
        log.info("job_canceled_safety_net", job_id=job_id)
        _cur = asyncio.current_task()
        if _cur is not None:
            _cur.uncancel()
        try:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                current = await svc.get_job(job_id)
                if current and current.state not in TERMINAL_STATES:
                    await svc.transition_state(job_id, JobState.canceled)
                    await session.commit()
        except (Exception, asyncio.CancelledError):
            log.error("safety_net_cancel_failed", job_id=job_id, exc_info=True)

    async def _run_job(
        self,
        job_id: str,
        agent_session: _AgentSession,
        config: SessionConfig,
        session_number: int = 1,
    ) -> None:
        """Execute the agent session, translate events, and handle completion."""
        import time

        self._last_activity[job_id] = time.monotonic()
        _job_wall_start = time.monotonic()  # captured here so adapter cleanup can't erase it
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(job_id),
            name=f"heartbeat-{job_id}",
        )
        self._heartbeat_tasks[job_id] = heartbeat_task

        # Start plan tracking via trail service
        if self._trail_service is not None:
            await self._trail_service.start_tracking(job_id, prompt=config.prompt or "")

        # Start telemetry tracking — init OTEL spans and SQLite summary row.
        from backend.services import telemetry as tel

        tel.start_job_span(job_id, sdk=config.sdk, model=config.model or "")

        asyncio.create_task(self._telemetry.init_telemetry_row(job_id, config), name=f"telemetry-init-{job_id[:8]}")

        # Create observer terminal for live agent shell output
        if self._terminal_service is not None:
            try:
                observer = self._terminal_service.create_observer_session(job_id=job_id)
                self._observer_terminals[job_id] = observer.id
            except (OSError, RuntimeError):
                log.warning("observer_terminal_create_failed", job_id=job_id, exc_info=True)

        # Emit environment_setup phase
        self._resolve_adapter(config.sdk).set_execution_phase(job_id, ExecutionPhase.environment_setup)
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.execution_phase_changed,
                payload={"phase": ExecutionPhase.environment_setup},
            )
        )

        # Resolve worktree_path and base_ref for diff calculations
        worktree_path: str | None = None
        base_ref: str | None = None
        post_conflict_merge_requested = False
        try:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                job = await svc.get_job(job_id)
            if job is not None:
                worktree_path = job.worktree_path or job.repo
                base_ref = job.base_ref
                post_conflict_merge_requested = job.merge_status == Resolution.conflict
        except DBAPIError:
            log.warning("diff_job_lookup_failed", job_id=job_id, exc_info=True)

        if worktree_path and self._step_tracker is not None:
            self._step_tracker.register_worktree(job_id, worktree_path)

        session_id: str | None = None
        error_reason: str | None = None
        final_state = JobState.review
        try:
            # Emit agent_reasoning phase before main session execution
            self._resolve_adapter(config.sdk).set_execution_phase(job_id, ExecutionPhase.agent_reasoning)
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=datetime.now(UTC),
                    kind=DomainEventKind.execution_phase_changed,
                    payload={"phase": ExecutionPhase.agent_reasoning},
                )
            )

            result = await self._execute_session_attempt(
                job_id,
                agent_session,
                config,
                worktree_path,
                base_ref,
                session_number=session_number,
            )
            session_id = result.session_id
            error_reason = result.error_reason

            # Resume fallback: first attempt errored without progress on a resumed session
            if error_reason and config.resume_sdk_session_id and not result.made_progress:
                result = await self._attempt_resume_fallback(
                    job_id,
                    config,
                    worktree_path,
                    base_ref,
                    session_number=session_number,
                )
                session_id = result.session_id
                error_reason = result.error_reason

            # Model downgrade (from either attempt): finish diff, move to review with note, skip verify
            if result.downgrade is not None:
                await self._handle_model_downgrade(job_id, result.downgrade, worktree_path, base_ref)
                return

            if error_reason:
                # An error event was received during execution — finalize diff before failing
                log.warning("job_error_reason_detected", job_id=job_id, error_reason=error_reason)
                await self._finalize_diff_safe(job_id, worktree_path, base_ref)
                await self._fail_job(job_id, error_reason)
                return

            final_state = await self._handle_successful_completion(
                job_id, config, session_id, worktree_path, base_ref,
                post_conflict_merge_requested, session_number,
            )
        except asyncio.CancelledError:
            if self._shutting_down:
                # Server is shutting down — leave job state as-is so
                # recover_on_startup picks it back up on next launch.
                log.info("job_interrupted_by_shutdown", job_id=job_id)
                await self._finalize_diff_safe(job_id, worktree_path, base_ref)
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await agent_session.abort()
            else:
                log.info("job_canceled_by_operator", job_id=job_id)
                await self._handle_job_canceled(job_id, agent_session, worktree_path, base_ref)
        except Exception as exc:
            log.error("job_execution_failed", job_id=job_id, exc_info=True)
            # Finalize diff so changes are preserved even for crashed jobs
            await self._finalize_diff_safe(job_id, worktree_path, base_ref)
            await self._fail_job(job_id, f"Execution error: {exc}")
        finally:
            await self._telemetry.finalize_job_telemetry(job_id, _job_wall_start, config)
            heartbeat_task.cancel()
            self._heartbeat_tasks.pop(job_id, None)
            if self._trail_service is not None:
                self._trail_service.stop_tracking(job_id)
                succeeded = final_state == JobState.completed
                await self._trail_service.finalize(job_id, succeeded=succeeded)
            await self._cleanup_job_state(job_id)

    async def _init_telemetry_row(self, job_id: str, config: SessionConfig) -> None:
        await self._telemetry.init_telemetry_row(job_id, config)

    async def _handle_model_downgrade(
        self,
        job_id: str,
        downgrade: tuple[str, str],
        worktree_path: str | None,
        base_ref: str | None,
    ) -> None:
        requested, actual = downgrade
        await self._finalize_diff_safe(job_id, worktree_path, base_ref)
        reason = f"Model downgraded: requested {requested} but received {actual}"
        async with self._session_factory() as session:
            svc = self._make_job_service(session)
            await svc.transition_state(job_id, JobState.review, failure_reason=reason)
            job_repo = JobRepository(session)
            await job_repo.update_resolution(job_id, Resolution.unresolved)
            await session.commit()

        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.job_review,
                payload={
                    "resolution": Resolution.unresolved,
                    "model_downgraded": True,
                    "requested_model": requested,
                    "actual_model": actual,
                },
            )
        )
        log.info("job_moved_to_review_model_downgrade", job_id=job_id)

    async def _handle_successful_completion(
        self,
        job_id: str,
        config: SessionConfig,
        session_id: str | None,
        worktree_path: str | None,
        base_ref: str | None,
        post_conflict_merge_requested: bool,
        session_number: int,
    ) -> JobState:
        # Final diff snapshot before resolution
        await self._finalize_diff_safe(job_id, worktree_path, base_ref)

        # Run optional verify / self-review follow-up turns
        await self._run_verify_review(
            job_id, config, session_id, worktree_path, base_ref, session_number=session_number
        )

        final_resolution = Resolution.unresolved
        final_pr_url: str | None = None
        final_merge_status: str | None = None
        resolution_event = None

        # Strategy completed normally → review
        #
        # Commit the state transition BEFORE running merge resolution.
        # Merge operations open their own sessions to persist merge_status
        # and publish events — if the outer session is still uncommitted
        # SQLite will deadlock on the jobs table write lock.
        async with self._session_factory() as session:
            svc = self._make_job_service(session)
            await svc.transition_state(job_id, JobState.review)
            if not post_conflict_merge_requested or self._merge_service is None:
                job_repo = JobRepository(session)
                await job_repo.update_resolution(job_id, final_resolution, pr_url=None)
                if post_conflict_merge_requested and self._merge_service is None:
                    log.warning("post_conflict_merge_unavailable", job_id=job_id)
            await session.commit()

        # Merge resolution runs in its own session(s) — no lock contention.
        if post_conflict_merge_requested and self._merge_service is not None:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                current_job = await svc.get_job(job_id)
                if current_job is None:
                    raise JobNotFoundError(f"Job {job_id} not found before post-conflict merge")

                log.info("job_attempting_post_conflict_merge", job_id=job_id)
                resolved, final_pr_url, _, _ = await svc.execute_resolve(
                    job=current_job,
                    action="merge",
                    merge_service=self._merge_service,
                )
                final_resolution = cast("Resolution", resolved)
                resolution_event = svc.build_job_resolved_event(
                    job_id,
                    resolved,
                    pr_url=final_pr_url,
                )
                await session.commit()

        if resolution_event is not None:
            await self._event_bus.publish(resolution_event)

        async with self._session_factory() as session:
            svc = self._make_job_service(session)
            updated_job = await svc.get_job(job_id)
        if updated_job is not None:
            final_merge_status = updated_job.merge_status
            final_pr_url = updated_job.pr_url

        if final_resolution == Resolution.unresolved:
            log.info("job_awaiting_review", job_id=job_id)
        else:
            log.info(
                "job_completed_with_resolution",
                job_id=job_id,
                resolution=final_resolution,
                merge_status=final_merge_status,
            )

        # Determine final state — execute_resolve may have already
        # transitioned review → completed for successful merges.
        final_state = JobState.review
        if final_resolution in (Resolution.merged, Resolution.pr_created, Resolution.discarded):
            final_state = JobState.completed
        final_event_kind = (
            DomainEventKind.job_completed if final_state == JobState.completed else DomainEventKind.job_review
        )

        await self._set_step_terminal_state(job_id, final_state)
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=final_event_kind,
                payload={
                    "resolution": final_resolution,
                    "merge_status": final_merge_status,
                    "pr_url": final_pr_url,
                },
            )
        )
        log.info(
            final_event_kind.value,
            job_id=job_id,
            resolution=final_resolution,
            merge_status=final_merge_status,
        )
        return final_state

    async def _finalize_job_telemetry(self, job_id: str, wall_start: float, config: SessionConfig) -> None:
        await self._telemetry.finalize_job_telemetry(job_id, wall_start, config)

    async def _store_post_completion_artifacts(
        self,
        job_id: str,
    ) -> None:
        """Persist internal state (telemetry, plan, approvals) as downloadable artifacts."""
        await self._telemetry.store_post_completion_artifacts(job_id)

    def _start_snapshot_task(self, job_id: str) -> None:
        if self._shutting_down:
            return
        if self._summarization_service is None:
            return
        existing = self._snapshot_tasks.get(job_id)
        if existing is not None and not existing.done():
            return

        task = asyncio.create_task(
            self._summarization_service.save_snapshot_to_disk(job_id),
            name=f"snapshot-{job_id}",
        )
        self._snapshot_tasks[job_id] = task

        def _cleanup_snapshot_task(completed: asyncio.Task[None]) -> None:
            current = self._snapshot_tasks.get(job_id)
            if current is completed:
                self._snapshot_tasks.pop(job_id, None)

        task.add_done_callback(_cleanup_snapshot_task)

    async def _set_step_terminal_state(self, job_id: str, outcome: str) -> None:
        """Forward terminal outcome to the step tracker."""
        if self._step_tracker is not None:
            await self._step_tracker.on_job_terminal(job_id, outcome)

    async def _cleanup_job_state(self, job_id: str) -> None:
        """Remove all per-job in-memory state and trigger post-job hooks."""
        # Last-resort guard: if the job is still non-terminal after all error
        # handlers have run, force it to failed so it doesn't stay stuck.
        await self._ensure_terminal_state(job_id)

        if self._trail_service is not None:
            self._trail_service.cleanup(job_id)
        if self._step_tracker is not None:
            self._step_tracker.cleanup(job_id)
        self._tasks.pop(job_id, None)
        self._agent_sessions.pop(job_id, None)
        self._last_activity.pop(job_id, None)
        self._waiting_for_approval.discard(job_id)
        self._session_ids.pop(job_id, None)
        self._echo_suppress.pop(job_id, None)
        self._pending_starts.pop(job_id, None)
        self._queued_override_prompts.pop(job_id, None)
        self._queued_resume_session_ids.pop(job_id, None)
        self._observer_terminals.pop(job_id, None)
        if self._sister_sessions is not None:
            try:
                self._sister_sessions.close_job(job_id)
            except (OSError, RuntimeError):
                log.warning("sister_session_close_failed", job_id=job_id, exc_info=True)
        if self._approval_service is not None:
            await self._approval_service.cleanup_job(job_id)
        if self._diff_service is not None:
            self._diff_service.cleanup(job_id)
        self._start_snapshot_task(job_id)
        await self._dequeue_next()

    async def _ensure_terminal_state(self, job_id: str) -> None:
        """Ensure the job is not stuck in an in-flight state.  Called as a
        last-resort safety net during cleanup so that no job is ever
        permanently stuck in 'running' or 'waiting_for_approval'.

        'review' is intentionally excluded — it is a valid resting state
        where the agent has finished and the job awaits operator action.

        During server shutdown, jobs are intentionally left as-is so that
        ``recover_on_startup`` can resume them on the next launch.
        """
        if self._shutting_down:
            return
        # Only force-fail jobs that are truly in-flight.  'review' and
        # terminal states are fine.
        stuck_states = frozenset({JobState.running, JobState.waiting_for_approval})
        # Clear any pending task-level cancellation so the DB transition
        # below is not immediately interrupted.
        _cur = asyncio.current_task()
        if _cur is not None:
            _cur.uncancel()
        try:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                job = await svc.get_job(job_id)
                if job is not None and job.state in stuck_states:
                    log.error(
                        "ensure_terminal_state_forcing_failure",
                        job_id=job_id,
                        current_state=str(job.state),
                    )
                    await svc.transition_state(
                        job_id,
                        JobState.failed,
                        failure_reason="Job cleanup: forced to failed (previous state transitions failed)",
                    )
                    await session.commit()
                    await self._set_step_terminal_state(job_id, JobState.failed)
                    await self._event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=job_id,
                            timestamp=datetime.now(UTC),
                            kind=DomainEventKind.job_failed,
                            payload={"reason": "Job cleanup: previous error handlers failed to transition state"},
                        )
                    )
        except (Exception, asyncio.CancelledError):
            log.error("ensure_terminal_state_failed", job_id=job_id, exc_info=True)

    async def _handle_approval_request(
        self,
        job_id: str,
        domain_event: DomainEvent,
        rejection_message: str,
    ) -> ApprovalResolution:
        """Handle an approval_requested event: transition state, wait for operator, return resolution."""
        import time

        if self._approval_service is None:
            raise ServiceInitError("approval_service must be set before handling approvals")

        async with self._session_factory() as sess:
            svc = self._make_job_service(sess)
            await svc.transition_state(job_id, JobState.waiting_for_approval)
            await sess.commit()

        self._waiting_for_approval.add(job_id)

        await self._event_bus.publish(domain_event)

        approval_id = domain_event.payload.get("approval_id", "")
        resolution = await self._approval_service.wait_for_resolution(approval_id)

        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.approval_resolved,
                payload={
                    "approval_id": approval_id,
                    "resolution": resolution,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

        self._waiting_for_approval.discard(job_id)

        if resolution == ApprovalResolution.rejected:
            # Leave job in waiting_for_approval — the caller will fail it
            # via _fail_job which handles the waiting_for_approval → failed
            # transition.  Do NOT transition to running first.
            return resolution

        async with self._session_factory() as sess:
            svc = self._make_job_service(sess)
            await svc.transition_state(job_id, JobState.running)
            await sess.commit()
        await self._publish_state_event(job_id, JobState.waiting_for_approval, JobState.running)
        self._last_activity[job_id] = time.monotonic()

        return resolution

    async def _attempt_resume_fallback(
        self,
        job_id: str,
        config: SessionConfig,
        worktree_path: str | None,
        base_ref: str | None,
        session_number: int = 1,
    ) -> _SessionAttemptResult:
        """Try a fresh session after a failed resume."""
        await self._clear_sdk_session_id(job_id)
        try:
            fallback_prompt = await self._build_resume_handoff_prompt(job_id, config.prompt)
        except (OSError, KeyError, ValueError, LookupError):
            log.warning("resume_handoff_prompt_build_failed", job_id=job_id, exc_info=True)
            return _SessionAttemptResult(error_reason="Resume handoff prompt build failed")

        log.warning(
            "resume_sdk_session_unusable_falling_back",
            job_id=job_id,
            sdk_session_id=config.resume_sdk_session_id,
        )
        fallback_session = _AgentSession()
        self._agent_sessions[job_id] = fallback_session
        fallback_config = dataclass_replace(
            config,
            prompt=fallback_prompt,
            resume_sdk_session_id=None,
        )
        fallback_result = await self._execute_session_attempt(
            job_id,
            fallback_session,
            fallback_config,
            worktree_path,
            base_ref,
            session_number=session_number,
        )
        return fallback_result

    async def _handle_job_canceled(
        self,
        job_id: str,
        agent_session: _AgentSession,
        worktree_path: str | None,
        base_ref: str | None,
    ) -> None:
        """Process cancellation: finalize diff, abort agent, transition state."""
        try:
            await self._finalize_diff_safe(job_id, worktree_path, base_ref)
        except (Exception, asyncio.CancelledError):
            log.warning("cancel_diff_finalize_failed", job_id=job_id, exc_info=True)
        try:
            await agent_session.abort()
        except (Exception, asyncio.CancelledError):
            log.warning("agent_abort_failed", job_id=job_id, exc_info=True)
        try:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                current = await svc.get_job(job_id)
                if current and current.state not in TERMINAL_STATES:
                    await svc.transition_state(job_id, JobState.canceled)
                    await session.commit()
                    await self._set_step_terminal_state(job_id, JobState.canceled)
                    await self._event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=job_id,
                            timestamp=datetime.now(UTC),
                            kind=DomainEventKind.job_canceled,
                            payload={"reason": "operator_cancel"},
                        )
                    )
                else:
                    await session.commit()
        except (Exception, asyncio.CancelledError):
            log.warning("job_cancel_transition_failed", job_id=job_id, exc_info=True)

    # ------------------------------------------------------------------
    # Shared event processing
    # ------------------------------------------------------------------

    async def _process_agent_event(
        self,
        job_id: str,
        session_event: SessionEvent,
        agent_session: _AgentSession,
        worktree_path: str | None,
        base_ref: str | None,
        rejection_message: str,
    ) -> tuple[_EventAction, DomainEvent | None, str | None]:
        """Process a single agent session event (shared by main + follow-up loops).

        Returns ``(action, domain_event, error_reason)``:

        * **skip** – event consumed internally, caller should ``continue``.
        * **publish** – caller should emit *domain_event* via the event bus.
          *error_reason* is set when the event signals a failure but the loop
          should keep draining.
        * **abort** – caller should ``break``; *error_reason* explains why.
        """
        import time

        self._last_activity[job_id] = time.monotonic()

        _diff_eligible = self._diff_service is not None and worktree_path and base_ref

        # Diff recalculation on file changes
        if _diff_eligible and session_event.kind == SessionEventKind.file_changed:
            await self._diff_service.on_worktree_file_modified(job_id, worktree_path, base_ref)
            return _EventAction.skip, None, None

        # Diff recalculation on tool completions (skip internal markers like report_intent)
        if (
            _diff_eligible
            and session_event.kind == SessionEventKind.transcript
            and session_event.payload.get("role") == "tool_call"
            and session_event.payload.get("tool_name") != "report_intent"
        ):
            await self._diff_service.on_worktree_file_modified(job_id, worktree_path, base_ref)

        domain_event = self._translate_event(job_id, session_event)
        if domain_event is None:
            return _EventAction.skip, None, None

        error_reason: str | None = None
        if domain_event.kind == DomainEventKind.job_failed:
            error_reason = domain_event.payload.get("message", "Agent error")

        # Suppress SDK echoes
        if domain_event.kind == DomainEventKind.transcript_updated and job_id in self._echo_suppress:
            content = domain_event.payload.get("content", "")
            if content in self._echo_suppress[job_id]:
                self._echo_suppress[job_id].discard(content)
                return _EventAction.skip, None, None

        # Handle approval requests
        if domain_event.kind == DomainEventKind.approval_requested and self._approval_service is not None:
            resolution = await self._handle_approval_request(
                job_id,
                domain_event,
                rejection_message,
            )
            if resolution == ApprovalResolution.rejected:
                return _EventAction.abort, None, rejection_message
            return _EventAction.skip, None, None

        return _EventAction.publish, domain_event, error_reason

    async def _execute_session_attempt(
        self,
        job_id: str,
        agent_session: _AgentSession,
        config: SessionConfig,
        worktree_path: str | None,
        base_ref: str | None,
        session_number: int = 1,
    ) -> _SessionAttemptResult:
        session_id: str | None = None
        error_reason: str | None = None
        made_progress = False
        downgrade: tuple[str, str] | None = None

        async for session_event in agent_session.execute(config, self._resolve_adapter(config.sdk)):
            made_progress = made_progress or _session_event_counts_as_resume_progress(session_event)

            # Forward shell events to observer terminal (before action filtering).
            self._forward_to_observer(job_id, session_event)

            action, domain_event, evt_error = await self._process_agent_event(
                job_id,
                session_event,
                agent_session,
                worktree_path,
                base_ref,
                "Approval rejected by operator",
            )

            if action == _EventAction.skip:
                continue
            if action == _EventAction.abort:
                error_reason = evt_error
                break

            if domain_event is None:
                raise CodePlaneError("Event publish must always provide a domain event")

            if evt_error:
                error_reason = evt_error
                log.warning("agent_error_event", job_id=job_id, error_reason=error_reason)

            # Session ID for return value + persistence
            if session_id is None and agent_session.session_id:
                session_id = agent_session.session_id
                self._session_ids[job_id] = session_id
                await self._persist_sdk_session_id(job_id, session_id)

            # Model downgrade: publish event, abort session, signal caller
            if domain_event.kind == DomainEventKind.model_downgraded:
                requested = domain_event.payload.get("requested_model", "")
                actual = domain_event.payload.get("actual_model", "")
                log.warning(
                    "model_downgrade_detected",
                    job_id=job_id,
                    requested=requested,
                    actual=actual,
                )
                await self._event_bus.publish(domain_event)
                try:
                    await agent_session.abort()
                except Exception:
                    log.warning("agent_abort_on_downgrade_failed", job_id=job_id, exc_info=True)
                downgrade = (requested, actual)
                break

            # Trail service feed (main loop only) — skip ephemeral delta chunks
            if domain_event.kind == DomainEventKind.transcript_updated and self._trail_service is not None:
                role = domain_event.payload.get("role", "")
                if role != "agent_delta":
                    content = domain_event.payload.get("content", "")
                    tool_intent = str(domain_event.payload.get("tool_intent") or "")
                    await self._trail_service.feed_transcript(job_id, role, content, tool_intent)

                # Feed tool names to trail service for summary context
                if role == "tool_call":
                    tool_name = domain_event.payload.get("tool_name", "")
                    if tool_name:
                        await self._trail_service.feed_tool_name(job_id, tool_name)
                    # Native plan capture: extract structured plan data from the
                    # agent's own todo/plan tool.
                    if tool_name in ("manage_todo_list", "TodoWrite"):
                        await self._ingest_native_plan(job_id, domain_event.payload)

            # Step tracking — annotate transcript events with step_id
            if domain_event.kind == DomainEventKind.transcript_updated and self._step_tracker is not None:
                role = domain_event.payload.get("role", "")
                if role != "agent_delta":
                    await self._step_tracker.on_transcript_event(job_id, domain_event)
                    current = self._step_tracker.current_step(job_id)
                    if current:
                        domain_event.payload["step_number"] = current.step_number
                    # TrailService is the sole step_id authority (ps-* IDs)
                    if self._trail_service is not None:
                        plan_step_id = self._trail_service.get_active_plan_step_id(job_id)
                        if plan_step_id:
                            domain_event.payload["step_id"] = plan_step_id

            # Tag log lines with the current session number so callers can filter
            # by session when a job has been resumed one or more times.
            if domain_event.kind == DomainEventKind.log_line_emitted:
                domain_event.payload.setdefault("session_number", session_number)

            await self._event_bus.publish(domain_event)

        return _SessionAttemptResult(
            session_id=session_id,
            error_reason=error_reason,
            made_progress=made_progress,
            downgrade=downgrade,
        )

    async def _ingest_native_plan(self, job_id: str, payload: dict[str, object]) -> None:
        """Extract plan steps from a manage_todo_list / TodoWrite tool call."""
        from backend.services.parsing_utils import ensure_dict

        if self._trail_service is None:
            return
        raw_args = payload.get("tool_args")
        if not raw_args:
            return

        args = ensure_dict(raw_args)
        if args is None:
            return

        # Copilot: {"todoList": [...]}   Claude: {"todos": [...]}
        items = args.get("todoList") or args.get("todos") or []
        if not isinstance(items, list):
            return

        try:
            await self._trail_service.feed_native_plan(job_id, items)
        except (ValueError, TypeError, KeyError):
            log.warning("native_plan_ingest_failed", job_id=job_id, exc_info=True)

    async def _run_followup_turn(
        self,
        job_id: str,
        prompt: str,
        base_config: SessionConfig,
        resume_session_id: str | None,
        worktree_path: str | None,
        base_ref: str | None,
        session_number: int = 1,
    ) -> tuple[str | None, str | None]:
        """Run a single follow-up agent turn (verify or self-review).

        Returns ``(new_session_id, error_reason)``.  *error_reason* is set if
        the turn encountered an error; callers decide whether to abort.
        """
        followup_session = _AgentSession()
        followup_config = dataclass_replace(
            base_config,
            prompt=prompt,
            resume_sdk_session_id=resume_session_id,
        )

        # Suppress echo of the follow-up prompt
        self._echo_suppress.setdefault(job_id, set()).add(prompt)

        error_reason: str | None = None
        new_session_id: str | None = None

        try:
            async for event in followup_session.execute(followup_config, self._resolve_adapter(base_config.sdk)):
                # Forward shell events to observer terminal.
                self._forward_to_observer(job_id, event)

                action, domain_event, evt_error = await self._process_agent_event(
                    job_id,
                    event,
                    followup_session,
                    worktree_path,
                    base_ref,
                    "Approval rejected during verification",
                )

                if action == _EventAction.skip:
                    continue
                if action == _EventAction.abort:
                    error_reason = evt_error
                    break

                if domain_event is None:
                    raise CodePlaneError("Event publish must always provide a domain event")

                if evt_error:
                    error_reason = evt_error

                # Capture follow-up session ID
                if new_session_id is None and followup_session.session_id:
                    new_session_id = followup_session.session_id
                    self._session_ids[job_id] = new_session_id
                    await self._persist_sdk_session_id(job_id, new_session_id)

                if domain_event.kind == DomainEventKind.log_line_emitted:
                    domain_event.payload.setdefault("session_number", session_number)

                # Step tracking for follow-up turns
                if domain_event.kind == DomainEventKind.transcript_updated and self._step_tracker is not None:
                    role = domain_event.payload.get("role", "")
                    if role != "agent_delta":
                        await self._step_tracker.on_transcript_event(job_id, domain_event)
                        current = self._step_tracker.current_step(job_id)
                        if current:
                            domain_event.payload["step_id"] = current.step_id
                            domain_event.payload["step_number"] = current.step_number

                await self._event_bus.publish(domain_event)
        except Exception:
            log.warning("followup_turn_failed", job_id=job_id, exc_info=True)
            error_reason = "Follow-up turn execution error"

        return new_session_id, error_reason

    async def _run_verify_review(
        self,
        job_id: str,
        base_config: SessionConfig,
        session_id: str | None,
        worktree_path: str | None,
        base_ref: str | None,
        session_number: int = 1,
    ) -> None:
        """Run optional verify and self-review turns after the main agent session."""
        job: Job | None = None
        try:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                job = await svc.get_job(job_id)
        except DBAPIError:
            log.warning("verify_job_lookup_failed", job_id=job_id, exc_info=True)
            return

        if job is None:
            return

        do_verify = job.verify if job.verify is not None else self._config.verification.verify
        do_self_review = job.self_review if job.self_review is not None else self._config.verification.self_review

        if not do_verify and not do_self_review:
            return

        max_turns = job.max_turns if job.max_turns is not None else self._config.verification.max_turns
        verify_prompt = job.verify_prompt or self._config.verification.verify_prompt or DEFAULT_VERIFY_PROMPT
        self_review_prompt = (
            job.self_review_prompt or self._config.verification.self_review_prompt or DEFAULT_SELF_REVIEW_PROMPT
        )

        # Emit verification phase change
        self._resolve_adapter(base_config.sdk).set_execution_phase(job_id, ExecutionPhase.verification)
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.execution_phase_changed,
                payload={"phase": ExecutionPhase.verification},
            )
        )

        current_session_id = session_id

        if do_verify:
            for turn in range(1, max_turns + 1):
                log.info("verify_turn_start", job_id=job_id, turn=turn, max_turns=max_turns)
                new_sid, error = await self._run_followup_turn(
                    job_id,
                    verify_prompt,
                    base_config,
                    current_session_id,
                    worktree_path,
                    base_ref,
                    session_number=session_number,
                )
                if new_sid:
                    current_session_id = new_sid
                if error:
                    log.warning("verify_turn_error", job_id=job_id, turn=turn, error=error)
                    break
                log.info("verify_turn_complete", job_id=job_id, turn=turn)

        if do_self_review:
            log.info("self_review_start", job_id=job_id)
            new_sid, error = await self._run_followup_turn(
                job_id,
                self_review_prompt,
                base_config,
                current_session_id,
                worktree_path,
                base_ref,
                session_number=session_number,
            )
            if new_sid:
                current_session_id = new_sid
            if error:
                log.warning("self_review_error", job_id=job_id, error=error)
            else:
                log.info("self_review_complete", job_id=job_id)

        # Final diff snapshot after verify/review turns
        await self._finalize_diff_safe(job_id, worktree_path, base_ref)

    async def _heartbeat_loop(self, job_id: str) -> None:
        """Emit periodic heartbeats for session health display."""
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)

                last = self._last_activity.get(job_id)
                if last is None:
                    return

                session_id = self._session_ids.get(job_id, "")
                await self._event_bus.publish(
                    DomainEvent(
                        event_id=DomainEvent.make_event_id(),
                        job_id=job_id,
                        timestamp=datetime.now(UTC),
                        kind=DomainEventKind.session_heartbeat,
                        payload={
                            "job_id": job_id,
                            "session_id": session_id,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )
                )
        except asyncio.CancelledError:
            log.debug("heartbeat_loop_cancelled", job_id=job_id)

    async def cancel(self, job_id: str) -> None:
        """Cancel a running job by cancelling its asyncio task.

        State transitions for non-running jobs (e.g. queued) are handled
        by the service layer (JobService.cancel_job). This method only
        interacts with in-memory runtime tasks.
        """
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()
            log.info("job_cancel_requested", job_id=job_id)
        else:
            log.info("job_cancel_no_running_task", job_id=job_id)

    async def interrupt(self, job_id: str) -> bool:
        """Interrupt the agent's current turn without destroying the session.

        Sends SIGINT-equivalent to the SDK subprocess: the currently running
        shell command is killed, but the session stays alive and the agent can
        recover or be given a new instruction.

        Returns True if an active session was found and interrupted.
        """
        agent_session = self._agent_sessions.get(job_id)
        if agent_session is None:
            log.info("job_interrupt_no_session", job_id=job_id)
            return False
        await agent_session.interrupt()
        log.info("job_interrupted", job_id=job_id)
        return True

    # ------------------------------------------------------------------
    # Observer terminal bridge
    # ------------------------------------------------------------------

    # Tool names that represent shell execution across SDKs.
    _SHELL_TOOL_NAMES: frozenset[str] = frozenset({
        "bash", "Bash", "run_in_terminal", "execute_command",
        "run_terminal_command", "shell",
    })

    def _forward_to_observer(self, job_id: str, event: SessionEvent) -> None:
        """Forward shell-tool transcript events to the observer terminal."""
        if self._terminal_service is None:
            return
        terminal_id = self._observer_terminals.get(job_id)
        if not terminal_id:
            return
        if event.kind != SessionEventKind.transcript:
            return

        payload = event.payload
        role = payload.get("role", "")
        tool_name = payload.get("tool_name", "")
        is_shell = tool_name in self._SHELL_TOOL_NAMES

        if role == "tool_running" and is_shell:
            # Show the command the agent is about to run.
            cmd = ""
            raw_args = payload.get("tool_args")
            if raw_args:
                from backend.services.parsing_utils import ensure_dict

                args = ensure_dict(raw_args)
                if args is not None:
                    cmd = args.get("command", "") or args.get("input", "")
                else:
                    cmd = str(raw_args)
            if cmd:
                self._terminal_service.write_observer_output(
                    terminal_id,
                    f"\x1b[1;34m$ \x1b[0m{cmd}\n",
                )

        elif role == "tool_output_delta" and is_shell:
            # Streaming stdout/stderr — write chunks as they arrive.
            chunk = payload.get("content", "")
            if chunk:
                self._terminal_service.write_observer_output(terminal_id, chunk)

        elif role == "tool_call" and is_shell:
            # Tool completed — write a separator line.
            success = payload.get("tool_success", True)
            if not success:
                issue = payload.get("tool_issue") or "command failed"
                self._terminal_service.write_observer_output(
                    terminal_id,
                    f"\x1b[1;31m✗ {issue}\x1b[0m\n",
                )

    async def send_message(self, job_id: str, message: str) -> bool:
        """Send an operator message to a running job.

        Publishes the transcript event locally for immediate UI feedback and
        suppresses the SDK echo to avoid showing the message twice.

        If no live agent session exists (e.g. after a server restart or when the
        UI has a stale job state), the job is automatically resumed with the
        message as the instruction so the operator message is never silently lost.
        """
        agent_session = self._agent_sessions.get(job_id)
        if agent_session is None:
            return await self._resume_orphaned(job_id, message)
        # Lift any tool block from a previous pause before sending.
        agent_session.resume_tools()
        now = datetime.now(UTC)
        await agent_session.send_message(message)
        # Publish immediately so the operator message appears in the transcript
        # without waiting for the SDK to echo it back.
        operator_event = DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.transcript_updated,
            payload={
                "job_id": job_id,
                "seq": 0,
                "timestamp": now.isoformat(),
                "role": TranscriptRole.operator,
                "content": message,
            },
        )
        if self._step_tracker is not None:
            await self._step_tracker.on_transcript_event(job_id, operator_event)
            current = self._step_tracker.current_step(job_id)
            if current:
                operator_event.payload["step_id"] = current.step_id
                operator_event.payload["step_number"] = current.step_number
        await self._event_bus.publish(operator_event)
        # Suppress the SDK echo so the same content is not published twice.
        self._echo_suppress.setdefault(job_id, set()).add(message)
        return True

    async def _resume_orphaned(self, job_id: str, message: str) -> bool:
        """Auto-resume a job that has no live agent session.

        Called by ``send_message`` when the in-memory session map has no entry
        for the job.  This covers two cases:

        * **Stale UI state** — the frontend still shows ``running`` or
          ``waiting_for_approval`` but the agent already finished and the SSE
          update hasn't reached the client yet.  The DB state will already be
          terminal, so we can resume directly.

                * **Orphaned non-terminal job** — the server restarted (or crashed)
                    before ``recover_on_startup`` ran, leaving the DB in ``running`` or
                    ``waiting_for_approval`` with no live task.  We recover it in place
                    instead of creating a synthetic failure transition.

        Returns ``True`` if the resume was successfully initiated, ``False`` if
        the job does not exist.

        Raises domain exceptions (``StateConflictError``, ``JobNotFoundError``)
        so that callers can surface the real error instead of a generic failure.
        """

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)

        if job is None:
            log.warning("send_message_job_not_found", job_id=job_id)
            return False

        if job.state not in TERMINAL_STATES and job.state != JobState.review:
            # Orphaned non-terminal job — recover it in place.
            log.warning(
                "send_message_orphaned_non_terminal",
                job_id=job_id,
                state=job.state,
            )
            try:
                await self._recover_active_job(job_id, instruction=message)
            except (StateConflictError, JobNotFoundError):
                raise
            except Exception:
                log.warning("send_message_auto_resume_failed", job_id=job_id, exc_info=True)
                return False
            return True

        log.info("send_message_auto_resume", job_id=job_id)
        try:
            await self.resume_job(job_id, message)
        except (StateConflictError, JobNotFoundError):
            raise
        except Exception:
            log.warning("send_message_auto_resume_failed", job_id=job_id, exc_info=True)
            return False
        return True

    async def pause_job(self, job_id: str) -> bool:
        """Forcefully pause a running agent. Returns True if sent.

        Immediately blocks all tool execution for the session so the agent
        cannot take further actions, interrupts the current turn (on SDKs
        that support it), and sends a follow-up message instructing the
        agent to wait.  The pause message is never shown in the transcript.
        """
        _pause_msg = (
            "Please stop what you are doing right now and wait. "
            "Do not take any further actions until the operator sends a follow-up message."
        )
        agent_session = self._agent_sessions.get(job_id)
        if agent_session is None:
            log.warning("pause_job_no_session", job_id=job_id)
            return False
        # Block all tool calls immediately so the agent cannot act.
        agent_session.pause_tools()
        # Interrupt the current turn so the agent stops immediately.
        try:
            await agent_session.interrupt()
        except Exception:
            log.warning("pause_interrupt_failed", job_id=job_id, exc_info=True)
        # Pre-register the echo suppression before sending so the SDK echo
        # (if any) is discarded and never appears in the transcript.
        self._echo_suppress.setdefault(job_id, set()).add(_pause_msg)
        await agent_session.send_message(_pause_msg)
        log.info("job_pause_requested", job_id=job_id)
        return True

    async def _dequeue_next(self) -> None:
        """Start the next queued job if capacity allows."""
        if self._shutting_down:
            return
        async with self._dequeue_lock:
            if self.running_count >= self.max_concurrent:
                return
            try:
                if self._pending_starts:
                    job_id, (override_prompt, resume_sdk_session_id) = next(iter(self._pending_starts.items()))
                    self._pending_starts.pop(job_id, None)
                    async with self._session_factory() as session:
                        job = await JobRepository(session).get(job_id)
                    if job is not None:
                        await self._start_job(
                            job,
                            override_prompt=override_prompt,
                            resume_sdk_session_id=resume_sdk_session_id,
                        )
                    return

                async with self._session_factory() as session:
                    svc = self._make_job_service(session)
                    queued_jobs = await svc.list_jobs(state=JobState.queued, limit=1)
                    jobs, _, _ = queued_jobs
                if jobs:
                    job = jobs[0]
                    override_prompt = self._queued_override_prompts.pop(job.id, None)
                    resume_sdk_session_id = self._queued_resume_session_ids.pop(job.id, None)
                    await self._start_job(
                        job,
                        override_prompt=override_prompt,
                        resume_sdk_session_id=resume_sdk_session_id,
                    )
            except Exception:
                log.error("dequeue_failed", exc_info=True)

    async def _fail_job(self, job_id: str, reason: str) -> None:
        """Transition a job to failed state and publish the event.

        The DB transition is run inside ``asyncio.shield`` so that a
        pending task-level cancellation (e.g. from anyio cancel-scope
        teardown) cannot interrupt the write.
        """

        async def _do_fail() -> None:
            async with self._session_factory() as session:
                svc = self._make_job_service(session)
                await svc.get_job(job_id)
                await svc.transition_state(job_id, JobState.failed, failure_reason=reason)
                await session.commit()

        try:
            await asyncio.shield(_do_fail())
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=datetime.now(UTC),
                    kind=DomainEventKind.job_failed,
                    payload={"reason": reason},
                )
            )
        except (Exception, asyncio.CancelledError):
            log.error("fail_job_transition_failed", job_id=job_id, exc_info=True)

    async def _persist_sdk_session_id(self, job_id: str, sdk_session_id: str) -> None:
        """Persist the Copilot SDK session ID so resume_job() can reconnect to it later."""
        try:
            async with self._session_factory() as session:
                job_repo = JobRepository(session)
                await job_repo.update_sdk_session_id(job_id, sdk_session_id)
                await session.commit()
        except DBAPIError:
            log.warning("persist_sdk_session_id_failed", job_id=job_id, exc_info=True)

    async def _clear_sdk_session_id(self, job_id: str) -> None:
        """Clear a stale Copilot SDK session ID so resume falls back cleanly."""
        try:
            async with self._session_factory() as session:
                job_repo = JobRepository(session)
                await job_repo.update_sdk_session_id(job_id, None)
                await session.commit()
        except DBAPIError:
            log.warning("clear_sdk_session_id_failed", job_id=job_id, exc_info=True)

    async def _load_handoff_context_for_job(
        self,
        session: AsyncSession,
        job: Job,
    ) -> tuple[str | None, list[str]]:
        return await load_handoff_context_for_job(
            session, self._session_factory, job, self._summarization_service
        )

    async def _build_resume_handoff_prompt_for_job(
        self,
        session: AsyncSession,
        job: Job,
        instruction: str,
        session_number: int,
    ) -> str:
        return await build_resume_handoff_prompt_for_job(
            session, self._session_factory, job, instruction, session_number, self._summarization_service
        )

    async def _build_followup_handoff_prompt_for_job(
        self,
        session: AsyncSession,
        job: Job,
        instruction: str,
    ) -> str:
        return await build_followup_handoff_prompt_for_job(
            session, self._session_factory, job, instruction, self._summarization_service
        )

    async def _build_resume_handoff_prompt(self, job_id: str, instruction: str) -> str:
        """Build the opaque handoff prompt used when native resume is unavailable."""

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)
            if job is None:
                raise JobNotFoundError(f"Job {job_id} does not exist.")
            return await self._build_resume_handoff_prompt_for_job(session, job, instruction, job.session_count)

    async def create_followup_job(self, job_id: str, instruction: str) -> Job:
        """Create and start a new follow-up job with parent-job handoff context.

        Raises ValueError if the parent job has already been merged — once merged,
        the work is in the base branch and a follow-up must be started as a fresh job.
        """
        from backend.models.domain import PermissionMode

        normalized_instruction = instruction.strip()
        if not normalized_instruction:
            raise ValueError("Follow-up instruction must not be empty")

        async with self._session_factory() as session:
            svc = self._make_job_service(session)
            original = await svc.get_job(job_id)

            # Block follow-ups on already-merged jobs — the work is already in the
            # base branch, so a new job should be started from scratch instead.
            _merged_resolutions = (Resolution.merged, Resolution.pr_created)
            if original.resolution in _merged_resolutions:
                raise StateConflictError(
                    f"Job {job_id} has already been merged (resolution={original.resolution.value}). "
                    "Start a new job instead of creating a follow-up."
                )

            # Build a naming context hint so the LLM can produce a name that
            # reflects both the new instruction AND its follow-up relationship.
            parent_label = original.title or original.id
            parent_job_context = (
                f"This is a follow-up task continuing work from '{parent_label}' (parent job: {original.id})."
            )

            override_prompt = await self._build_followup_handoff_prompt_for_job(
                session,
                original,
                normalized_instruction,
            )
            followup = await svc.create_job(JobSpec(
                repo=original.repo,
                prompt=normalized_instruction,
                base_ref=original.base_ref,
                permission_mode=original.permission_mode or PermissionMode.full_auto,
                model=original.model,
                sdk=original.sdk,
                verify=original.verify,
                self_review=original.self_review,
                max_turns=original.max_turns,
                verify_prompt=original.verify_prompt,
                self_review_prompt=original.self_review_prompt,
                parent_job_id=original.id,
                parent_job_context=parent_job_context,
            ))
            await session.commit()

        if followup.state != JobState.failed:
            await self.start_or_enqueue(followup, override_prompt=override_prompt)
            async with self._session_factory() as session:
                followup = await self._make_job_service(session).get_job(followup.id)

        return followup

    async def resume_job(self, job_id: str, instruction: str | None = None) -> Job:
        """Resume a terminal or review job in-place.

        Primary path: reconnect to the existing Copilot SDK session (full conversation history
        intact, no summarization cost). Fallback: use LLM-generated session summary when the
        SDK session is no longer available (daemon restart, session expired, etc.).
        """

        resumable_states = TERMINAL_STATES | {JobState.review}
        normalized_instruction = _normalize_resume_instruction(instruction)

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)
            if job is None:
                raise JobNotFoundError(f"Job {job_id} does not exist.")
            if job.state not in resumable_states:
                raise StateConflictError(f"Job {job_id} is not in a resumable state (current: {job.state}).")

            previous_state = job.state
            previous_session_count = job.session_count
            previous_completed_at = job.completed_at
            previous_resolution = job.resolution
            previous_failure_reason = job.failure_reason
            previous_archived_at = job.archived_at
            previous_merge_status = job.merge_status
            previous_pr_url = job.pr_url
            resume_merge_status = (
                Resolution.conflict
                if previous_merge_status == Resolution.conflict or previous_resolution == Resolution.conflict
                else None
            )

            job = await self._ensure_resumable_worktree(job_repo, job)

            new_session_count = job.session_count + 1

            if job.sdk_session_id:
                # Primary path: SDK native session resume — full history intact, no summarization cost.
                log.info("resume_via_sdk_session", job_id=job_id, sdk_session_id=job.sdk_session_id)
                override_prompt = normalized_instruction
                resume_sdk_session_id: str | None = job.sdk_session_id
            else:
                log.info("resume_via_summarization", job_id=job_id)
                override_prompt = await self._build_resume_handoff_prompt_for_job(
                    session,
                    job,
                    normalized_instruction,
                    new_session_count,
                )
                resume_sdk_session_id = None

            await job_repo.reset_for_resume(job_id, new_session_count, merge_status=resume_merge_status)
            await session.commit()

        # Reload job and start execution
        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} not found after resume reset")

        try:
            await self.start_or_enqueue(
                job,
                override_prompt=override_prompt,
                resume_sdk_session_id=resume_sdk_session_id,
            )
        except Exception:
            log.error("resume_start_failed", job_id=job_id, exc_info=True)
            async with self._session_factory() as session:
                job_repo = JobRepository(session)
                await job_repo.restore_after_failed_resume(
                    job_id,
                    previous_state=previous_state,
                    previous_session_count=previous_session_count,
                    completed_at=previous_completed_at,
                    resolution=previous_resolution,
                    failure_reason=previous_failure_reason,
                    archived_at=previous_archived_at,
                    merge_status=previous_merge_status,
                    pr_url=previous_pr_url,
                )
                await session.commit()
            raise

        # Publish session_resumed only after startup succeeds so callers do not
        # see a false-positive resume when task initialization fails.
        now = datetime.now(UTC)
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.session_resumed,
                payload={
                    "session_number": new_session_count,
                    "instruction": normalized_instruction,
                    "timestamp": now.isoformat(),
                },
            )
        )
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.transcript_updated,
                payload={
                    "job_id": job_id,
                    "seq": 0,
                    "timestamp": now.isoformat(),
                    "role": TranscriptRole.operator,
                    "content": normalized_instruction,
                },
            )
        )

        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            reloaded = await job_repo.get(job_id)
        if reloaded is None:
            raise JobNotFoundError(f"Job {job_id} not found after start")
        return reloaded

    async def _cleanup_job_worktree(self, job: Job) -> None:
        """Remove the secondary worktree for a finished job (failed/canceled).

        The main worktree (where worktree_path == repo) is never removed.
        """
        import contextlib

        worktree_path = job.worktree_path
        if not worktree_path or worktree_path == job.repo:
            return  # main worktree — leave it alone
        from backend.services.git_service import GitError, GitService

        git = GitService(self._config)
        with contextlib.suppress(GitError, OSError):
            await git.remove_worktree(job.repo, worktree_path)
            log.info("worktree_cleaned_up", job_id=job.id, worktree=worktree_path)

    async def _try_create_pr(self, job_id: str) -> str | None:
        """Best-effort PR creation via platform adapter. Returns the PR URL or None."""
        if self._platform_registry is None:
            log.info("pr_creation_skipped_no_registry", job_id=job_id)
            return None

        async with self._session_factory() as session:
            svc = self._make_job_service(session)
            job = await svc.get_job(job_id)

        if job is None or not job.worktree_path or not job.branch:
            log.info("pr_creation_skipped_no_worktree", job_id=job_id)
            return None

        if not REF_PATTERN.match(job.branch):
            log.warning("pr_creation_invalid_branch", job_id=job_id)
            return None
        if not REF_PATTERN.match(job.base_ref):
            log.warning("pr_creation_invalid_base_ref", job_id=job_id)
            return None

        adapter = await self._platform_registry.get_adapter(job.repo)
        pr_result = await adapter.create_pr(
            cwd=job.worktree_path,
            head=job.branch,
            base=job.base_ref,
            title=f"[CodePlane] {job.prompt[:80]}",
            body=f"Automated PR created by CodePlane for job `{job_id}`.",
        )
        if pr_result.ok:
            log.info("pr_created", job_id=job_id, pr_url=pr_result.url, platform=adapter.name)
            return pr_result.url
        log.warning("pr_creation_failed", job_id=job_id, platform=adapter.name, error=pr_result.error)
        return None

    async def _publish_state_event(self, job_id: str, previous_state: str | None, new_state: str) -> None:
        """Publish a job state change event."""
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.job_state_changed,
                payload={
                    "previous_state": previous_state,
                    "new_state": new_state,
                },
            )
        )

    def _translate_event(self, job_id: str, event: SessionEvent) -> DomainEvent | None:
        """Translate a SessionEvent into a DomainEvent."""
        mapping: dict[SessionEventKind, DomainEventKind] = {
            SessionEventKind.log: DomainEventKind.log_line_emitted,
            SessionEventKind.transcript: DomainEventKind.transcript_updated,
            SessionEventKind.approval_request: DomainEventKind.approval_requested,
            SessionEventKind.error: DomainEventKind.job_failed,
            SessionEventKind.model_downgraded: DomainEventKind.model_downgraded,
        }
        kind = mapping.get(event.kind)
        if kind is None:
            # 'done' events are handled at the _run_job level
            return None
        return DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=kind,
            payload=event.payload,
        )

    async def recover_on_startup(self) -> None:
        """Recover from a previous crash by restarting active jobs and re-enqueueing queued ones."""
        # Restore in-memory futures for approvals that survived the restart
        # so that recovered jobs in waiting_for_approval can be unblocked.
        if self._approval_service is not None:
            await self._approval_service.recover_pending_approvals()

        orphaned_jobs: list[tuple[Job, JobState]] = []
        preparing_jobs: list[Job] = []
        async with self._session_factory() as session:
            svc = self._make_job_service(session)
            # Recover jobs that were already in progress before the backend restart.
            for state in (JobState.running, JobState.waiting_for_approval):
                jobs, _, _ = await svc.list_jobs(state=state, limit=10000)
                orphaned_jobs.extend((job, state) for job in jobs)

            # Re-enqueue queued jobs
            queued_jobs, _, _ = await svc.list_jobs(state=JobState.queued, limit=10000)

            # Re-run setup for jobs that were mid-preparation when we crashed
            preparing, _, _ = await svc.list_jobs(state=JobState.preparing, limit=10000)
            preparing_jobs.extend(preparing)

        for job in preparing_jobs:
            log.warning("recovering_preparing_job", job_id=job.id)
            asyncio.create_task(self.setup_and_start(job), name=f"recover-setup-{job.id}")

        for job, state in orphaned_jobs:
            log.warning("recovering_orphaned_job", job_id=job.id, state=state)
            await self._recover_active_job(job.id)

        for job in queued_jobs:
            await self.start_or_enqueue(job)

    async def shutdown(self) -> None:
        """Gracefully shut down all running jobs.

        Jobs are left in their current state (running / waiting_for_approval)
        so that ``recover_on_startup`` can pick them up on the next launch
        instead of marking them as canceled (which confused users).
        """
        self._shutting_down = True
        for job_id in list(self._tasks):
            task = self._tasks.get(job_id)
            if task is not None:
                task.cancel()
                log.info("shutdown_task_cancelled", job_id=job_id)
        # Wait briefly for tasks to complete
        tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        snapshot_tasks = list(self._snapshot_tasks.values())
        if snapshot_tasks:
            await asyncio.gather(*snapshot_tasks, return_exceptions=True)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down
