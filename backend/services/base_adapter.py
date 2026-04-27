"""Base agent adapter — shared infrastructure for all SDK adapters.

Owns state management, queue helpers, DB write scheduling, telemetry
recording, permission evaluation, model verification, retry tracking,
tool span recording, and session cleanup.  Concrete adapters (Claude,
Copilot, …) subclass and override only the SDK-specific hooks.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

import structlog

from sqlalchemy.exc import DBAPIError

from backend.models.api_schemas import ExecutionPhase
from backend.models.domain import (
    ApprovalResolution,
    PermissionMode,
    SessionEvent,
    SessionEventKind,
)
from backend.services.agent_adapter import AgentAdapterInterface, normalize_model_name
from backend.services.parsing_utils import ensure_dict
from backend.services.permission_policy import (
    PolicyDecision,
    evaluate,
    is_git_reset_hard,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.approval_service import ApprovalService
    from backend.services.event_bus import EventBus
    from backend.services.retry_tracker import RetryTracker

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Shared adapter constants
# ---------------------------------------------------------------------------

# Truncation limits for approval action payloads and tool summaries (characters)
_TOOL_ACTION_MAX_CHARS = 2000
_TOOL_SUMMARY_MAX_CHARS = 200
_TOOL_SUMMARY_FALLBACK_CHARS = 120

# SDK event stream queue timeout: if no event arrives within this window the
# stream is considered stale.  330s accommodates long LLM generations plus a
# safety margin over the typical ~300s provider timeout.
STREAM_EVENT_TIMEOUT_S = 330

# Single-turn completion timeout used by the `complete()` helper.
COMPLETION_TIMEOUT_S = 180

# Grace period for stopping a running SDK client process.
CLIENT_STOP_TIMEOUT_S = 10


class PermissionDecision(StrEnum):
    """Result of the SDK-agnostic permission evaluation."""

    allow = "allow"
    deny = "deny"


class BaseAgentAdapter(AgentAdapterInterface):
    """Shared infrastructure for all SDK adapters.

    Concrete adapters must call ``super().__init__(...)`` and override the
    abstract methods from :class:`AgentAdapterInterface`.  All shared state
    (queues, telemetry dicts, retry trackers, …) lives here.
    """

    _MAX_PENDING_WRITES = 20  # limit concurrent fire-and-forget DB tasks
    _TELEMETRY_BROADCAST_INTERVAL = 2.0  # seconds — debounce SSE broadcasts

    def __init__(
        self,
        approval_service: ApprovalService | None = None,
        event_bus: EventBus | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._queues: dict[str, asyncio.Queue[SessionEvent | None]] = {}
        self._clients: dict[str, Any] = {}  # SDK client type varies by adapter subclass
        self._session_to_job: dict[str, str] = {}
        self._paused_sessions: set[str] = set()
        self._tool_start_times: dict[str, float] = {}
        self._pending_tool_metadata: dict[str, dict[str, str]] = {}
        self._approval_service = approval_service
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._job_start_times: dict[str, float] = {}
        self._job_main_models: dict[str, str] = {}
        self._last_telemetry_broadcast: dict[str, float] = {}
        self._turn_counters: dict[str, int] = {}
        self._current_phases: dict[str, str] = {}
        self._retry_trackers: dict[str, RetryTracker] = {}
        self._write_tasks: list[asyncio.Task[None]] = []
        # Ring buffer of recent transcript entries per job for motivation capture.
        # Each entry is a compact dict with role, content (truncated), and optional
        # tool_name.  Kept to _TRANSCRIPT_BUFFER_SIZE entries per job.
        self._transcript_buffers: dict[str, list[dict[str, str]]] = {}

    # Ring buffer size per job: 10 entries × ~2KB each ≈ 20KB per active job.
    # With typical 5–20 concurrent jobs this keeps total transcript memory
    # under 400KB while retaining enough context for motivation extraction.
    _TRANSCRIPT_BUFFER_SIZE = 10

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _enqueue(self, session_id: str, event: SessionEvent) -> None:
        q = self._queues.get(session_id)
        if q is not None:
            q.put_nowait(event)
        # Buffer transcript events for motivation context capture
        if event.kind == SessionEventKind.transcript:
            self._buffer_transcript(session_id, event.payload)

    # ------------------------------------------------------------------
    # Transcript ring buffer for motivation context
    # ------------------------------------------------------------------

    _TRANSCRIPT_CONTENT_MAX = 800  # truncate content in buffer entries

    def _buffer_transcript(self, session_id: str, payload: dict[str, Any]) -> None:
        """Append a compact transcript entry to the per-job ring buffer."""
        job_id = self._session_to_job.get(session_id)
        if not job_id:
            return
        role = payload.get("role", "")
        # Skip deltas — only buffer complete messages and tool calls
        if role in ("agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"):
            return
        content = str(payload.get("content", ""))[:self._TRANSCRIPT_CONTENT_MAX]
        entry: dict[str, str] = {"role": role, "content": content}
        tool_name = payload.get("tool_name")
        if tool_name:
            entry["tool_name"] = str(tool_name)
            tool_args = payload.get("tool_args")
            if tool_args:
                entry["tool_args"] = str(tool_args)[:self._TRANSCRIPT_CONTENT_MAX]
        buf = self._transcript_buffers.setdefault(job_id, [])
        buf.append(entry)
        # Trim to ring buffer size
        if len(buf) > self._TRANSCRIPT_BUFFER_SIZE:
            del buf[: len(buf) - self._TRANSCRIPT_BUFFER_SIZE]

    def _snapshot_preceding_context(self, job_id: str, count: int = 5) -> str | None:
        """Return JSON array of the last *count* transcript entries, or None."""
        buf = self._transcript_buffers.get(job_id)
        if not buf:
            return None
        entries = buf[-count:]
        return json.dumps(entries, ensure_ascii=False)

    # Mutative shell command prefixes — commands that modify the filesystem,
    # repository, or environment.  Matched against the first token(s) of a
    # bash tool's command string.
    _MUTATIVE_SHELL_PREFIXES: frozenset[str] = frozenset({
        "git commit", "git add", "git push", "git checkout", "git merge",
        "git rebase", "git reset", "git stash", "git cherry-pick", "git tag",
        "git branch -d", "git branch -D", "git branch -m",
        "mkdir", "mv", "rm", "cp", "ln", "chmod", "chown", "touch",
        "pip install", "pip uninstall",
        "uv add", "uv remove", "uv sync", "uv pip install",
        "npm install", "npm uninstall", "npm ci", "yarn add", "yarn remove",
        "pnpm add", "pnpm remove",
        "docker build", "docker run", "docker compose up",
        "make", "cargo build", "go build",
    })

    @classmethod
    def _is_mutative_shell(cls, tool_args_str: str | None) -> bool:
        """Return True if the shell command appears to modify state."""
        if not tool_args_str:
            return False
        parsed = ensure_dict(tool_args_str)
        if parsed is None:
            return False
        cmd = str(parsed.get("command", ""))
        if not cmd:
            return False
        cmd_lower = cmd.strip().lower()
        return any(cmd_lower.startswith(prefix) for prefix in cls._MUTATIVE_SHELL_PREFIXES)

    def _maybe_capture_context(
        self, job_id: str, category: str, tool_args_str: str | None,
    ) -> str | None:
        """Capture preceding transcript context for mutative tool actions."""
        if category in {"file_write", "git_write"}:
            return self._snapshot_preceding_context(job_id)
        if category == "shell" and self._is_mutative_shell(tool_args_str):
            return self._snapshot_preceding_context(job_id)
        return None

    def _enqueue_log(
        self,
        session_id: str,
        message: str,
        level: str = "info",
        seq: list[int] | None = None,
    ) -> None:
        """Enqueue a log event for the session.

        When *seq* is provided it is **mutated in-place** (``seq[0]`` is
        incremented) so the caller's counter stays in sync.
        """
        if seq is not None:
            seq[0] += 1
        self._enqueue(
            session_id,
            SessionEvent(
                kind=SessionEventKind.log,
                payload={
                    "seq": seq[0] if seq else 0,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": level,
                    "message": message,
                },
            ),
        )

    # ------------------------------------------------------------------
    # Session state
    # ------------------------------------------------------------------

    def set_job_id(self, session_id: str, job_id: str) -> None:
        """Associate a session with a job for telemetry routing."""
        self._session_to_job[session_id] = job_id
        self._job_start_times.setdefault(job_id, time.monotonic())

    def set_execution_phase(self, job_id: str, phase: ExecutionPhase) -> None:
        """Update the current execution phase for cost analytics span tagging."""
        self._current_phases[job_id] = phase

    def pause_tools(self, session_id: str) -> None:
        self._paused_sessions.add(session_id)

    def resume_tools(self, session_id: str) -> None:
        self._paused_sessions.discard(session_id)

    # Per-job tracking dicts cleaned up together in _cleanup_session_state
    _JOB_TRACKING_DICTS: ClassVar[tuple[str, ...]] = (
        "_job_start_times",
        "_job_main_models",
        "_last_telemetry_broadcast",
        "_turn_counters",
        "_current_phases",
        "_retry_trackers",
        "_transcript_buffers",
    )

    def _cleanup_session_state(self, session_id: str) -> None:
        """Pop shared per-session and per-job tracking dicts.

        Subclasses should call ``super()._cleanup_session_state()`` in their
        own ``_cleanup_session`` after doing SDK-specific teardown.
        """
        self._paused_sessions.discard(session_id)
        job_id = self._session_to_job.pop(session_id, None)
        self._clients.pop(session_id, None)
        self._queues.pop(session_id, None)
        if job_id:
            for attr in self._JOB_TRACKING_DICTS:
                getattr(self, attr).pop(job_id, None)

    # ------------------------------------------------------------------
    # DB write pipeline
    # ------------------------------------------------------------------

    def _schedule_db_write(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule an async DB write with backpressure."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        # Prune completed tasks
        self._write_tasks = [t for t in self._write_tasks if not t.done()]

        # Drop writes when too many are in-flight to prevent pool exhaustion
        if len(self._write_tasks) >= self._MAX_PENDING_WRITES:
            log.debug("telemetry_write_dropped_backpressure", pending=len(self._write_tasks))
            return

        task = loop.create_task(coro)
        self._write_tasks.append(task)

    async def _db_write(self, fn_name: str, **kwargs: Any) -> None:
        """Execute a telemetry DB write in its own session."""
        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                from backend.persistence.file_access_repo import FileAccessRepository
                from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                summary = TelemetrySummaryRepository(session)
                dispatch = {
                    "increment": summary.increment,
                    "insert_span": TelemetrySpansRepository(session).insert,
                    "set_model": summary.set_model,
                    "set_context": summary.set_context,
                    "set_quota": summary.set_quota,
                    "record_file_access": FileAccessRepository(session).record,
                }
                handler = dispatch.get(fn_name)
                if handler is not None:
                    await handler(**kwargs)
                await session.commit()
        except (DBAPIError, OSError):
            log.warning("telemetry_db_write_failed", fn=fn_name, exc_info=True)
            return

        # Broadcast a debounced telemetry_updated SSE for summary changes
        if fn_name != "insert_span":
            job_id = kwargs.get("job_id")
            if job_id:
                await self._maybe_broadcast_telemetry(job_id)

    async def _maybe_broadcast_telemetry(self, job_id: str) -> None:
        """Publish telemetry_updated if debounce interval has elapsed."""
        from backend.models.events import DomainEvent, DomainEventKind

        if self._event_bus is None:
            return
        now = time.monotonic()
        last = self._last_telemetry_broadcast.get(job_id, 0.0)
        if now - last < self._TELEMETRY_BROADCAST_INTERVAL:
            return
        self._last_telemetry_broadcast[job_id] = now
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=datetime.now(UTC),
                kind=DomainEventKind.telemetry_updated,
                payload={"job_id": job_id},
            )
        )

    # ------------------------------------------------------------------
    # Model verification
    # ------------------------------------------------------------------

    def _verify_and_set_model(
        self,
        session_id: str,
        job_id: str,
        actual_model: str,
        requested_model: str,
    ) -> None:
        """First-call model verification: log mismatch, emit event, persist.

        Safe to call multiple times — only acts on the first invocation
        per job (guards on ``_job_main_models``).
        """
        if not actual_model or job_id in self._job_main_models:
            return
        self._job_main_models[job_id] = actual_model
        self._schedule_db_write(self._db_write("set_model", job_id=job_id, model=actual_model))

        if requested_model and normalize_model_name(actual_model) != normalize_model_name(requested_model):
            log.error(
                "model_mismatch",
                requested=requested_model,
                actual=actual_model,
                job_id=job_id,
            )
            self._enqueue(
                session_id,
                SessionEvent(
                    kind=SessionEventKind.model_downgraded,
                    payload={
                        "requested_model": requested_model,
                        "actual_model": actual_model,
                    },
                ),
            )
        else:
            log.info("model_confirmed", model=actual_model, job_id=job_id)

    # ------------------------------------------------------------------
    # Telemetry recording
    # ------------------------------------------------------------------

    def _record_llm_telemetry(
        self,
        job_id: str,
        sdk_name: str,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_write: int,
        cost_usd: float,
        duration_ms: float,
        is_subagent: bool = False,
        num_turns: int = 1,
    ) -> None:
        """Record OTEL counters + DB summary increment for an LLM call."""
        from backend.services import telemetry as tel

        attrs: dict[str, Any] = {"job_id": job_id, "sdk": sdk_name, "model": model}
        tel.tokens_input.add(input_tokens, attrs)
        tel.tokens_output.add(output_tokens, attrs)
        tel.tokens_cache_read.add(cache_read, attrs)
        tel.tokens_cache_write.add(cache_write, attrs)
        tel.cost_usd.add(cost_usd, attrs)
        tel.llm_duration.record(duration_ms, {**attrs, "is_subagent": is_subagent})

        self._schedule_db_write(
            self._db_write(
                "increment",
                job_id=job_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                total_cost_usd=cost_usd,
                total_llm_duration_ms=int(duration_ms),
                llm_call_count=num_turns,
                total_turns=num_turns,
                subagent_cost_usd=cost_usd if is_subagent else 0.0,
            )
        )

    def _record_llm_span(
        self,
        job_id: str,
        model: str,
        *,
        duration_ms: float,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_write: int,
        cost_usd: float,
        is_subagent: bool = False,
        num_turns: int = 1,
        turn_id: str | None = None,
    ) -> None:
        """Insert an LLM span into the telemetry_spans table."""
        turn_num = self._turn_counters.get(job_id, 0)
        current_phase = self._current_phases.get(job_id, "agent_reasoning")
        job_start = self._job_start_times.get(job_id, time.monotonic())
        offset = time.monotonic() - job_start

        self._schedule_db_write(
            self._db_write(
                "insert_span",
                job_id=job_id,
                span_type="llm",
                name=model or "unknown",
                started_at=round(offset, 2),
                duration_ms=float(duration_ms),
                attrs={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": cache_read,
                    "cache_write_tokens": cache_write,
                    "cost": cost_usd,
                    "is_subagent": is_subagent,
                    "num_turns": num_turns,
                },
                turn_number=turn_num,
                execution_phase=current_phase,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=cost_usd,
                turn_id=turn_id,
            )
        )

    def _record_tool_telemetry(
        self,
        session_id: str,
        job_id: str,
        sdk_name: str,
        *,
        tool_name: str,
        tool_args_str: str | None,
        success: bool,
        duration_ms: float,
        result_text: str,
        turn_id: str | None = None,
    ) -> None:
        """Record OTEL + DB metrics for a tool execution.

        Handles: tool_duration counter, tool classification, retry detection,
        file access tracking, file_changed events, summary increment, and
        span insertion.
        """
        from backend.services import telemetry as tel
        from backend.services.tool_classifier import classify_tool, extract_file_paths, extract_tool_target

        attrs: dict[str, Any] = {
            "job_id": job_id,
            "sdk": sdk_name,
            "tool_name": tool_name,
            "success": bool(success),
        }
        tel.tool_duration.record(duration_ms, attrs)

        category = classify_tool(tool_name)
        target = extract_tool_target(tool_name, tool_args_str)
        current_phase = self._current_phases.get(job_id, "agent_reasoning")
        turn_num = self._turn_counters.get(job_id, 0)

        # Retry detection
        from backend.services.retry_tracker import RetryTracker

        if job_id not in self._retry_trackers:
            self._retry_trackers[job_id] = RetryTracker()
        retry_result = self._retry_trackers[job_id].record(tool_name, target, 0, success)

        # Result size
        result_size = len(result_text.encode("utf-8", errors="replace")) if result_text else None

        # File access tracking
        file_rw_increment: dict[str, int] = {"file_read_count": 0, "file_write_count": 0}
        if category in ("file_read", "file_write"):
            paths = extract_file_paths(tool_name, tool_args_str)
            access_type = "write" if category == "file_write" else "read"
            if access_type == "read":
                file_rw_increment["file_read_count"] = 1
            else:
                file_rw_increment["file_write_count"] = 1
            for fpath in paths:
                self._schedule_db_write(
                    self._db_write(
                        "record_file_access",
                        job_id=job_id,
                        file_path=fpath,
                        access_type=access_type,
                        turn_number=turn_num,
                    )
                )

            # Emit file_changed events for successful writes
            if category == "file_write" and success:
                for fpath in paths:
                    self._enqueue(
                        session_id,
                        SessionEvent(
                            kind=SessionEventKind.file_changed,
                            payload={"path": fpath},
                        ),
                    )

        # Summary increment
        self._schedule_db_write(
            self._db_write(
                "increment",
                job_id=job_id,
                tool_call_count=1,
                tool_failure_count=0 if success else 1,
                total_tool_duration_ms=int(duration_ms),
                retry_count=1 if retry_result.is_retry else 0,
                **file_rw_increment,
            )
        )

        # Span detail
        job_start = self._job_start_times.get(job_id, time.monotonic())
        offset = time.monotonic() - job_start

        # Capture preceding context for mutative actions
        preceding_context = self._maybe_capture_context(job_id, category, tool_args_str)

        self._schedule_db_write(
            self._db_write(
                "insert_span",
                job_id=job_id,
                span_type="tool",
                name=tool_name,
                started_at=round(offset, 2),
                duration_ms=duration_ms,
                attrs={
                    "success": success,
                    **({"error_snippet": result_text[:2000]} if not success and result_text else {}),
                },
                tool_category=category,
                tool_target=target,
                turn_number=turn_num,
                execution_phase=current_phase,
                is_retry=retry_result.is_retry,
                retries_span_id=retry_result.prior_failure_span_id,
                tool_args_json=tool_args_str,
                result_size_bytes=result_size,
                turn_id=turn_id,
                preceding_context=preceding_context,
            )
        )

    # ------------------------------------------------------------------
    # Permission evaluation (SDK-agnostic core)
    # ------------------------------------------------------------------

    async def _evaluate_permission(
        self,
        session_id: str,
        job_id: str | None,
        mode: PermissionMode,
        *,
        tool_kind: str,
        tool_name: str = "",
        tool_input: dict[str, Any] | None = None,
        workspace_path: str = "",
        full_command_text: str | None = None,
        file_name: str | None = None,
        path: str | None = None,
        read_only: bool | None = None,
        possible_paths: list[str] | None = None,
    ) -> PermissionDecision:
        """Evaluate a tool permission request against CodePlane's policy.

        Returns ``PermissionDecision.allow`` or ``PermissionDecision.deny``.
        When the policy says "ask", this method routes to the operator and
        blocks until a resolution is received.
        """
        # Paused — immediately deny
        if session_id in self._paused_sessions:
            return PermissionDecision.deny

        # Hard block: git reset --hard
        shell_cmd = full_command_text or ""
        if not shell_cmd and tool_input:
            shell_cmd = str(tool_input.get("command", "")) if tool_kind == "shell" or tool_name == "Bash" else ""
        if shell_cmd and is_git_reset_hard(shell_cmd):
            resolution = await self._hard_block_approval(
                session_id,
                job_id,
                shell_cmd,
                tool_input,
            )
            return PermissionDecision.allow if resolution == ApprovalResolution.approved else PermissionDecision.deny

        # Trust bypass
        if self._approval_service is not None and job_id and self._approval_service.is_trusted(job_id):
            return PermissionDecision.allow

        # Policy evaluation
        decision = evaluate(
            mode=mode,
            kind=tool_kind,
            workspace_path=workspace_path,
            full_command_text=full_command_text,
            file_name=file_name,
            path=path,
            read_only=read_only,
            possible_paths=possible_paths,
        )
        if decision == PolicyDecision.approve:
            return PermissionDecision.allow
        if decision == PolicyDecision.deny:
            return PermissionDecision.deny

        # ask → route to operator
        description = self._build_permission_description(
            tool_kind,
            tool_name,
            tool_input,
            full_command_text,
        )
        proposed = full_command_text or (json.dumps(tool_input, default=str)[:_TOOL_ACTION_MAX_CHARS] if tool_input else None)
        resolution = await self._route_to_operator(
            session_id,
            job_id,
            description,
            proposed_action=proposed,
        )
        return PermissionDecision.allow if resolution == ApprovalResolution.approved else PermissionDecision.deny

    async def _hard_block_approval(
        self,
        session_id: str,
        job_id: str | None,
        shell_cmd: str,
        tool_input: dict[str, Any] | None = None,
    ) -> ApprovalResolution:
        """Route a hard-blocked command to the operator."""
        if self._approval_service is None or job_id is None:
            log.error("git_reset_hard_blocked_no_infra", command=shell_cmd[:200])
            return ApprovalResolution.rejected

        description = (
            "⚠️ git reset --hard — this will discard ALL uncommitted changes and "
            f"move HEAD: {shell_cmd[:_TOOL_SUMMARY_MAX_CHARS]}"
        )
        proposed = json.dumps(tool_input, default=str)[:_TOOL_ACTION_MAX_CHARS] if tool_input else shell_cmd
        approval = await self._approval_service.create_request(
            job_id=job_id,
            description=description,
            proposed_action=proposed,
            requires_explicit_approval=True,
        )
        self._enqueue(
            session_id,
            SessionEvent(
                kind=SessionEventKind.approval_request,
                payload={
                    "description": description,
                    "proposed_action": proposed,
                    "approval_id": approval.id,
                    "requires_explicit_approval": True,
                },
            ),
        )
        log.warning(
            "git_reset_hard_awaiting_operator",
            approval_id=approval.id,
            job_id=job_id,
            command=shell_cmd[:200],
        )
        return await self._approval_service.wait_for_resolution(approval.id)

    async def _route_to_operator(
        self,
        session_id: str,
        job_id: str | None,
        description: str,
        proposed_action: str | None = None,
    ) -> ApprovalResolution:
        """Create an approval request, emit it, and block until resolved."""
        if self._approval_service is None or job_id is None:
            log.warning("permission_ask_no_infra")
            return ApprovalResolution.approved

        approval = await self._approval_service.create_request(
            job_id=job_id,
            description=description,
            proposed_action=proposed_action,
        )
        self._enqueue(
            session_id,
            SessionEvent(
                kind=SessionEventKind.approval_request,
                payload={
                    "description": description,
                    "proposed_action": proposed_action,
                    "approval_id": approval.id,
                },
            ),
        )
        log.info(
            "permission_awaiting_operator",
            approval_id=approval.id,
            description=description,
        )
        return await self._approval_service.wait_for_resolution(approval.id)

    @staticmethod
    def _build_permission_description(
        tool_kind: str,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        full_command_text: str | None,
    ) -> str:
        """Build a human-readable description for an approval request."""

        def _get(key: str, *fallbacks: str) -> str:
            if not tool_input:
                return ""
            for k in (key, *fallbacks):
                val = tool_input.get(k, "")
                if val:
                    return str(val)
            return ""

        # Dispatch table: (prefix, primary_field, fallback_field, truncate)
        _RULES: dict[str, tuple[str, str, str | None]] = {
            "shell": ("Run shell:", "command", None),
            "Bash": ("Run shell:", "command", None),
            "write": ("Write file:", "file_path", "path"),
            "Edit": ("Write file:", "file_path", "path"),
            "Write": ("Write file:", "file_path", "path"),
            "WebSearch": ("Web search:", "query", None),
            "url": ("Fetch URL:", "url", None),
            "WebFetch": ("Fetch URL:", "url", None),
            "Read": ("Read file:", "file_path", "path"),
        }

        rule = _RULES.get(tool_name) or _RULES.get(tool_kind)
        if rule:
            prefix, primary, fallback = rule
            if tool_kind == "shell" or tool_name == "Bash":
                val = full_command_text or _get(primary)
            elif fallback:
                val = _get(primary, fallback)
            else:
                val = _get(primary)
            return f"{prefix} {val[:_TOOL_SUMMARY_MAX_CHARS]}"

        # Generic
        if tool_name:
            summary = ""
            if tool_input:
                try:
                    summary = json.dumps(tool_input, default=str)[:_TOOL_SUMMARY_FALLBACK_CHARS]
                except (TypeError, ValueError):
                    summary = str(tool_input)[:_TOOL_SUMMARY_FALLBACK_CHARS]
            return f"{tool_name}: {summary}"
        return full_command_text or tool_kind
