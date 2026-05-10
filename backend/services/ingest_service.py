"""IngestService — central coordinator for imported CLI sessions.

Routes incoming data from Claude hooks and Copilot OTEL spans into
the standard CodePlane event pipeline (EventBus → SSE → persistence).
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.domain import Job, JobSource, JobState
from backend.models.events import DomainEvent, DomainEventKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.persistence.job_repo import JobRepository
    from backend.services.coderecon_service import CodeReconService
    from backend.services.copilot_steer import CopilotSteerClient
    from backend.services.diff_service import DiffService
    from backend.services.event_bus import EventBus
    from backend.services.git_service import GitService
    from backend.services.merge_service import MergeService
    from backend.services.trail import TrailService

log = structlog.get_logger()

# Background tasks tracked for clean shutdown
_bg_tasks: set[asyncio.Task] = set()


def _fire_bg(coro: Any, *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


class IngestService:
    """Ingests events from native CLI sessions and maps them to DomainEvents."""

    def __init__(
        self,
        event_bus: EventBus,
        session_factory: async_sessionmaker[AsyncSession],
        config: CPLConfig,
        git_service: GitService | None = None,
        diff_service: DiffService | None = None,
        merge_service: MergeService | None = None,
        trail_service: TrailService | None = None,
        coderecon_service: CodeReconService | None = None,
        steer_client: CopilotSteerClient | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._config = config
        self._git = git_service
        self._diff = diff_service
        self._merge = merge_service
        self._trail = trail_service
        self._coderecon = coderecon_service
        self._steer = steer_client

        # Per-session state: external_session_id → job_id
        self._session_to_job: dict[str, str] = {}
        # Pending operator messages for Claude hook injection
        self._pending_messages: dict[str, list[str]] = {}
        # Sequence counters per job
        self._seq_counters: dict[str, int] = {}
        # Copilot conversation_id → job_id (OTEL demux)
        self._conversation_to_job: dict[str, str] = {}
        # Guard set for double-finalize protection
        self._finalized_jobs: set[str] = set()

    def _next_seq(self, job_id: str) -> int:
        val = self._seq_counters.get(job_id, 0) + 1
        self._seq_counters[job_id] = val
        return val

    # ------------------------------------------------------------------
    # Claude hooks
    # ------------------------------------------------------------------

    async def ingest_claude_hook(self, event_type: str, payload: dict) -> dict:
        """Process a Claude hook POST. Returns the hook response body."""
        session_id = payload.get("session_id", "")
        if not session_id:
            log.warning("ingest_empty_session_id", event_type=event_type)
            return {}
        cwd = payload.get("cwd", "")

        if event_type == "SessionStart":
            # Idempotent: if session already tracked, return existing job id
            existing_job_id = self._session_to_job.get(session_id)
            if existing_job_id:
                return {"additionalContext": f"CodePlane is observing this session as job {existing_job_id}."}
            job = await self._create_job_from_session(
                cwd=cwd,
                source=JobSource.claude_cli,
                session_id=session_id,
            )
            return {"additionalContext": f"CodePlane is observing this session as job {job.id}."}

        job_id = self._session_to_job.get(session_id)
        if not job_id:
            log.debug("ingest_unknown_session", event_type=event_type, session_id=session_id)
            return {}

        if event_type == "UserPromptSubmit":
            content = payload.get("prompt") or payload.get("content", "")
            await self._emit_transcript(job_id, role="operator", content=content)
            # Set job prompt from first user message
            await self._maybe_set_job_prompt(job_id, content)
            return {}

        if event_type == "PostToolUse":
            tool_name = payload.get("tool_name", "unknown")
            tool_input = payload.get("tool_input")
            tool_response = payload.get("tool_response")
            duration_ms = payload.get("duration_ms")
            await self._emit_transcript(
                job_id,
                role="tool_call",
                tool_name=tool_name,
                tool_args=str(tool_input) if tool_input else None,
                tool_result=str(tool_response) if tool_response else None,
                tool_duration_ms=duration_ms,
            )
            return {}

        if event_type == "PreToolUse":
            # Check for pending approval blocks
            return {}

        if event_type == "Stop":
            # Emit agent transcript from Claude's response
            assistant_msg = payload.get("last_assistant_message", "")
            if assistant_msg:
                await self._emit_transcript(job_id, role="agent", content=assistant_msg)

            # Deliver any pending operator messages
            messages = self._pending_messages.pop(job_id, [])
            if messages:
                combined = "\n\n".join(messages)
                return {"decision": "block", "reason": combined}
            return {}

        if event_type == "SessionEnd":
            await self._finalize_session(job_id)
            return {}

        if event_type == "SubagentStart":
            await self._emit_step_started(job_id, intent=payload.get("agent_type", "subagent"))
            return {}

        if event_type == "SubagentStop":
            await self._emit_step_completed(job_id)
            return {}

        log.debug("ingest_unhandled_hook", event_type=event_type, session_id=session_id)
        return {}

    # ------------------------------------------------------------------
    # Copilot OTEL spans
    # ------------------------------------------------------------------

    async def ingest_otel_span(self, span: dict) -> None:
        """Process a single OTEL JSONL span from the Copilot file watcher."""
        attrs = span.get("attributes", {})
        span_name = span.get("name", "")
        conversation_id = attrs.get("gen_ai.conversation.id", "")

        if not conversation_id:
            return

        job_id = self._conversation_to_job.get(conversation_id)

        # First span for this conversation → create job
        if job_id is None:
            cwd = self._infer_cwd_from_span(span)
            if not cwd:
                log.debug("otel_no_cwd_skip", conversation_id=conversation_id)
                return
            job = await self._create_job_from_session(
                cwd=cwd,
                source=JobSource.copilot_cli,
                session_id=conversation_id,
            )
            job_id = job.id
            self._conversation_to_job[conversation_id] = job_id

        # Map span to events
        if span_name.startswith("execute_tool"):
            tool_name = span_name.removeprefix("execute_tool ").strip() or span_name
            await self._emit_transcript(
                job_id,
                role="tool_call",
                tool_name=tool_name,
                tool_args=attrs.get("gen_ai.tool.call.arguments"),
                tool_result=attrs.get("gen_ai.tool.call.result"),
            )
        elif span_name.startswith("chat"):
            # LLM call — emit telemetry
            input_tokens = attrs.get("gen_ai.usage.input_tokens", 0)
            output_tokens = attrs.get("gen_ai.usage.output_tokens", 0)
            cost = attrs.get("github.copilot.cost", 0.0)
            model = attrs.get("gen_ai.response.model", "")
            await self._emit_telemetry(
                job_id,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cost_usd=float(cost),
                model=model,
            )
        elif span_name == "invoke_agent":
            # Check for span end (non-zero duration means session finished)
            duration = span.get("duration", 0)
            if duration and duration > 0:
                await self._finalize_session(job_id)

    def _infer_cwd_from_span(self, span: dict) -> str | None:
        """Try to extract working directory from OTEL span data."""
        # Check resource attributes first (user-configured)
        resource = span.get("resource", {})
        resource_attrs = resource.get("attributes", {})
        cwd = resource_attrs.get("process.cwd")
        if cwd:
            return str(cwd)

        # Inferring from tool arguments is risky (untrusted data); skip it
        # to avoid filesystem probing via crafted OTEL spans.
        return None

    # ------------------------------------------------------------------
    # Operator messaging
    # ------------------------------------------------------------------

    async def send_operator_message(self, job_id: str, message: str) -> None:
        """Queue an operator message for delivery to the agent."""
        # Check which source this job uses
        job = await self._get_job(job_id)
        if not job:
            return

        if job.source == JobSource.claude_cli:
            # Queue for next Stop hook response
            self._pending_messages.setdefault(job_id, []).append(message)
            log.info("operator_message_queued_claude", job_id=job_id)
        elif job.source == JobSource.copilot_cli and self._steer:
            ext_id = job.external_session_id
            if ext_id:
                await self._steer.send_message(ext_id, message)
                log.info("operator_message_sent_copilot", job_id=job_id)
        else:
            log.warning("operator_message_no_channel", job_id=job_id, source=job.source)

    async def abort_session(self, job_id: str) -> None:
        """Abort the external session.

        Note: the caller (cancel_job endpoint) already transitions job state
        to canceled via JobService.cancel_job(). This method only handles
        the external agent communication (hook message or steer API).
        """
        job = await self._get_job(job_id)
        if not job:
            return

        if job.source == JobSource.claude_cli:
            # Queue a block response for the next hook event
            self._pending_messages.setdefault(job_id, []).append(
                "OPERATOR: Session abort requested. Please stop immediately."
            )
        elif job.source == JobSource.copilot_cli and self._steer:
            ext_id = job.external_session_id
            if ext_id:
                await self._steer.abort(ext_id)

        # Clean up in-memory state
        self._cleanup_session(job_id)
        self._finalized_jobs.add(job_id)  # Prevent further finalization

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_job_from_session(
        self,
        cwd: str,
        source: str,
        session_id: str,
    ) -> Job:
        """Detect git metadata from cwd, create Job record."""
        if not self._git:
            raise RuntimeError("GitService required for session import")

        # Resolve git root from cwd
        try:
            repo_root = await self._git._run_git(  # noqa: SLF001
                "rev-parse", "--show-toplevel", cwd=cwd,
            )
            repo_path = repo_root.strip()
        except Exception:
            repo_path = cwd

        # Auto-register repo in allowlist if not present
        from backend.config import register_repo
        register_repo(self._config, repo_path)

        # Detect branch and base_ref
        try:
            branch = await self._git.get_current_branch(cwd=cwd)
        except Exception:
            branch = "unknown"

        try:
            base_ref = await self._git.get_default_branch(repo_path)
        except Exception:
            base_ref = "main"

        # Generate a deterministic job ID
        hex_suffix = hashlib.sha256(session_id.encode()).hexdigest()[:6]
        repo_slug = Path(repo_path).name
        job_id = f"{repo_slug}-{hex_suffix}"

        now = datetime.now(UTC)
        job = Job(
            id=job_id,
            repo=repo_path,
            prompt="(imported CLI session)",
            state=JobState.running,
            base_ref=base_ref,
            branch=branch,
            worktree_path=cwd,
            session_id=None,
            created_at=now,
            updated_at=now,
            sdk="claude" if source == JobSource.claude_cli else "copilot",
            source=source,
            external_session_id=session_id,
        )

        # Persist
        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository
            repo = JobRepository(session)
            await repo.create(job)
            await session.commit()

        self._session_to_job[session_id] = job_id

        # Publish creation events
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.job_created,
            payload={
                "repo": repo_path,
                "branch": branch,
                "base_ref": base_ref,
                "source": source,
                "prompt": job.prompt,
            },
        ))
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.job_state_changed,
            payload={"state": JobState.running, "new_state": JobState.running},
        ))

        # Background: CodeRecon indexing
        if self._coderecon:
            async def _index() -> None:
                try:
                    await self._coderecon.ensure_repo_indexed(repo_path)
                    log.info("ingest_coderecon_indexed", job_id=job_id, repo=repo_path)
                except Exception:
                    log.debug("ingest_coderecon_failed", job_id=job_id, exc_info=True)
            _fire_bg(_index(), name=f"ingest-coderecon-{job_id[:8]}")

        log.info("ingest_job_created", job_id=job_id, source=source, repo=repo_path, branch=branch)
        return job

    async def _finalize_session(self, job_id: str) -> None:
        """Transition to review and trigger post-session merge flow."""
        # Guard against double-finalize (duplicate SessionEnd, OTEL race)
        if job_id in self._finalized_jobs:
            log.debug("ingest_already_finalized", job_id=job_id)
            return
        self._finalized_jobs.add(job_id)

        # Verify current state allows transition
        job = await self._get_job(job_id)
        if job and job.state != JobState.running:
            log.debug("ingest_finalize_wrong_state", job_id=job_id, state=job.state)
            return

        await self._transition_state(job_id, JobState.review)

        # Publish job_review event (triggers existing review story prefetch etc.)
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.job_review,
            payload={},
        ))

        # Clean up in-memory tracking for this session
        self._cleanup_session(job_id)

        log.info("ingest_session_finalized", job_id=job_id)

    async def _transition_state(self, job_id: str, new_state: JobState) -> None:
        """Transition job state and emit event."""
        now = datetime.now(UTC)
        completed_at = now if new_state in (JobState.completed, JobState.failed, JobState.canceled) else None

        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository
            repo = JobRepository(session)
            await repo.update_state(job_id, new_state, now, completed_at=completed_at)
            await session.commit()

        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.job_state_changed,
            payload={"state": new_state, "new_state": new_state},
        ))

    async def _emit_transcript(
        self,
        job_id: str,
        *,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_args: str | None = None,
        tool_result: str | None = None,
        tool_duration_ms: int | None = None,
    ) -> None:
        """Publish a transcript_updated DomainEvent."""
        seq = self._next_seq(job_id)
        payload: dict[str, Any] = {
            "seq": seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "role": role,
        }
        if content is not None:
            payload["content"] = content
        if tool_name is not None:
            payload["tool_name"] = tool_name
        if tool_args is not None:
            payload["tool_args"] = tool_args
        if tool_result is not None:
            payload["tool_result"] = tool_result
        if tool_duration_ms is not None:
            payload["tool_duration_ms"] = tool_duration_ms

        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.transcript_updated,
            payload=payload,
        ))

    async def _emit_telemetry(
        self,
        job_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        model: str = "",
    ) -> None:
        """Publish a telemetry_updated DomainEvent."""
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.telemetry_updated,
            payload={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_cost_usd": cost_usd,
                "model": model,
            },
        ))

    async def _emit_step_started(self, job_id: str, intent: str) -> None:
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.step_started,
            payload={"intent": intent},
        ))

    async def _emit_step_completed(self, job_id: str) -> None:
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.step_completed,
            payload={},
        ))

    async def _maybe_set_job_prompt(self, job_id: str, content: str) -> None:
        """Set job prompt from first user message (replaces placeholder)."""
        if not content:
            return
        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository

            repo = JobRepository(session)
            job = await repo.get(job_id)
            if job and job.prompt == "(imported CLI session)":
                await repo.update_prompt(job_id, content[:500])
                await session.commit()

    def _cleanup_session(self, job_id: str) -> None:
        """Remove in-memory tracking state for a completed session."""
        # Find and remove from session/conversation maps
        stale_session_keys = [k for k, v in self._session_to_job.items() if v == job_id]
        for k in stale_session_keys:
            del self._session_to_job[k]
        stale_conv_keys = [k for k, v in self._conversation_to_job.items() if v == job_id]
        for k in stale_conv_keys:
            del self._conversation_to_job[k]
        self._pending_messages.pop(job_id, None)
        self._seq_counters.pop(job_id, None)

    async def _get_job(self, job_id: str) -> Job | None:
        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository
            repo = JobRepository(session)
            return await repo.get(job_id)
