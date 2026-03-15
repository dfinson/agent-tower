"""Agent adapter interface and implementations."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import structlog

from backend.models.domain import (
    PermissionMode,
    SessionConfig,
    SessionEvent,
    SessionEventKind,
)
from backend.services.permission_policy import PolicyDecision, evaluate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot.generated.session_events import SessionEvent as SdkSessionEvent
    from copilot.session import CopilotSession

    from backend.services.approval_service import ApprovalService
    from backend.services.event_bus import EventBus

log = structlog.get_logger()


class AgentAdapterInterface(ABC):
    """Wraps the agent runtime behind a generic interface."""

    @abstractmethod
    async def create_session(self, config: SessionConfig) -> str:
        """Create a session, return session_id."""

    @abstractmethod
    async def stream_events(self, session_id: str) -> AsyncIterator[SessionEvent]:
        """Stream events from a running session."""
        yield  # type: ignore[misc]

    @abstractmethod
    async def send_message(self, session_id: str, message: str) -> None:
        """Send a follow-up message into a running session."""

    @abstractmethod
    async def abort_session(self, session_id: str) -> None:
        """Abort the current message processing. Session remains valid."""


class CopilotAdapter(AgentAdapterInterface):
    """Wraps the Python Copilot SDK behind the adapter interface.

    Uses a callback-to-iterator bridge: SDK callbacks push SessionEvent
    items onto an asyncio.Queue; stream_events() yields from the queue.
    """

    def __init__(
        self,
        approval_service: ApprovalService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._queues: dict[str, asyncio.Queue[SessionEvent | None]] = {}
        self._sessions: dict[str, CopilotSession] = {}
        self._session_to_job: dict[str, str] = {}  # session_id → job_id for telemetry
        self._tool_start_times: dict[str, float] = {}  # tool_call_id → start monotonic
        self._approval_service = approval_service
        self._event_bus = event_bus

    def set_job_id(self, session_id: str, job_id: str) -> None:
        """Associate a session with a job for telemetry routing."""
        self._session_to_job[session_id] = job_id

    def _cleanup_session(self, session_id: str) -> None:
        """Remove session and queue references for a completed/aborted session."""
        self._sessions.pop(session_id, None)
        self._queues.pop(session_id, None)
        self._session_to_job.pop(session_id, None)

    async def create_session(self, config: SessionConfig) -> str:
        from copilot import CopilotClient, PermissionRequest, PermissionRequestResult

        client = CopilotClient()
        session_id = str(uuid.uuid4())
        queue: asyncio.Queue[SessionEvent | None] = asyncio.Queue()
        self._queues[session_id] = queue

        permission_mode = config.permission_mode
        workspace_path = config.workspace_path
        protected_paths = config.protected_paths
        approval_service = self._approval_service
        event_bus = self._event_bus

        # Permission handler — evaluates policy and either auto-approves
        # or blocks until the operator responds via the approval UI.
        async def _on_permission(request: PermissionRequest, invocation: dict[str, str]) -> PermissionRequestResult:
            request_kind = request.kind.value if request.kind else "unknown"
            description = f"{request.tool_name or request_kind}: {request.intention or request.subject or ''}"
            proposed_action = request.full_command_text

            # --- Permissive: approve everything ---
            if permission_mode == PermissionMode.permissive:
                log.debug("permission_auto_approved", mode="permissive", kind=request_kind)
                return PermissionRequestResult(kind="approved")

            # --- Supervised: ask for everything ---
            if permission_mode == PermissionMode.supervised:
                decision = PolicyDecision.ask
            else:
                # --- Auto: evaluate policy ---
                # Collect all candidate paths from the request
                candidate_paths: list[str] = []
                if request.file_name:
                    candidate_paths.append(request.file_name)
                if request.path:
                    candidate_paths.append(request.path)
                if request.possible_paths:
                    candidate_paths.extend(request.possible_paths)

                decision = evaluate(
                    kind=request_kind,
                    workspace_path=workspace_path,
                    protected_paths=protected_paths,
                    possible_paths=candidate_paths or None,
                    file_name=request.file_name,
                    path=request.path,
                    read_only=request.read_only,
                )

            if decision == PolicyDecision.approve:
                log.debug("permission_auto_approved", mode=str(permission_mode), kind=request_kind)
                return PermissionRequestResult(kind="approved")

            # --- Decision is "ask" — route to operator via approval system ---
            job_id = self._session_to_job.get(session_id)
            if approval_service is None or event_bus is None or job_id is None:
                # No approval infrastructure available — fall back to approve
                log.warning(
                    "permission_ask_no_infra",
                    kind=request_kind,
                    has_svc=approval_service is not None,
                    has_bus=event_bus is not None,
                    has_job=job_id is not None,
                )
                return PermissionRequestResult(kind="approved")

            # Persist the approval request and create a Future
            approval = await approval_service.create_request(
                job_id=job_id,
                description=description,
                proposed_action=proposed_action,
            )

            # Emit approval_request event on the queue so RuntimeService
            # can transition state and publish SSE to the frontend
            queue.put_nowait(
                SessionEvent(
                    kind=SessionEventKind.approval_request,
                    payload={
                        "description": description,
                        "proposed_action": proposed_action,
                        "approval_id": approval.id,
                    },
                )
            )

            log.info(
                "permission_awaiting_operator",
                approval_id=approval.id,
                kind=request_kind,
                description=description,
            )

            # Block the SDK until the operator responds
            resolution = await approval_service.wait_for_resolution(approval.id)

            if resolution == "approved":
                return PermissionRequestResult(kind="approved")
            return PermissionRequestResult(kind="denied-interactively-by-user")

        session = await client.create_session(
            {
                "working_directory": config.workspace_path,
                "on_permission_request": _on_permission,
            }
        )
        self._sessions[session_id] = session

        # Register SDK callback that bridges into the async queue
        # and extracts telemetry from Copilot-specific event types.
        def _on_event(sdk_event: SdkSessionEvent) -> None:
            kind_str = sdk_event.type.value if sdk_event.type else "log"
            payload = sdk_event.data.to_dict() if sdk_event.data else {}
            data = sdk_event.data

            # --- Copilot SDK → standard telemetry contract ---
            # Compare against event type string values to avoid importing
            # SessionEventType (which mypy flags as not re-exported).
            job_id = self._session_to_job.get(session_id)
            if job_id and data:
                from backend.services.telemetry import collector as tel

                if kind_str == "assistant_usage":
                    tel.record_llm_usage(
                        job_id,
                        model=data.model or "",
                        input_tokens=int(data.input_tokens or 0),
                        output_tokens=int(data.output_tokens or 0),
                        cache_read_tokens=int(data.cache_read_tokens or 0),
                        cache_write_tokens=int(data.cache_write_tokens or 0),
                        cost=float(data.cost or 0),
                        duration_ms=float(data.duration or 0),
                    )
                elif kind_str == "tool_execution_start":
                    tool_id = data.tool_call_id or ""
                    import time as _time

                    self._tool_start_times[tool_id] = _time.monotonic()
                elif kind_str == "tool_execution_complete":
                    tool_id = data.tool_call_id or ""
                    import time as _time

                    start = self._tool_start_times.pop(tool_id, _time.monotonic())
                    dur = (_time.monotonic() - start) * 1000
                    tel.record_tool_call(
                        job_id,
                        tool_name=data.tool_name or data.mcp_tool_name or "unknown",
                        duration_ms=dur,
                        success=bool(data.success) if data.success is not None else True,
                    )
                elif kind_str == "session_context_changed":
                    tel.record_context_change(
                        job_id,
                        current_tokens=int(data.current_tokens or 0),
                    )
                elif kind_str == "session_compaction_complete":
                    tel.record_compaction(
                        job_id,
                        pre_tokens=int(data.pre_compaction_tokens or 0),
                        post_tokens=int(data.post_compaction_tokens or 0),
                    )
                    if data.post_compaction_tokens:
                        tel.record_context_change(
                            job_id,
                            current_tokens=int(data.post_compaction_tokens),
                        )
                elif kind_str == "session_truncation":
                    if data.token_limit:
                        tel.record_context_change(
                            job_id,
                            window_size=int(data.token_limit),
                        )
                elif kind_str == "session_model_change":
                    if data.new_model:
                        t = tel.get(job_id)
                        if t:
                            t.model = data.new_model
                elif kind_str == "assistant_message":
                    tel.record_message(job_id, role="agent")
                elif kind_str == "user_message":
                    tel.record_message(job_id, role="operator")

            # --- Bridge to SessionEvent queue ---
            try:
                kind = SessionEventKind(kind_str)
            except ValueError:
                kind = SessionEventKind.log
                payload = {"level": "debug", "message": f"Unknown SDK event: {kind_str}"}
            try:
                queue.put_nowait(SessionEvent(kind=kind, payload=payload if isinstance(payload, dict) else {}))
            except Exception:
                log.warning("copilot_queue_put_failed", session_id=session_id)
            if kind == SessionEventKind.done or kind == SessionEventKind.error:
                with contextlib.suppress(Exception):
                    queue.put_nowait(None)  # sentinel

        session.on(_on_event)
        # Send initial prompt
        try:
            await session.send({"prompt": config.prompt, "mode": "immediate", "attachments": []})
        except Exception:
            self._cleanup_session(session_id)
            raise
        log.info("copilot_session_created", session_id=session_id)
        return session_id

    async def stream_events(self, session_id: str) -> AsyncIterator[SessionEvent]:
        queue = self._queues.get(session_id)
        if queue is None:
            log.error("copilot_stream_no_queue", session_id=session_id)
            yield SessionEvent(kind=SessionEventKind.error, payload={"message": "No queue for session"})
            return
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300)
                except TimeoutError:
                    yield SessionEvent(
                        kind=SessionEventKind.error,
                        payload={"message": "Session timed out waiting for events"},
                    )
                    return
                if event is None:
                    return
                yield event
        finally:
            self._cleanup_session(session_id)

    async def send_message(self, session_id: str, message: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            log.warning("copilot_send_no_session", session_id=session_id)
            return
        await session.send({"prompt": message, "mode": "immediate", "attachments": []})

    async def abort_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        try:
            await session.abort()
        except Exception:
            log.warning("copilot_abort_failed", session_id=session_id, exc_info=True)
        finally:
            self._cleanup_session(session_id)
