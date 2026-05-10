"""IngestService — thin bridge for imported CLI sessions.

Translates incoming data from Claude hooks and Copilot OTEL spans into
SessionEvent objects and feeds them through the shared EventProcessor
pipeline — the same path used by managed SDK sessions in RuntimeService.

Responsibilities:
  - Session lifecycle (job creation, state transitions, finalization)
  - Hook/OTEL payload → SessionEvent translation
  - Operator message delivery (hook injection / steer API)

Event processing (diffs, step tracking, trail enrichment) is delegated
entirely to EventProcessor.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.domain import Job, JobSource, JobState, Preset, SessionEvent, SessionEventKind
from backend.models.events import DomainEvent, DomainEventKind
from backend.services.tool_classifier import TOOL_CATEGORIES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.services.coderecon_service import CodeReconService
    from backend.services.copilot_steer import CopilotSteerClient
    from backend.services.event_bus import EventBus
    from backend.services.event_processor import EventProcessor
    from backend.services.git_service import GitService
    from backend.services.merge_service import MergeService
    from backend.services.sister_session import SisterSessionManager

log = structlog.get_logger()

# Background tasks tracked for clean shutdown
_bg_tasks: set[asyncio.Task] = set()


def _fire_bg(coro: Any, *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


# Tool categories that count as file writes (triggers diff + file_changed)
_WRITE_TOOLS = frozenset(
    name for name, cat in TOOL_CATEGORIES.items() if cat == "file_write"
)
_READ_TOOLS = frozenset(
    name for name, cat in TOOL_CATEGORIES.items() if cat in ("file_read", "file_search")
)


@dataclass
class _JobContext:
    """Per-job runtime context for the event processor."""

    worktree_path: str
    base_ref: str


class IngestService:
    """Bridge for imported CLI sessions — translates hooks/OTEL into the standard pipeline."""

    def __init__(
        self,
        event_bus: EventBus,
        event_processor: EventProcessor,
        session_factory: async_sessionmaker[AsyncSession],
        config: CPLConfig,
        git_service: GitService | None = None,
        merge_service: MergeService | None = None,
        coderecon_service: CodeReconService | None = None,
        steer_client: CopilotSteerClient | None = None,
        sister_sessions: SisterSessionManager | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._processor = event_processor
        self._session_factory = session_factory
        self._config = config
        self._git = git_service
        self._merge = merge_service
        self._coderecon = coderecon_service
        self._steer = steer_client
        self._sister_sessions = sister_sessions

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
        # Per-job turn counter for synthetic turn_ids
        self._turn_counters: dict[str, int] = {}
        # Per-job accumulated tool state for the current turn
        self._turn_tools: dict[str, list[str]] = {}  # job_id → [tool_name, ...]
        self._turn_files_read: dict[str, list[str]] = {}
        self._turn_files_written: dict[str, list[str]] = {}
        self._turn_duration_ms: dict[str, int] = {}  # job_id → accumulated ms
        # Per-job context (worktree/base_ref) for event processor
        self._job_ctx: dict[str, _JobContext] = {}

    def _next_seq(self, job_id: str) -> int:
        val = self._seq_counters.get(job_id, 0) + 1
        self._seq_counters[job_id] = val
        return val

    def _next_turn_id(self, job_id: str) -> str:
        """Generate a synthetic turn_id for the current agent turn."""
        val = self._turn_counters.get(job_id, 0) + 1
        self._turn_counters[job_id] = val
        return f"turn-{val}"

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
            model = payload.get("model") or None
            job = await self._create_job_from_session(
                cwd=cwd,
                source=JobSource.claude_cli,
                session_id=session_id,
                model=model,
            )
            return {"additionalContext": f"CodePlane is observing this session as job {job.id}."}

        job_id = self._session_to_job.get(session_id)
        if not job_id:
            log.debug("ingest_unknown_session", event_type=event_type, session_id=session_id)
            return {}

        if event_type == "UserPromptSubmit":
            content = payload.get("prompt") or payload.get("content", "")
            # Reset turn accumulators for the new turn
            self._turn_tools.pop(job_id, None)
            self._turn_files_read.pop(job_id, None)
            self._turn_files_written.pop(job_id, None)
            self._turn_duration_ms.pop(job_id, None)
            # Transition back to running if agent was idle (between turns)
            await self._ensure_running(job_id)
            # Feed operator message through the standard pipeline
            await self._feed_event(job_id, SessionEvent(
                kind=SessionEventKind.transcript,
                payload={"role": "operator", "content": content, "seq": self._next_seq(job_id),
                         "timestamp": datetime.now(UTC).isoformat()},
            ))
            # Set job prompt from first user message
            await self._maybe_set_job_prompt(job_id, content)
            # Capture permission_mode → preset mapping
            await self._maybe_set_preset_from_permission_mode(job_id, payload.get("permission_mode"))
            return {}

        if event_type == "PostToolUse":
            tool_name = payload.get("tool_name", "unknown")
            tool_input = payload.get("tool_input")
            tool_response = payload.get("tool_response")
            duration_ms = payload.get("duration_ms")

            # Build transcript event and feed through processor
            turn_id = f"turn-{self._turn_counters.get(job_id, 0) + 1}"
            await self._feed_event(job_id, SessionEvent(
                kind=SessionEventKind.transcript,
                payload={
                    "role": "tool_call",
                    "tool_name": tool_name,
                    "tool_args": json.dumps(tool_input) if tool_input else None,
                    "tool_result": json.dumps(tool_response) if tool_response else None,
                    "tool_duration_ms": duration_ms,
                    "turn_id": turn_id,
                    "seq": self._next_seq(job_id),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            ))

            # Accumulate for end-of-turn step_completed
            self._turn_tools.setdefault(job_id, []).append(tool_name)
            self._turn_duration_ms[job_id] = self._turn_duration_ms.get(job_id, 0) + (duration_ms or 0)

            # Track file paths for the step filter
            file_path = self._extract_file_path(tool_name, tool_input)
            if file_path:
                category = TOOL_CATEGORIES.get(tool_name, "other")
                if category == "file_write":
                    self._turn_files_written.setdefault(job_id, []).append(file_path)
                    # Emit file_changed so DiffService recalculates
                    await self._feed_event(job_id, SessionEvent(
                        kind=SessionEventKind.file_changed,
                        payload={"path": file_path},
                    ))
                elif category in ("file_read", "file_search"):
                    self._turn_files_read.setdefault(job_id, []).append(file_path)

            return {}

        if event_type == "PreToolUse":
            # Check for pending approval blocks
            return {}

        if event_type == "Stop":
            # Emit agent transcript from Claude's response
            assistant_msg = payload.get("last_assistant_message", "")
            if assistant_msg:
                turn_id = f"turn-{self._turn_counters.get(job_id, 0) + 1}"
                await self._feed_event(job_id, SessionEvent(
                    kind=SessionEventKind.transcript,
                    payload={"role": "agent", "content": assistant_msg, "turn_id": turn_id,
                             "seq": self._next_seq(job_id), "timestamp": datetime.now(UTC).isoformat()},
                ))

            # Emit step_completed with accumulated turn data (drives activity timeline)
            turn_id = self._next_turn_id(job_id)
            tool_names = self._turn_tools.pop(job_id, [])
            files_read = self._turn_files_read.pop(job_id, [])
            files_written = self._turn_files_written.pop(job_id, [])
            duration_ms = self._turn_duration_ms.pop(job_id, 0)
            await self._event_bus.publish(DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.step_completed,
                payload={
                    "turn_id": turn_id,
                    "agent_message": assistant_msg or "",
                    "tool_names": tool_names,
                    "tool_count": len(tool_names),
                    "duration_ms": duration_ms,
                    "files_read": files_read,
                    "files_written": files_written,
                },
            ))

            # Deliver any pending operator messages
            messages = self._pending_messages.pop(job_id, [])
            if messages:
                combined = "\n\n".join(messages)
                return {"decision": "block", "reason": combined}

            # Agent turn complete — transition to review (idle between turns)
            await self._transition_state(job_id, JobState.review)
            return {}

        if event_type == "SessionEnd":
            await self._finalize_session(job_id)
            return {}

        if event_type == "SubagentStart":
            return {}

        if event_type == "SubagentStop":
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

        # Map span to SessionEvents and feed through the standard processor
        if span_name.startswith("execute_tool"):
            tool_name = span_name.removeprefix("execute_tool ").strip() or span_name
            tool_args = attrs.get("gen_ai.tool.call.arguments")
            turn_id = f"turn-{self._turn_counters.get(job_id, 0) + 1}"
            await self._feed_event(job_id, SessionEvent(
                kind=SessionEventKind.transcript,
                payload={
                    "role": "tool_call",
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_result": attrs.get("gen_ai.tool.call.result"),
                    "turn_id": turn_id,
                    "seq": self._next_seq(job_id),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            ))

            # Accumulate turn state
            self._turn_tools.setdefault(job_id, []).append(tool_name)

            # Track file paths and emit file_changed for writes
            file_path = self._extract_file_path(tool_name, tool_args)
            if file_path:
                category = TOOL_CATEGORIES.get(tool_name, "other")
                if category == "file_write":
                    self._turn_files_written.setdefault(job_id, []).append(file_path)
                    await self._feed_event(job_id, SessionEvent(
                        kind=SessionEventKind.file_changed,
                        payload={"path": file_path},
                    ))
                elif category in ("file_read", "file_search"):
                    self._turn_files_read.setdefault(job_id, []).append(file_path)

        elif span_name.startswith("chat"):
            # LLM call — emit telemetry (this stays direct — telemetry isn't a SessionEvent)
            input_tokens = attrs.get("gen_ai.usage.input_tokens", 0)
            output_tokens = attrs.get("gen_ai.usage.output_tokens", 0)
            cost = attrs.get("github.copilot.cost", 0.0)
            model = attrs.get("gen_ai.response.model", "")
            await self._event_bus.publish(DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.telemetry_updated,
                payload={
                    "input_tokens": int(input_tokens),
                    "output_tokens": int(output_tokens),
                    "total_cost_usd": float(cost),
                    "model": model,
                },
            ))
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

    async def _feed_event(self, job_id: str, event: SessionEvent) -> None:
        """Feed a SessionEvent through the shared EventProcessor pipeline.

        This is the core bridge: hooks/OTEL translate to SessionEvent, then
        the same processing (diff, step tracking, trail) as managed sessions.
        """
        ctx = self._job_ctx.get(job_id)
        await self._processor.process_event(
            job_id,
            event,
            worktree_path=ctx.worktree_path if ctx else None,
            base_ref=ctx.base_ref if ctx else None,
        )

    @staticmethod
    def _extract_file_path(tool_name: str, tool_input: Any) -> str | None:
        """Best-effort extract file path from tool input."""
        if not tool_input:
            return None
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input) if tool_input.startswith("{") else {}
            except (ValueError, TypeError):
                return None
        if isinstance(tool_input, dict):
            return (
                tool_input.get("file_path")
                or tool_input.get("filePath")
                or tool_input.get("path")
                or tool_input.get("file")
            )
        return None

    async def _create_job_from_session(
        self,
        cwd: str,
        source: str,
        session_id: str,
        model: str | None = None,
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
            default_branch = await self._git.get_default_branch(repo_path)
        except Exception:
            default_branch = "main"

        # Resolve base_ref to a SHA so diff remains stable even when the agent
        # commits directly to the branch during the session.
        try:
            base_ref = await self._git.rev_parse("HEAD", cwd=cwd)
        except Exception:
            base_ref = default_branch

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
            model=model,
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

        # Assign a sister session so the title generator has LLM access
        if self._sister_sessions:
            self._sister_sessions.create_for_job(job_id)

        # Register worktree with event processor for diff/step tracking
        worktree_path = job.worktree_path or repo_path
        self._job_ctx[job_id] = _JobContext(worktree_path=worktree_path, base_ref=base_ref)
        self._processor.register_worktree(job_id, worktree_path)

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
        """Transition to completed and trigger post-session cleanup."""
        # Guard against double-finalize (duplicate SessionEnd, OTEL race)
        if job_id in self._finalized_jobs:
            log.debug("ingest_already_finalized", job_id=job_id)
            return
        self._finalized_jobs.add(job_id)

        # Verify current state allows transition (running or review/idle-between-turns)
        job = await self._get_job(job_id)
        if job and job.state not in (JobState.running, JobState.review):
            log.debug("ingest_finalize_wrong_state", job_id=job_id, state=job.state)
            return

        # If still running (SessionEnd without Stop), transition to review first
        if job and job.state == JobState.running:
            await self._transition_state(job_id, JobState.review)

        # Final diff calculation (bypasses throttle) before we clean up context
        ctx = self._job_ctx.get(job_id)
        if ctx and self._processor._diff_service:
            await self._processor._diff_service.finalize(
                job_id, ctx.worktree_path, ctx.base_ref
            )

        # Notify processor of terminal state (closes step tracker)
        await self._processor.on_job_terminal(job_id, JobState.review)

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

        # Release the sister session
        if self._sister_sessions:
            self._sister_sessions.close_job(job_id)

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

    async def _ensure_running(self, job_id: str) -> None:
        """Re-enter running state if agent was idle between turns (review state)."""
        job = await self._get_job(job_id)
        if job and job.state == JobState.review:
            await self._transition_state(job_id, JobState.running)

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

    # Map Claude CLI permission_mode values to CodePlane presets
    _PERMISSION_MODE_TO_PRESET: dict[str, str] = {
        "default": Preset.supervised,
        "acceptEdits": Preset.autonomous,
        "bypassPermissions": Preset.autonomous,
        "plan": Preset.strict,
    }

    async def _maybe_set_preset_from_permission_mode(self, job_id: str, permission_mode: str | None) -> None:
        """Map Claude CLI permission_mode to a CodePlane preset on first encounter."""
        if not permission_mode:
            return
        preset = self._PERMISSION_MODE_TO_PRESET.get(permission_mode)
        if not preset:
            return
        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository

            repo = JobRepository(session)
            job = await repo.get(job_id)
            # Only set once (don't overwrite if already non-default)
            if job and job.preset == Preset.supervised:
                await repo.update_preset(job_id, preset)
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
        self._turn_counters.pop(job_id, None)
        self._turn_tools.pop(job_id, None)
        self._turn_files_read.pop(job_id, None)
        self._turn_files_written.pop(job_id, None)
        self._turn_duration_ms.pop(job_id, None)
        self._job_ctx.pop(job_id, None)
        # Clean up processor state (step tracker, diff throttle)
        self._processor.cleanup(job_id)

    async def _get_job(self, job_id: str) -> Job | None:
        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository
            repo = JobRepository(session)
            return await repo.get(job_id)
