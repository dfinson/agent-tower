"""Claude Agent SDK adapter — bridges the Claude Agent SDK into CodePlane.

Uses ClaudeSDKClient for multi-turn session management. The SDK's async
message iterator is consumed in a background task that pushes SessionEvent
items onto an asyncio.Queue; stream_events() yields from the queue.

Permission handling uses the ``can_use_tool`` callback to route tool
approval requests through CodePlane's approval system.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import tempfile
import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.domain import (
    PermissionMode,
    SessionConfig,
    SessionEvent,
    SessionEventKind,
)
from backend.services.agent_adapter import CODEPLANE_SYSTEM_PROMPT, CompletionResult
from backend.services.base_adapter import BaseAgentAdapter, PermissionDecision

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from claude_code_sdk import ClaudeSDKClient

    from backend.services.approval_service import ApprovalService
    from backend.services.event_bus import EventBus

log = structlog.get_logger()

# Claude SDK tool names that are internal / should not appear in transcript
_HIDDEN_TOOLS: frozenset[str] = frozenset()

# Map CodePlane permission modes to Claude SDK permission modes
_PERMISSION_MODE_MAP: dict[PermissionMode, str] = {
    PermissionMode.full_auto: "bypassPermissions",
    PermissionMode.observe_only: "plan",
    PermissionMode.review_and_approve: "default",
}


def _kill_sdk_subprocess(client: object | None) -> None:
    """Terminate the SDK's CLI subprocess using raw OS signals.

    This MUST be used instead of ``client.disconnect()`` or
    ``transport.close()`` because both invoke anyio methods whose
    cancel-scope teardown injects ``CancelledError`` into every
    SQLAlchemy connection in the process via the greenlet adapter.

    Pure OS calls (``os.kill`` / ``os.waitpid``) bypass anyio entirely
    and cannot contaminate other asyncio tasks.
    """
    if client is None:
        return
    transport = getattr(client, "_transport", None)
    if transport is None:
        return
    process = getattr(transport, "_process", None)
    if process is None:
        return
    # anyio Process wraps an asyncio.subprocess.Process in _process
    inner = getattr(process, "_process", None)
    pid: int | None = None
    if inner is not None:
        pid = getattr(inner, "pid", None)
    if pid is None:
        pid = getattr(process, "pid", None)
    if pid is None:
        return
    with contextlib.suppress(ProcessLookupError, OSError):
        os.kill(pid, signal.SIGTERM)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    # Null out SDK internal references so the garbage collector doesn't
    # try to clean them up through anyio (which triggers the connection
    # pool contamination on __del__).
    with contextlib.suppress(Exception):
        transport._process = None  # private access needed for cleanup
        transport._stdout_stream = None
        transport._stdin_stream = None
        transport._ready = False
    with contextlib.suppress(Exception):
        query = getattr(client, "_query", None)
        if query is not None:
            query._tg = None  # prevent cancel-scope teardown in GC
            client._query = None  # type: ignore[attr-defined]
        client._transport = None  # type: ignore[attr-defined]


class ClaudeAdapter(BaseAgentAdapter):
    """Wraps the Claude Agent SDK (Python) behind the adapter interface.

    Each session is backed by a ``ClaudeSDKClient`` instance that maintains
    conversation context.  A background asyncio task consumes the SDK's
    async message iterator and pushes translated ``SessionEvent`` objects
    onto a queue that ``stream_events()`` yields from.
    """

    def __init__(
        self,
        approval_service: ApprovalService | None = None,
        event_bus: EventBus | None = None,
        session_factory: Any | None = None,
    ) -> None:
        super().__init__(
            approval_service=approval_service,
            event_bus=event_bus,
            session_factory=session_factory,
        )
        self._consumer_tasks: dict[str, asyncio.Task[None]] = {}
        self._current_turn_id: str = ""
        self._requested_models: dict[str, str] = {}
        self._model_verified: dict[str, bool] = {}
        # Stderr capture files for debugging failed sessions
        self._stderr_files: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup_session(self, session_id: str) -> None:
        task = self._consumer_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        stderr_path = self._stderr_files.pop(session_id, None)
        if stderr_path:
            with contextlib.suppress(OSError):
                os.unlink(stderr_path)
        # Claude-specific model tracking
        job_id = self._session_to_job.get(session_id)
        if job_id:
            self._requested_models.pop(job_id, None)
            self._model_verified.pop(job_id, None)
        super()._cleanup_session_state(session_id)

    def set_execution_phase(self, job_id: str, phase: str) -> None:
        """Update the current execution phase for cost analytics span tagging."""
        self._current_phases[job_id] = phase

    def _read_session_stderr(self, session_id: str) -> str:
        """Read captured stderr from the Claude subprocess (last 4 KB)."""
        path = self._stderr_files.get(session_id)
        if not path:
            return ""
        try:
            with open(path) as f:
                return f.read()[-4096:]
        except OSError:
            return ""

    @staticmethod
    async def _disconnect_client(client: ClaudeSDKClient) -> None:
        """Disconnect a ClaudeSDKClient, terminating its backing subprocess."""
        try:
            await asyncio.wait_for(client.disconnect(), timeout=10)
        except (Exception, asyncio.CancelledError):
            log.warning("claude_client_disconnect_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Permission callback builder
    # ------------------------------------------------------------------

    def _build_can_use_tool(self, config: SessionConfig, session_id: str) -> Any:  # noqa: ANN401
        """Build the ``can_use_tool`` callback for the Claude SDK.

        Wraps the base adapter's ``_evaluate_permission`` to return SDK-
        specific PermissionResultAllow / PermissionResultDeny objects.
        """
        from claude_code_sdk import PermissionResultAllow, PermissionResultDeny

        # Map Claude tool names to permission_policy kinds
        _CLAUDE_TOOL_KIND: dict[str, str] = {
            "Bash": "shell",
            "Edit": "write",
            "Write": "write",
            "Read": "read",
            "MultiEdit": "write",
            "Glob": "read",
            "Grep": "read",
            "ToolSearch": "read",
            "WebFetch": "read",
            "WebSearch": "read",
        }

        async def _can_use_tool(
            tool_name: str,
            input_data: dict[str, Any],
            context: object,
        ) -> PermissionResultAllow | PermissionResultDeny:
            job_id = self._session_to_job.get(session_id)
            tool_kind = _CLAUDE_TOOL_KIND.get(tool_name, "custom-tool")
            full_cmd = str(input_data.get("command", "")) if tool_name == "Bash" else None
            file_name = str(input_data.get("file_path", "") or input_data.get("path", "")) or None
            decision = await self._evaluate_permission(
                session_id,
                job_id,
                config.permission_mode,
                tool_kind=tool_kind,
                tool_name=tool_name,
                tool_input=input_data,
                workspace_path=config.workspace_path,
                full_command_text=full_cmd,
                file_name=file_name,
                path=file_name,
            )
            if decision == PermissionDecision.allow:
                return PermissionResultAllow()
            return PermissionResultDeny(message="Blocked by CodePlane policy")

        return _can_use_tool

    @staticmethod
    async def _disconnect_client(client: ClaudeSDKClient) -> None:
        """Disconnect a ClaudeSDKClient, terminating its backing subprocess."""
        try:
            await asyncio.wait_for(client.disconnect(), timeout=10)
        except (Exception, asyncio.CancelledError):
            log.warning("claude_client_disconnect_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Message consumer — runs in a background task per session
    # ------------------------------------------------------------------

    async def _consume_messages(self, session_id: str, client: object) -> None:
        """Consume messages from the ClaudeSDKClient and translate to SessionEvents."""
        from claude_code_sdk import (
            AssistantMessage,
            ResultMessage,
            SystemMessage,
            UserMessage,
        )

        # Guard against SDK message-parse failures for unknown event types
        # (e.g. rate_limit_event in SDK ≤0.0.25).
        try:
            from claude_code_sdk._errors import MessageParseError
        except ImportError:
            MessageParseError = None  # type: ignore[assignment,misc]  # noqa: N806

        seq = [0]
        queue = self._queues.get(session_id)
        if queue is None:
            return

        done = False
        parse_error_retries = 0
        max_parse_error_retries = 5
        try:
            while not done:
                try:
                    async for message in client.receive_messages():  # type: ignore[attr-defined]
                        parse_error_retries = 0  # reset on successful message
                        if isinstance(message, SystemMessage):
                            self._enqueue_log(session_id, "Claude session initialized", "info", seq)

                        elif isinstance(message, AssistantMessage):
                            self._process_assistant_message(session_id, message, seq)

                        elif isinstance(message, UserMessage):
                            self._process_user_message(session_id, message, seq)

                        elif isinstance(message, ResultMessage):
                            self._process_result_message(session_id, message, seq)
                            done = True
                            break

                        # StreamEvent, TaskStartedMessage etc. are logged but not
                        # forwarded as transcript events (they are internal SDK bookkeeping).
                    else:
                        # Iterator exhausted without ResultMessage — session ended
                        done = True
                except Exception as exc:
                    # SDK ≤0.0.25 throws MessageParseError on unknown event types like
                    # rate_limit_event.  Log it and re-enter the message loop — the SDK
                    # subprocess is still alive.
                    if MessageParseError is not None and isinstance(exc, MessageParseError):
                        parse_error_retries += 1
                        log.warning(
                            "claude_unknown_message_type",
                            session_id=session_id,
                            error=str(exc),
                            retry=parse_error_retries,
                        )
                        if parse_error_retries >= max_parse_error_retries:
                            log.error(
                                "claude_parse_error_retry_limit",
                                session_id=session_id,
                                retries=parse_error_retries,
                            )
                            self._enqueue(
                                session_id,
                                SessionEvent(
                                    kind=SessionEventKind.error,
                                    payload={
                                        "message": (
                                            f"Claude SDK: too many consecutive parse errors ({parse_error_retries})"
                                        ),
                                    },
                                ),
                            )
                            done = True
                        else:
                            continue  # retry the receive_messages loop
                        continue

                    stderr_snippet = self._read_session_stderr(session_id)
                    log.error(
                        "claude_consumer_error",
                        session_id=session_id,
                        stderr_tail=stderr_snippet[:500] if stderr_snippet else "",
                        exc_info=True,
                    )
                    error_msg = f"Claude SDK session error: {exc}"
                    if stderr_snippet:
                        error_msg += f"\n{stderr_snippet}"
                    self._enqueue(
                        session_id,
                        SessionEvent(
                            kind=SessionEventKind.error,
                            payload={"message": error_msg},
                        ),
                    )
                    done = True
        except asyncio.CancelledError:
            log.info("claude_consumer_cancelled", session_id=session_id)
        finally:
            # Sentinel to signal end of stream
            if queue is not None:
                queue.put_nowait(None)

    def _process_user_message(
        self,
        session_id: str,
        message: object,
        seq: list[int],
    ) -> None:
        """Handle a UserMessage — extract ToolResultBlocks for telemetry/transcript."""
        from claude_code_sdk import ToolResultBlock

        content = getattr(message, "content", None)
        job_id = self._session_to_job.get(session_id)

        if isinstance(content, list):
            for block in content:
                if isinstance(block, ToolResultBlock):
                    self._process_tool_result_block(session_id, block, seq, job_id)
        elif isinstance(content, str) and content.strip() and job_id:
            # Human / operator follow-up message
            self._schedule_db_write(self._db_write("increment", job_id=job_id, operator_messages=1))

    def _process_assistant_message(
        self,
        session_id: str,
        message: object,
        seq: list[int],
    ) -> None:
        """Translate an AssistantMessage's content blocks into SessionEvents."""
        from claude_code_sdk import TextBlock, ToolResultBlock, ToolUseBlock

        content_blocks = getattr(message, "content", []) or []
        model = getattr(message, "model", "") or ""
        job_id = self._session_to_job.get(session_id)

        # Each AssistantMessage starts a new turn for grouping
        self._current_turn_id = str(uuid.uuid4())

        # Turn counting is deferred to ResultMessage.num_turns for accuracy
        # (the SDK streams many AssistantMessages per actual API turn).
        if job_id:
            turn_num = self._turn_counters.get(job_id, 0) + 1
            self._turn_counters[job_id] = turn_num

        # Lock in the main model from the first AssistantMessage that carries one
        if job_id and model:
            requested = self._requested_models.get(job_id, "")
            if not self._model_verified.get(job_id):
                self._model_verified[job_id] = True
                self._verify_and_set_model(session_id, job_id, model, requested)

        for block in content_blocks:
            if isinstance(block, TextBlock):
                text = block.text or ""
                if not text.strip():
                    continue
                if job_id:
                    self._schedule_db_write(
                        self._db_write(
                            "increment",
                            job_id=job_id,
                            agent_messages=1,
                        )
                    )
                self._enqueue(
                    session_id,
                    SessionEvent(
                        kind=SessionEventKind.transcript,
                        payload={
                            "role": "agent",
                            "content": text,
                            "turn_id": self._current_turn_id,
                        },
                    ),
                )

            elif isinstance(block, ToolUseBlock):
                self._process_tool_use_block(session_id, block, model, seq, job_id)

            elif isinstance(block, ToolResultBlock):
                self._process_tool_result_block(session_id, block, seq, job_id)

    def _process_tool_use_block(
        self,
        session_id: str,
        block: object,
        model: str,
        seq: list[int],
        job_id: str | None,
    ) -> None:
        """Handle a ToolUseBlock — emit tool_running transcript + log + record start time."""
        tool_name = getattr(block, "name", "") or "tool"
        tool_id = getattr(block, "id", "") or str(uuid.uuid4())
        tool_input = getattr(block, "input", None)

        # Serialize tool arguments
        args_str: str | None = None
        if isinstance(tool_input, dict):
            try:
                args_str = json.dumps(tool_input)
            except Exception:
                args_str = str(tool_input)

        # Record start time for duration calculation
        self._tool_start_times[tool_id] = time.monotonic()

        # Synthesize a turn_id for grouping (one per AssistantMessage stream)
        if not self._current_turn_id:
            self._current_turn_id = str(uuid.uuid4())
        turn_id = self._current_turn_id

        # Buffer for the completion event
        self._tool_call_buffer[tool_id] = {
            "tool_name": tool_name,
            "tool_args": args_str or "",
            "turn_id": turn_id,
        }

        if tool_name not in _HIDDEN_TOOLS:
            from backend.services.tool_formatters import classify_tool_visibility, format_tool_display, format_tool_display_full

            self._enqueue(
                session_id,
                SessionEvent(
                    kind=SessionEventKind.transcript,
                    payload={
                        "role": "tool_running",
                        "content": tool_name,
                        "tool_name": tool_name,
                        "tool_args": args_str,
                        "turn_id": turn_id,
                        "tool_display": format_tool_display(tool_name, args_str),
                        "tool_display_full": format_tool_display_full(tool_name, args_str),
                        "tool_visibility": classify_tool_visibility(tool_name, args_str),
                    },
                ),
            )
            self._enqueue_log(session_id, f"Tool started: {tool_name}", "debug", seq)

    def _process_tool_result_block(
        self,
        session_id: str,
        block: object,
        seq: list[int],
        job_id: str | None,
    ) -> None:
        """Handle a ToolResultBlock — emit transcript + telemetry."""
        tool_use_id = getattr(block, "tool_use_id", "") or ""
        content = getattr(block, "content", "")
        is_error = getattr(block, "is_error", False)

        # Resolve tool name + args from the buffer populated by _process_tool_use_block
        buffered = self._tool_call_buffer.pop(tool_use_id, {})
        tool_name = buffered.get("tool_name", "tool")
        tool_args_str = buffered.get("tool_args") or None
        turn_id = buffered.get("turn_id") or None

        # Calculate duration
        start = self._tool_start_times.pop(tool_use_id, time.monotonic())
        duration_ms = (time.monotonic() - start) * 1000

        # Extract text from content (can be str or list of content blocks)
        result_text = ""
        if isinstance(content, str):
            result_text = content
        elif isinstance(content, list):
            parts = []
            for part in content:
                if hasattr(part, "text"):
                    parts.append(part.text)
                else:
                    parts.append(str(part))
            result_text = "\n".join(parts)

        success = not is_error
        # Correct false failures for file-edit tools (SDK may report is_error
        # even when the edit was applied to disk).
        if not success:
            from backend.services.tool_formatters import correct_edit_success

            success = correct_edit_success(tool_name, success, result_text)

        tool_issue = None
        if not success:
            from backend.services.tool_formatters import extract_tool_issue

            tool_issue = extract_tool_issue(result_text) or "Tool reported an issue"

        if tool_name not in _HIDDEN_TOOLS:
            from backend.services.tool_formatters import classify_tool_visibility, format_tool_display, format_tool_display_full

            self._enqueue(
                session_id,
                SessionEvent(
                    kind=SessionEventKind.transcript,
                    payload={
                        "role": "tool_call",
                        "content": tool_name,
                        "tool_name": tool_name,
                        "tool_args": tool_args_str,
                        "tool_result": result_text,
                        "tool_success": success,
                        "tool_issue": tool_issue,
                        "turn_id": turn_id,
                        "tool_display": format_tool_display(
                            tool_name,
                            tool_args_str,
                            tool_result=result_text or None,
                            tool_success=success,
                        ),
                        "tool_display_full": format_tool_display_full(
                            tool_name,
                            tool_args_str,
                            tool_result=result_text or None,
                            tool_success=success,
                        ),
                        "tool_duration_ms": int(duration_ms),
                        "tool_visibility": classify_tool_visibility(tool_name, tool_args_str),
                    },
                ),
            )
            self._enqueue_log(
                session_id,
                f"Tool {'completed' if success else 'failed'}: {tool_name}",
                "info" if success else "warn",
                seq,
            )

        # Telemetry
        if job_id:
            self._record_tool_telemetry(
                session_id,
                job_id,
                "claude",
                tool_name=tool_name,
                tool_args_str=tool_args_str,
                success=success,
                duration_ms=duration_ms,
                result_text=result_text,
            )

    def _process_result_message(
        self,
        session_id: str,
        message: object,
        seq: list[int],
    ) -> None:
        """Handle the final ResultMessage — extract cost/usage and emit done."""
        job_id = self._session_to_job.get(session_id)
        result_text = getattr(message, "result", "") or ""
        total_cost_usd = getattr(message, "total_cost_usd", 0.0) or 0.0
        usage = getattr(message, "usage", {}) or {}
        duration_ms = getattr(message, "duration_ms", 0) or 0
        is_error = getattr(message, "is_error", False)

        input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
        cache_read = usage.get("cache_read_input_tokens", 0) if isinstance(usage, dict) else 0
        cache_write = usage.get("cache_creation_input_tokens", 0) if isinstance(usage, dict) else 0

        # Telemetry — note: model is not on ResultMessage, so we use the main model.
        if job_id:
            model = self._job_main_models.get(job_id, "")

            num_turns = getattr(message, "num_turns", 0) or 1
            self._record_llm_telemetry(
                job_id,
                "claude",
                model,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cache_read=int(cache_read),
                cache_write=int(cache_write),
                cost_usd=float(total_cost_usd),
                duration_ms=float(duration_ms),
                is_subagent=False,
                num_turns=int(num_turns),
            )
            self._record_llm_span(
                job_id,
                model,
                duration_ms=float(duration_ms),
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cache_read=int(cache_read),
                cache_write=int(cache_write),
                cost_usd=float(total_cost_usd),
                is_subagent=False,
                num_turns=int(num_turns),
            )

        self._enqueue_log(
            session_id,
            f"Session complete (cost=${total_cost_usd:.4f}, {input_tokens}+{output_tokens} tokens)",
            "info",
            seq,
        )

        if is_error:
            self._enqueue(
                session_id,
                SessionEvent(
                    kind=SessionEventKind.error,
                    payload={"message": "Claude session ended with error", "result": result_text},
                ),
            )
        else:
            self._enqueue(
                session_id,
                SessionEvent(kind=SessionEventKind.done, payload={"result": result_text}),
            )

    # ------------------------------------------------------------------
    # AgentAdapterInterface implementation
    # ------------------------------------------------------------------

    async def create_session(self, config: SessionConfig) -> str:
        from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

        session_id = str(uuid.uuid4())
        queue: asyncio.Queue[SessionEvent | None] = asyncio.Queue()
        self._queues[session_id] = queue

        if config.job_id:
            self.set_job_id(session_id, config.job_id)
            if config.model:
                self._requested_models[config.job_id] = config.model

        # Capture Claude subprocess stderr for diagnostics on failure
        stderr_fd, stderr_path = tempfile.mkstemp(prefix="claude_stderr_", suffix=".log")
        stderr_file = os.fdopen(stderr_fd, "w")
        self._stderr_files[session_id] = stderr_path

        # Build options
        options = ClaudeCodeOptions(
            cwd=config.workspace_path,
            model=config.model,
            permission_mode=_PERMISSION_MODE_MAP.get(config.permission_mode, "default"),  # type: ignore[arg-type]
            can_use_tool=self._build_can_use_tool(config, session_id),
            append_system_prompt=CODEPLANE_SYSTEM_PROMPT,
            extra_args={"debug-to-stderr": None},
            debug_stderr=stderr_file,
        )

        # MCP servers from CodePlane config
        if config.mcp_servers:
            mcp_config: dict[str, dict[str, Any]] = {}
            for name, srv in config.mcp_servers.items():
                entry: dict[str, Any] = {
                    "type": "stdio",
                    "command": srv.command,
                    "args": srv.args,
                }
                if srv.env:
                    entry["env"] = srv.env
                mcp_config[name] = entry
            options.mcp_servers = mcp_config  # type: ignore[assignment]

        # Resume support
        if config.resume_sdk_session_id:
            options.resume = config.resume_sdk_session_id

        # Create client and connect — the SDK requires an AsyncIterable prompt
        # when can_use_tool is set (streaming mode).
        try:
            client = ClaudeSDKClient(options)
            await client.connect(_prompt_to_stream(config.prompt))
        except Exception:
            if options.resume:
                # Resume failed — fall back to a fresh session (mirrors CopilotAdapter behaviour)
                log.warning(
                    "claude_session_resume_failed_creating_new",
                    resume_id=options.resume,
                    exc_info=True,
                )
                options.resume = None
                try:
                    client = ClaudeSDKClient(options)
                    await client.connect(_prompt_to_stream(config.prompt))
                except Exception:
                    log.error("claude_session_create_failed", exc_info=True)
                    self._cleanup_session(session_id)
                    raise
            else:
                log.error("claude_session_create_failed", exc_info=True)
                self._cleanup_session(session_id)
                raise

        self._clients[session_id] = client

        # Start background consumer
        task = asyncio.create_task(
            self._consume_messages(session_id, client),
            name=f"claude-consumer-{session_id[:8]}",
        )
        self._consumer_tasks[session_id] = task

        log.info("claude_session_created", session_id=session_id)
        return session_id

    async def stream_events(self, session_id: str) -> AsyncIterator[SessionEvent]:
        queue = self._queues.get(session_id)
        if queue is None:
            log.error("claude_stream_no_queue", session_id=session_id)
            yield SessionEvent(
                kind=SessionEventKind.error,
                payload={"message": "No queue for session"},
            )
            return
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=330)
                except TimeoutError:
                    # Consumer hung or sentinel was lost — treat as stream end.
                    log.error(
                        "claude_stream_queue_timeout",
                        session_id=session_id,
                    )
                    yield SessionEvent(
                        kind=SessionEventKind.error,
                        payload={"message": "Claude SDK stream timed out (no events for 330s)"},
                    )
                    return
                if event is None:
                    return
                yield event
        finally:
            # Cancel the consumer task first — this ensures the SDK subprocess
            # is no longer being read before we disconnect.
            consumer = self._consumer_tasks.get(session_id)
            if consumer and not consumer.done():
                consumer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await consumer

            # Kill the CLI subprocess using raw OS signals.
            #
            # We MUST NOT call client.disconnect(), transport.close(), or
            # ANY method on anyio-owned objects.  The SDK's Query holds an
            # anyio task-group whose cancel-scope was entered in a different
            # asyncio task.  Touching ANY anyio object (streams, Process,
            # etc.) from this task triggers cross-task cancel-scope
            # propagation that injects CancelledError into the entire
            # SQLAlchemy connection pool.
            #
            # os.kill(SIGTERM) + os.waitpid are pure OS calls that bypass
            # anyio entirely.  The subprocess is already dead or dying;
            # we just reap it so it doesn't become a zombie.
            _kill_sdk_subprocess(self._clients.get(session_id))
            self._cleanup_session(session_id)

    async def send_message(self, session_id: str, message: str) -> None:
        client = self._clients.get(session_id)
        if client is None:
            log.warning("claude_send_no_session", session_id=session_id)
            return
        try:
            # Start a new turn on the existing session
            await client.query(message)
        except Exception:
            log.warning("claude_send_message_failed", session_id=session_id, exc_info=True)

    async def interrupt_session(self, session_id: str) -> None:
        client = self._clients.get(session_id)
        if client is None:
            return
        try:
            await client.interrupt()
        except Exception:
            log.warning("claude_interrupt_failed", session_id=session_id, exc_info=True)


    async def abort_session(self, session_id: str) -> None:
        client = self._clients.get(session_id)
        if client is None:
            return
        try:
            await client.interrupt()
        except (Exception, asyncio.CancelledError):
            log.warning("claude_abort_interrupt_failed", session_id=session_id, exc_info=True)

        # Kill subprocess with raw OS signals — see stream_events comment.
        _kill_sdk_subprocess(client)
        self._cleanup_session(session_id)

    async def complete(self, prompt: str) -> CompletionResult:
        """Single-turn completion using the Claude Agent SDK."""
        from claude_code_sdk import (
            AssistantMessage,
            ClaudeCodeOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        from backend.services.agent_adapter import CompletionResult

        options = ClaudeCodeOptions(
            max_turns=1,
            model="claude-haiku-4-20250414",
            permission_mode="bypassPermissions",
            allowed_tools=[],
        )

        collected: list[str] = []
        result_meta: dict[str, object] = {}
        try:

            async def _run_query() -> None:
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in getattr(message, "content", []) or []:
                            if isinstance(block, TextBlock):
                                text = block.text
                                if text:
                                    collected.append(text)
                    elif isinstance(message, ResultMessage):
                        result = getattr(message, "result", "")
                        if result:
                            collected.append(result)
                        # Capture usage/cost from the result message
                        usage = getattr(message, "usage", {}) or {}
                        if isinstance(usage, dict):
                            result_meta["input_tokens"] = usage.get("input_tokens", 0)
                            result_meta["output_tokens"] = usage.get("output_tokens", 0)
                        result_meta["cost_usd"] = getattr(message, "total_cost_usd", 0.0) or 0.0
                        result_meta["model"] = getattr(message, "model", "") or ""
                        break

            await asyncio.wait_for(_run_query(), timeout=180)
        except TimeoutError:
            log.warning("claude_complete_timeout", prompt_len=len(prompt))
        except Exception:
            log.error("claude_complete_failed", prompt_len=len(prompt), exc_info=True)
            return CompletionResult()
        return CompletionResult(
            text="\n".join(collected),
            input_tokens=int(result_meta.get("input_tokens", 0) or 0),
            output_tokens=int(result_meta.get("output_tokens", 0) or 0),
            cost_usd=float(result_meta.get("cost_usd", 0.0) or 0.0),
            model=str(result_meta.get("model", "") or ""),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _prompt_to_stream(prompt: str) -> Any:  # noqa: ANN401
    """Wrap a string prompt as an async iterable for Claude SDK streaming mode.

    The generator **must** remain alive after yielding the initial prompt.
    When the generator returns, the SDK's ``stream_input`` calls
    ``transport.end_input()`` which closes stdin to the Claude subprocess.
    With stdin closed the SDK can no longer write control-protocol responses
    (tool permission results) back to the subprocess, so the first tool call
    hangs forever waiting for a permission response that will never arrive.
    """
    yield {
        "type": "user",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
        "session_id": "default",
    }
    # Keep the stream open so stdin is not closed.
    # The anyio task running stream_input will be cancelled when the
    # session disconnects — that is the normal cleanup path.
    # Use a bare Future — it suspends until cancelled, and correctly
    # propagates CancelledError under both asyncio and anyio.
    await asyncio.get_running_loop().create_future()
