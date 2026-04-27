"""Job lifecycle orchestration."""

from __future__ import annotations

import asyncio
import glob
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from backend.config import load_config
from backend.models.domain import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    CodePlaneError,
    InvalidStateTransitionError,
    Job,
    JobNotFoundError,
    JobSpec,
    JobState,
    RepoNotAllowedError,
    Resolution,
    ServiceInitError,
    StateConflictError,
    validate_state_transition,
)
from backend.services.agent_adapter import validate_sdk_model
from backend.services.git_service import GitError
from backend.services.naming_service import NamingError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.config import CPLConfig
    from backend.models.events import DomainEvent, DomainEventKind
    from backend.persistence.event_repo import EventRepository
    from backend.persistence.job_repo import JobRepository
    from backend.services.event_bus import EventBus
    from backend.services.git_service import GitService
    from backend.services.merge_service import MergeService
    from backend.services.naming_service import NamingService

log = structlog.get_logger()

_MAX_COUNT_LIMIT = 10_000  # upper bound for count queries that scan all jobs


_MAX_NAMING_COLLISION_RETRIES = 2


@dataclass(frozen=True)
class ProgressPreview:
    headline: str
    summary: str


class JobService:
    """Orchestrates job creation, state transitions, and control actions."""

    def __init__(
        self,
        job_repo: JobRepository,
        git_service: GitService | None,
        config: CPLConfig,
        naming_service: NamingService | None = None,
        event_repo: EventRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._job_repo = job_repo
        self._git = git_service
        self._config = config
        self._naming = naming_service
        self._event_repo = event_repo
        self._event_bus = event_bus

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        config: CPLConfig,
        *,
        git_service: GitService | None = None,
        naming_service: NamingService | None = None,
    ) -> JobService:
        """Construct from a DB session."""
        from backend.persistence.event_repo import EventRepository
        from backend.persistence.job_repo import JobRepository

        job_repo = JobRepository(session)
        event_repo = EventRepository(session)
        if git_service is None:
            from backend.services.git_service import GitService

            git_service = GitService(config)
        return cls(
            job_repo=job_repo,
            git_service=git_service,
            config=config,
            naming_service=naming_service,
            event_repo=event_repo,
        )

    def _resolve_repos(self) -> set[str]:
        """Expand glob patterns and return the full set of allowed repo paths.

        Reads fresh from disk on every call so that repos registered after
        app startup (via the settings API) are immediately visible.
        """
        fresh_repos = load_config().repos
        allowed: set[str] = set()
        for pattern in fresh_repos:
            expanded = Path(pattern).expanduser()
            if "*" in pattern or "?" in pattern:
                for match in glob.glob(str(expanded), recursive=True):
                    p = Path(match).resolve()
                    if p.is_dir() and (p / ".git").exists():
                        allowed.add(str(p))
            else:
                allowed.add(str(expanded.resolve()))
        return allowed

    async def list_events_by_job(
        self,
        job_id: str,
        kinds: list[DomainEventKind],
        limit: int = 2000,
    ) -> list[DomainEvent]:
        """Query domain events for a job, filtered by kind.

        Delegates to the event repository so that API routes never need
        to import persistence classes directly.
        """
        if self._event_repo is None:
            raise ServiceInitError("JobService was created without an event_repo")
        return await self._event_repo.list_by_job(job_id, kinds, limit=limit)

    async def get_latest_progress_preview(self, job_id: str) -> ProgressPreview | None:
        """Return the latest persisted progress milestone for a job."""
        if self._event_repo is None:
            raise ServiceInitError("JobService was created without an event_repo")
        preview = await self._event_repo.get_latest_progress_preview(job_id)
        if preview is None:
            return None
        return ProgressPreview(headline=preview[0], summary=preview[1])

    async def list_latest_progress_previews(self, job_ids: list[str]) -> dict[str, ProgressPreview]:
        """Return the latest persisted progress milestone for each requested job."""
        if self._event_repo is None:
            raise ServiceInitError("JobService was created without an event_repo")
        previews = await self._event_repo.list_latest_progress_previews(job_ids)
        return {
            job_id: ProgressPreview(headline=headline, summary=summary)
            for job_id, (headline, summary) in previews.items()
        }

    def validate_repo(self, repo: str) -> str:
        """Validate a repo path is in the allowlist. Returns resolved path."""
        resolved = str(Path(repo).expanduser().resolve())
        allowed = self._resolve_repos()
        if resolved not in allowed:
            raise RepoNotAllowedError(f"Repository '{repo}' is not in the allowlist.")
        return resolved

    async def _generate_names_with_retry(
        self,
        spec: JobSpec,
        resolved_repo: str,
        branch: str | None,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Generate title/description/branch/worktree_name via the naming service.

        Retries if the generated worktree_name collides with an existing job.
        """
        existing_branches, existing_worktrees, existing_job_ids = await asyncio.gather(
            self._git.list_branches(resolved_repo),
            self._git.list_worktree_names(resolved_repo),
            self._job_repo.list_ids(),
        )
        exclude_names = existing_worktrees | existing_job_ids

        if self._naming is None:
            raise ServiceInitError("NamingService must be set before generating job metadata")
        title, description, generated_branch, worktree_name = await self._naming.generate(
            spec.prompt,
            existing_branches=existing_branches,
            existing_worktrees=exclude_names,
            parent_job_context=spec.parent_job_context,
        )
        if branch is None and generated_branch:
            branch = generated_branch

        for _retry in range(_MAX_NAMING_COLLISION_RETRIES):
            if worktree_name not in exclude_names and await self._job_repo.get(worktree_name) is None:
                break
            log.warning(
                "naming_collision_retry",
                worktree_name=worktree_name,
                attempt=_retry + 1,
            )
            exclude_names = exclude_names | {worktree_name}
            title, description, generated_branch, worktree_name = await self._naming.generate(
                spec.prompt,
                existing_branches=existing_branches,
                existing_worktrees=exclude_names,
                parent_job_context=spec.parent_job_context,
            )
            if branch is None and generated_branch:
                branch = generated_branch

        return title, description, branch, worktree_name

    async def _resolve_job_name(
        self,
        spec: JobSpec,
        resolved_repo: str,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Resolve title, description, branch, and worktree_name for a new job.

        Uses pre-computed names from the frontend if available, falls back to
        LLM naming, and finally to a hash-based fallback.

        Returns (title, description, branch, worktree_name).
        Raises NamingError (from naming_service) if LLM naming fails.
        """
        title = spec.title
        description = spec.description
        worktree_name = spec.worktree_name
        branch = spec.branch

        # When the frontend has pre-computed names via suggest-names, we can
        # skip the expensive LLM round-trip entirely.  We only need collision
        # checks (fast DB + git lookups).
        pre_named = title is not None and worktree_name is not None

        if pre_named:
            # Still verify the pre-computed worktree_name doesn't collide
            existing_job_ids = await self._job_repo.list_ids()
            if worktree_name in existing_job_ids or (
                await self._job_repo.get(worktree_name) is not None
            ):
                # Collision — fall through to LLM naming below
                log.info("pre_named_collision", worktree_name=worktree_name)
                pre_named = False
                title = None
                description = None
                worktree_name = None

        if not pre_named and self._naming is not None:
            title, description, branch, worktree_name = await self._generate_names_with_retry(
                spec, resolved_repo, branch
            )

        # When no naming service is configured (e.g. tests without LLM), use a hash.
        # Check existing IDs to avoid collisions on reruns of the same prompt.
        if worktree_name is None:
            import hashlib

            base_hash = hashlib.sha256(spec.prompt.encode()).hexdigest()[:8]
            candidate = f"task-{base_hash}"
            existing_ids = await self._job_repo.list_ids()
            counter = 0
            while candidate in existing_ids:
                counter += 1
                candidate = f"task-{base_hash}-{counter}"
            worktree_name = candidate

        return title, description, branch, worktree_name

    async def create_job(self, spec: JobSpec) -> Job:
        """Create a new job record in ``preparing`` state.

        Performs naming (LLM or pre-computed) and persists the job row, but
        does **not** create the worktree or start the agent.  Call
        :meth:`setup_workspace` in a background task to complete preparation.

        The job ID is the LLM-generated worktree name (e.g. "fix-login-bug").
        Naming is blocking: the LLM generates title, branch, and worktree name
        before the job is persisted. If naming fails, NamingError is raised
        and a failed job record is persisted with a hash-based ID.

        Returns the created Job domain object.
        Raises RepoNotAllowedError if the repo is not in the allowlist.
        """
        resolved_repo = self.validate_repo(spec.repo)

        if self._git is None:
            raise ServiceInitError("GitService required for job creation")

        resolved_sdk = spec.sdk or self._config.runtime.default_sdk

        # Validate SDK-model compatibility upfront
        validate_sdk_model(resolved_sdk, spec.model)

        # Determine base_ref
        base_ref = spec.base_ref
        if base_ref is None:
            base_ref = await self._git.get_default_branch(resolved_repo)

        now = datetime.now(UTC)

        try:
            title, description, branch, worktree_name = await self._resolve_job_name(spec, resolved_repo)
        except NamingError as exc:
            import hashlib

            h = hashlib.sha256(f"{spec.prompt}{now.isoformat()}".encode()).hexdigest()[:12]
            job_id = f"naming-failed-{h}"
            job = Job(
                id=job_id,
                repo=resolved_repo,
                prompt=spec.prompt,
                state=JobState.failed,
                base_ref=base_ref,
                branch=None,
                worktree_path=None,
                session_id=None,
                created_at=now,
                updated_at=now,
                completed_at=now,
                title=None,
                description=None,
                worktree_name=None,
                permission_mode=spec.permission_mode,
                model=spec.model,
                failure_reason=f"Naming failed: {exc}",
                parent_job_id=spec.parent_job_id,
            )
            await self._job_repo.create(job)
            log.error("job_naming_failed", job_id=job_id, error=str(exc))
            return job

        job_id = worktree_name

        # Final collision guard (covers both naming paths).
        # If after all retries the name still collides, append a numeric suffix.
        if await self._job_repo.get(job_id) is not None:
            existing_ids = await self._job_repo.list_ids()
            counter = 2
            while f"{job_id}-{counter}" in existing_ids:
                counter += 1
            job_id = f"{job_id}-{counter}"
            worktree_name = job_id
            log.warning("naming_collision_suffixed", job_id=job_id)
        log.info(
            "naming_preflight_complete",
            job_id=job_id,
            title=title,
            branch=branch,
            worktree_name=worktree_name,
        )

        # Persist in ``preparing`` state — worktree is created asynchronously
        # by the background setup task.
        initial_state = JobState.preparing

        job = Job(
            id=job_id,
            repo=resolved_repo,
            prompt=spec.prompt,
            state=initial_state,
            base_ref=base_ref,
            branch=branch,
            worktree_path=None,
            session_id=None,
            created_at=now,
            updated_at=now,
            title=title,
            description=description,
            worktree_name=worktree_name,
            permission_mode=spec.permission_mode,
            model=spec.model,
            sdk=resolved_sdk,
            verify=spec.verify,
            self_review=spec.self_review,
            max_turns=spec.max_turns,
            verify_prompt=spec.verify_prompt,
            self_review_prompt=spec.self_review_prompt,
            parent_job_id=spec.parent_job_id,
        )
        await self._job_repo.create(job)
        log.info("job_created", job_id=job_id, title=title, repo=resolved_repo, state=initial_state)
        return job

    async def setup_workspace(self, job_id: str) -> Job:
        """Create the worktree for a ``preparing`` job and transition to ``queued``.

        Called as a background task after the job row has been committed.
        Publishes ``job_setup_progress`` events during setup so the frontend
        can show a progress stepper.

        Returns the updated Job.
        Raises JobNotFoundError / StateConflictError on bad state.
        """
        from backend.models.events import DomainEvent, DomainEventKind

        if self._git is None:
            raise ServiceInitError("GitService required for workspace setup")

        job = await self._job_repo.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} does not exist.")
        if job.state != JobState.preparing:
            raise StateConflictError(f"Job {job_id} is in state {job.state!r}, expected 'preparing'.")

        async def _emit_progress(step: str) -> None:
            if self._event_bus is not None:
                await self._event_bus.publish(
                    DomainEvent(
                        event_id=DomainEvent.make_event_id(),
                        job_id=job_id,
                        timestamp=datetime.now(UTC),
                        kind=DomainEventKind.job_setup_progress,
                        payload={"step": step},
                    )
                )

        await _emit_progress("creating_workspace")

        try:
            worktree_path, branch_name = await self._git.create_worktree(
                repo_path=job.repo,
                job_id=job.worktree_name or job_id,
                base_ref=job.base_ref,
                branch=job.branch,
            )
        except GitError as exc:
            now = datetime.now(UTC)
            validate_state_transition(JobState.preparing, JobState.failed)
            await self._job_repo.update_state(job_id, JobState.failed, now)
            await self._job_repo.update_failure_reason(job_id, f"Worktree creation failed: {exc}")
            log.error("job_worktree_failed", job_id=job_id, error=str(exc))
            await _emit_progress("failed")
            job = await self._job_repo.get(job_id)
            if job is None:
                raise JobNotFoundError(f"Job {job_id} disappeared after state update")
            return job

        # Update the job with worktree info and transition to queued
        now = datetime.now(UTC)
        await self._job_repo.update_worktree(job_id, worktree_path, branch_name)
        validate_state_transition(JobState.preparing, JobState.queued)
        await self._job_repo.update_state(job_id, JobState.queued, now)

        await _emit_progress("workspace_ready")
        log.info("job_workspace_ready", job_id=job_id, worktree_path=worktree_path, branch=branch_name)

        job = await self._job_repo.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} disappeared after state update")
        return job

    async def get_job(self, job_id: str) -> Job:
        """Get a job by ID. Raises JobNotFoundError if not found."""
        job = await self._job_repo.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} does not exist.")
        return job

    async def list_jobs(
        self,
        state: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        archived: bool | None = None,
    ) -> tuple[list[Job], str | None, bool]:
        """List jobs with optional filtering and pagination.

        Args:
            archived: True = only archived, False = exclude archived, None = all.

        Returns (jobs, next_cursor, has_more).
        """
        include_archived: bool | None = None  # repo default: return all
        if archived is True:
            include_archived = True  # only archived
        elif archived is False:
            include_archived = False  # exclude archived

        jobs = await self._job_repo.list(
            state=state,
            limit=limit + 1,
            cursor=cursor,
            include_archived=include_archived,
        )
        has_more = len(jobs) > limit
        if has_more:
            jobs = jobs[:limit]
        next_cursor = jobs[-1].id if has_more and jobs else None
        return jobs, next_cursor, has_more

    async def transition_state(self, job_id: str, new_state: JobState, *, failure_reason: str | None = None) -> Job:
        """Transition a job's state. Validates the transition."""
        job = await self.get_job(job_id)
        validate_state_transition(job.state, new_state)

        now = datetime.now(UTC)
        completed_at = now if new_state in TERMINAL_STATES else None
        await self._job_repo.update_state(job_id, new_state, now, completed_at, failure_reason=failure_reason)

        job.state = new_state
        job.updated_at = now
        if completed_at:
            job.completed_at = completed_at
        if failure_reason is not None:
            job.failure_reason = failure_reason

        log.info("job_state_changed", job_id=job_id, new_state=new_state)
        return job

    async def cancel_job(self, job_id: str) -> Job:
        """Cancel a running or queued job and auto-archive it.

        Cancelled jobs are immediately archived so they don't clutter the
        Kanban board — cancellation is a deliberate operator action.
        """
        job = await self.get_job(job_id)
        if job.state in TERMINAL_STATES:
            raise StateConflictError(f"Cannot cancel job {job_id}: already in terminal state '{job.state}'.")
        try:
            job = await self.transition_state(job_id, JobState.canceled)
        except InvalidStateTransitionError as exc:
            raise StateConflictError(str(exc)) from exc
        await self._job_repo.update_archived_at(job_id, datetime.now(UTC))
        return await self.get_job(job_id)

    async def rerun_job(self, job_id: str) -> Job:
        """Create a new job from an existing job's configuration."""
        original = await self.get_job(job_id)
        return await self.create_job(JobSpec(
            repo=original.repo,
            prompt=original.prompt,
            base_ref=original.base_ref,
            permission_mode=original.permission_mode,
            model=original.model,
            sdk=original.sdk,
        ))

    async def count_active_jobs(self) -> int:
        """Count currently active (non-terminal) jobs."""
        jobs = await self._job_repo.list(
            state=",".join(ACTIVE_STATES),
            limit=_MAX_COUNT_LIMIT,
        )
        return len(jobs)

    async def count_queued_jobs(self) -> int:
        """Count queued jobs."""
        jobs = await self._job_repo.list(state=JobState.queued, limit=_MAX_COUNT_LIMIT)
        return len(jobs)

    async def resolve_job(self, job_id: str) -> Job:
        """Validate that a job is eligible for resolution.

        Raises StateConflictError if the job state or current resolution
        prevents the requested action.
        """
        job = await self.get_job(job_id)
        if job.state != JobState.review:
            raise StateConflictError(f"Job {job_id} is in state {job.state!r}, not 'review'")
        if job.resolution not in (None, Resolution.unresolved, Resolution.conflict):
            raise StateConflictError(f"Job {job_id} already resolved as {job.resolution!r}")
        return job

    async def execute_resolve(
        self,
        job: Job,
        action: str,
        merge_service: MergeService,
    ) -> tuple[Resolution, str | None, list[str] | None, str | None]:
        """Execute merge/PR/discard resolution and persist the outcome.

        On successful resolution (merged, pr_created, discarded), the job
        transitions from ``review`` → ``completed``.  On conflict, it stays
        in ``review`` with resolution ``conflict``.

        Returns (resolution, pr_url, conflict_files, error).
        """
        result = await merge_service.resolve_job(job, action)

        from backend.services.merge_service import MergeStatus

        status_map = {
            MergeStatus.merged: Resolution.merged,
            MergeStatus.pr_created: Resolution.pr_created,
            MergeStatus.conflict: Resolution.conflict,
            MergeStatus.skipped: Resolution.discarded if action == "discard" else Resolution.unresolved,
            MergeStatus.error: Resolution.unresolved,
        }
        resolution = status_map.get(result.status, Resolution.unresolved)

        if result.error:
            log.warning(
                "job_resolution_failed",
                job_id=job.id,
                action=action,
                merge_status=str(result.status),
                error=result.error,
            )

        # Persist resolution
        await self._job_repo.update_resolution(job.id, resolution, pr_url=result.pr_url)

        # Transition review → completed for final resolutions
        final_resolutions = (Resolution.merged, Resolution.pr_created, Resolution.discarded)
        if resolution in final_resolutions and job.state == JobState.review:
            await self.transition_state(job.id, JobState.completed)

        return resolution, result.pr_url, result.conflict_files, result.error

    async def resolve_and_complete(
        self,
        job: Job,
        action: str,
        merge_service: MergeService,
    ) -> tuple[Resolution, str | None, list[str] | None, str | None, list[DomainEvent]]:
        """Full resolve protocol: execute merge, persist result, build events.

        Returns (resolution, pr_url, conflict_files, error, events_to_publish).
        The caller should commit the session and then publish the events.
        """
        from backend.models.events import DomainEvent, DomainEventKind

        resolution, pr_url, conflict_files, error = await self.execute_resolve(
            job=job, action=action, merge_service=merge_service,
        )

        events: list[DomainEvent] = [
            self.build_job_resolved_event(
                job.id, resolution, pr_url=pr_url,
                conflict_files=conflict_files, error=error,
            )
        ]

        if resolution in (Resolution.merged, Resolution.pr_created, Resolution.discarded):
            events.append(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job.id,
                    timestamp=datetime.now(UTC),
                    kind=DomainEventKind.job_completed,
                    payload={
                        "resolution": resolution,
                        "merge_status": resolution,
                        "pr_url": pr_url,
                    },
                )
            )

        return resolution, pr_url, conflict_files, error, events

    def build_job_resolved_event(
        self,
        job_id: str,
        resolution: Resolution,
        *,
        pr_url: str | None = None,
        conflict_files: list[str] | None = None,
        error: str | None = None,
    ) -> DomainEvent:
        """Build a job_resolved event for publication after the caller commits."""
        from backend.models.events import DomainEvent, DomainEventKind

        payload: dict[str, object] = {"resolution": resolution}
        if pr_url:
            payload["pr_url"] = pr_url
        if conflict_files:
            payload["conflict_files"] = conflict_files
        if error:
            payload["error"] = error

        return DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.job_resolved,
            payload=payload,
        )

    async def archive_job(self, job_id: str) -> Job:
        """Archive a job (hide from Kanban board) and clean up its worktree."""
        job = await self.get_job(job_id)
        if job.state not in TERMINAL_STATES:
            raise StateConflictError(f"Job {job_id} is in state {job.state!r}, cannot archive active jobs")
        await self._job_repo.update_archived_at(job_id, datetime.now(UTC))

        # Clean up worktree and branch immediately rather than waiting for
        # the daily retention sweep — the UI promises this happens on archive.
        if self._git and job.worktree_path and job.worktree_path != job.repo:
            try:
                await self._git.remove_worktree(job.repo, job.worktree_path)
                log.info("archive_worktree_removed", job_id=job_id, worktree=job.worktree_path)
            except (GitError, OSError):
                log.warning("archive_worktree_cleanup_failed", job_id=job_id, exc_info=True)

        return await self.get_job(job_id)

    def build_job_archived_event(self, job_id: str) -> DomainEvent:
        """Build a job_archived event for publication after the caller commits."""
        from backend.models.events import DomainEvent, DomainEventKind

        return DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.job_archived,
            payload={},
        )
