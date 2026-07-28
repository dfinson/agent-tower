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
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

import structlog
from sqlalchemy.exc import DBAPIError

from backend.models.domain import (
    ApprovalResolution,
    SessionEvent,
    SessionEventKind,
)
from backend.services.adapters.agent_adapter import AgentAdapterInterface, normalize_model_name
from backend.services.auth.permission_policy import (
    PermissionRequest,
    is_git_reset_hard,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Coroutine

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.models.api_schemas import ExecutionPhase
    from backend.services.action_policy.classifier import CostContext
    from backend.services.events.event_bus import EventBus
    from backend.services.job.approval_service import ApprovalService

log = structlog.get_logger()


class _NoSessionFactoryError(Exception):
    """Sentinel raised when no DB session factory is configured."""


# ---------------------------------------------------------------------------
# Shared adapter constants
# ---------------------------------------------------------------------------

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
        self._session_kinds: dict[str, str] = {}  # session_id → session_kind for telemetry
        self._paused_sessions: set[str] = set()
        self._approval_service = approval_service
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._policy_router: dict[str, Any] = {}  # job_id → PolicyRouter
        self._repo_policies: dict[str, Any] = {}  # job_id → RepoPolicy
        self._worktree_paths: dict[str, str] = {}  # job_id → cwd
        self._job_start_times: dict[str, float] = {}
        self._job_main_models: dict[str, str] = {}
        self._last_telemetry_broadcast: dict[str, float] = {}
        self._current_phases: dict[str, str] = {}
        self._write_tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _enqueue(self, session_id: str, event: SessionEvent) -> None:
        q = self._queues.get(session_id)
        if q is not None:
            q.put_nowait(event)

    # ------------------------------------------------------------------
    # Session state
    # ------------------------------------------------------------------

    def set_job_id(self, session_id: str, job_id: str) -> None:
        """Associate a session with a job for telemetry routing."""
        self._session_to_job[session_id] = job_id
        self._job_start_times.setdefault(job_id, time.monotonic())

    def set_session_kind(self, session_id: str, kind: str) -> None:
        """Tag a session with its kind for telemetry dimension tracking."""
        self._session_kinds[session_id] = kind

    def get_session_kind(self, session_id: str) -> str:
        """Return the session_kind for a session (defaults to 'job')."""
        return self._session_kinds.get(session_id, "job")

    def set_execution_phase(self, job_id: str, phase: ExecutionPhase) -> None:
        """Update the current execution phase for cost analytics span tagging."""
        self._current_phases[job_id] = phase

    def pause_tools(self, session_id: str) -> None:
        self._paused_sessions.add(session_id)

    def resume_tools(self, session_id: str) -> None:
        self._paused_sessions.discard(session_id)

    # Per-job tracking dicts cleaned up together in _cleanup_session_state.
    # NOTE: _policy_router, _repo_policies, _worktree_paths are intentionally
    # excluded — they are per-job (not per-session) and must survive across
    # retries / follow-up sessions.  They are cleaned up by
    # RuntimeService._cleanup_job_state at end-of-job.
    _JOB_TRACKING_DICTS: ClassVar[tuple[str, ...]] = (
        "_job_start_times",
        "_job_main_models",
        "_last_telemetry_broadcast",
        "_current_phases",
    )

    def _cleanup_session_state(self, session_id: str) -> None:
        """Pop shared per-session and per-job tracking dicts.

        Subclasses should call ``super()._cleanup_session_state()`` in their
        own ``_cleanup_session`` after doing SDK-specific teardown.
        """
        self._paused_sessions.discard(session_id)
        self._session_kinds.pop(session_id, None)
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
            coro.close()
            return

        # Prune completed tasks
        self._write_tasks = [t for t in self._write_tasks if not t.done()]

        # Drop writes when too many are in-flight to prevent pool exhaustion
        if len(self._write_tasks) >= self._MAX_PENDING_WRITES:
            log.debug("telemetry_write_dropped_backpressure", pending=len(self._write_tasks))
            coro.close()
            return

        task = loop.create_task(coro)
        self._write_tasks.append(task)

    @asynccontextmanager
    async def _db_session(self) -> AsyncIterator[AsyncSession]:
        """Yield a scoped DB session with commit and error handling."""
        if self._session_factory is None:
            raise _NoSessionFactoryError
        from backend.persistence.database import serialized_write

        async with serialized_write(self._session_factory) as session:
            yield session

    async def _db_write_set_model(self, *, job_id: str, model: str) -> None:
        """Record the main model for a job."""
        try:
            async with self._db_session() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                await TelemetrySummaryRepository(session).set_model(job_id=job_id, model=model)
        except (_NoSessionFactoryError, DBAPIError, OSError):
            log.warning("telemetry_db_write_failed", fn="set_model", exc_info=True)
            return
        await self._maybe_broadcast_telemetry(job_id)

    async def _db_write_set_quota(self, *, job_id: str, quota_remaining: str) -> None:
        """Record remaining quota."""
        try:
            async with self._db_session() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                await TelemetrySummaryRepository(session).set_quota(job_id=job_id, quota_json=quota_remaining)
        except (_NoSessionFactoryError, DBAPIError, OSError):
            log.warning("telemetry_db_write_failed", fn="set_quota", exc_info=True)
            return
        await self._maybe_broadcast_telemetry(job_id)

    async def _maybe_broadcast_telemetry(
        self,
        job_id: str,
        *,
        totals: dict[str, float | int] | None = None,
    ) -> None:
        """Publish telemetry_updated if debounce interval has elapsed."""
        from backend.models.events import EventKind, new_event

        if self._event_bus is None:
            return
        now = time.monotonic()
        last = self._last_telemetry_broadcast.get(job_id, 0.0)
        if now - last < self._TELEMETRY_BROADCAST_INTERVAL:
            return
        self._last_telemetry_broadcast[job_id] = now
        payload: dict[str, Any] = {"job_id": job_id}
        if totals:
            payload["total_cost_usd"] = totals.get("total_cost_usd", 0.0)
            payload["total_tokens"] = totals.get("total_tokens", 0)
            payload["input_tokens"] = totals.get("input_tokens", 0)
            payload["output_tokens"] = totals.get("output_tokens", 0)
        await self._event_bus.publish(
            new_event(
                session_id=job_id, timestamp=datetime.now(UTC), kind=EventKind.telemetry_updated, payload=payload
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
        self._schedule_db_write(self._db_write_set_model(job_id=job_id, model=actual_model))

        if (
            requested_model
            and requested_model != "auto"
            and normalize_model_name(actual_model) != normalize_model_name(requested_model)
        ):
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
    # Shared tool event helpers (used by Claude + Copilot adapters)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_result_text(content: object) -> str:
        """Convert SDK result content (str, list of blocks, or object) to plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                parts.append(text if text is not None else str(item))
            return "\n".join(parts)
        return str(content) if content else ""

    # ------------------------------------------------------------------
    # Action policy integration
    # ------------------------------------------------------------------

    def set_policy_router(self, router: Any, policy: Any, job_id: str, cwd: str) -> None:
        """Configure the action policy router for a job.

        When set, ``_evaluate_permission`` routes through the classifier/router
        before falling back to the legacy ``permission_policy.evaluate()`` path.
        """
        self._policy_router[job_id] = router
        self._repo_policies[job_id] = policy
        self._worktree_paths[job_id] = cwd

    def update_repo_policy(self, job_id: str, policy: Any) -> None:
        """Hot-swap the RepoPolicy for a running job (mid-job policy reload)."""
        if job_id in self._repo_policies:
            self._repo_policies[job_id] = policy

    def cleanup_job_policy(self, job_id: str) -> None:
        """Remove per-job policy state.  Called at end-of-job by RuntimeService."""
        self._policy_router.pop(job_id, None)
        self._repo_policies.pop(job_id, None)
        self._worktree_paths.pop(job_id, None)

    # ------------------------------------------------------------------
    # Permission evaluation (SDK-agnostic core)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_shell_command(
        tool_kind: str,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        full_command_text: str | None,
    ) -> str:
        """Extract the shell command string from a tool permission request."""
        if full_command_text:
            return full_command_text
        if tool_input and (tool_kind == "shell" or tool_name == "Bash"):
            return str(tool_input.get("command", ""))
        return ""

    async def _evaluate_permission(
        self,
        session_id: str,
        job_id: str | None,
        request: PermissionRequest,
        *,
        tool_name: str = "",
        tool_input: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        """Evaluate a tool permission request against CodePlane's policy.

        Returns ``PermissionDecision.allow`` or ``PermissionDecision.deny``.
        All decisions are routed through the action policy router.  The router
        handles observe (auto-approve), checkpoint (savepoint + approve), and
        gate (route to operator) tiers.
        """
        # Paused — immediately deny
        if session_id in self._paused_sessions:
            return PermissionDecision.deny

        # Hard block: git reset --hard
        shell_cmd = self._resolve_shell_command(
            request.kind,
            tool_name,
            tool_input,
            request.full_command_text,
        )
        if shell_cmd and is_git_reset_hard(shell_cmd):
            resolution = await self._hard_block_approval(
                session_id,
                job_id,
                shell_cmd,
                tool_input,
            )
            return PermissionDecision.allow if resolution == ApprovalResolution.approved else PermissionDecision.deny

        # --- Action policy router ---
        if job_id and job_id in self._policy_router:
            return await self._evaluate_with_policy_router(
                session_id,
                job_id,
                request,
                tool_name=tool_name,
                tool_input=tool_input,
            )

        log.error(
            "no_policy_router_for_job",
            job_id=job_id,
            session_id=session_id,
            tool_name=tool_name,
        )
        return PermissionDecision.deny

    async def _evaluate_with_policy_router(
        self,
        session_id: str,
        job_id: str,
        request: PermissionRequest,
        *,
        tool_name: str = "",
        tool_input: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        """Route a permission request through the action policy classifier/router."""
        from backend.services.action_policy.classifier import Action, ActionKind

        # Map SDK permission request kind to Action
        shell_cmd = self._resolve_shell_command(
            request.kind,
            tool_name,
            tool_input,
            request.full_command_text,
        )
        kind_map = {
            "read": ActionKind.sdk_tool,
            "write": ActionKind.file,
            "shell": ActionKind.shell,
            "mcp": ActionKind.mcp_tool,
            "url": ActionKind.sdk_tool,
            "memory": ActionKind.sdk_tool,
            "custom-tool": ActionKind.sdk_tool,
        }
        action = Action(
            kind=kind_map.get(request.kind, ActionKind.sdk_tool),
            path=request.file_name or request.path,
            command=shell_cmd or None,
            tool_name=tool_name or request.kind,
            mcp_server=None,  # MCP tool metadata not in PermissionRequest
            mcp_tool=tool_name if request.kind == "mcp" else None,
            mcp_read_only=request.read_only or False,
            job_id=job_id,
            workspace_path=request.workspace_path,
        )

        policy = self._repo_policies[job_id]
        cwd = self._worktree_paths.get(job_id)
        router = self._policy_router[job_id]

        # Fetch cost context for cost rule evaluation
        cost_ctx = None
        if policy.cost_rules:
            cost_ctx = await self._get_cost_context(job_id)

        decision = await router.route(action, policy, cwd=cwd, cost=cost_ctx)

        # Emit action_classified event for timeline tier indicators
        tier_str = decision.tier.value if decision.tier else None
        if tier_str and self._event_bus is not None:
            from backend.models.events import EventKind, new_event

            cls = decision.classification
            await self._event_bus.publish(
                new_event(
                    session_id=job_id,
                    timestamp=datetime.now(UTC),
                    kind=EventKind.action_classified,
                    payload={
                        "tier": tier_str,
                        "tool_name": tool_name or request.kind,
                        "path": request.file_name or request.path,
                        "reversible": cls.reversible if cls else False,
                        "contained": cls.contained if cls else True,
                        "checkpoint_ref": decision.checkpoint_ref,
                    },
                )
            )

        if decision.proceed:
            return PermissionDecision.allow
        return PermissionDecision.deny

    async def _get_cost_context(self, job_id: str) -> CostContext | None:
        """Fetch current spend for a job to feed into cost rule evaluation."""
        from backend.services.action_policy.classifier import CostContext

        try:
            async with self._db_session() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                summary = await TelemetrySummaryRepository(session).get(job_id)
                if summary and summary["total_cost_usd"] is not None:
                    return CostContext(job_spend_usd=summary["total_cost_usd"])
        except (_NoSessionFactoryError, DBAPIError, OSError):
            log.warning("cost_context_fetch_failed", job_id=job_id, exc_info=True)
        return None

    async def _hard_block_approval(
        self,
        session_id: str,
        job_id: str | None,
        shell_cmd: str,
        tool_input: dict[str, Any] | None = None,
    ) -> ApprovalResolution:
        """Route a hard-blocked command to the operator."""
        if self._approval_service is None or job_id is None:
            log.error("git_reset_hard_blocked_no_infra", command=shell_cmd)
            return ApprovalResolution.rejected

        description = f"⚠️ git reset --hard — this will discard ALL uncommitted changes and move HEAD: {shell_cmd}"
        proposed = json.dumps(tool_input, default=str) if tool_input else shell_cmd
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
            command=shell_cmd,
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
        _RULES: dict[str, tuple[str, str, str | None]] = {  # noqa: N806
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
            return f"{prefix} {val}"

        # Generic
        if tool_name:
            summary = ""
            if tool_input:
                try:
                    summary = json.dumps(tool_input, default=str)
                except (TypeError, ValueError):
                    summary = str(tool_input)
            return f"{tool_name}: {summary}"
        return full_command_text or tool_kind
