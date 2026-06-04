"""Vendor-agnostic event processing pipeline for all SDK adapters and session watchers.

Both managed adapters (CopilotAdapter, ClaudeAdapter) and session watchers
(SessionStateWatcher, ClaudeSessionStateWatcher) normalize their vendor-specific
events into calls on this pipeline.  The pipeline knows nothing about SDK types,
event strings, or content-block structures — adapters handle all parsing.

Responsibilities consolidated here (previously duplicated across 4 code paths):
- Tool metadata buffering (start → complete pairing) with duration tracking
- Enriched payload generation (tool_display, tool_visibility, tool_intent, …)
- Log SessionEvent generation for operational events
- Tool telemetry recording (OTEL + DB: duration, classification, retry, file access, spans)
- file_changed event synthesis from tool writes
- Message counting (agent_messages, operator_messages)
- Usage / LLM telemetry recording
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.domain import (
    DonePayload,
    ErrorPayload,
    FileChangedPayload,
    LogPayload,
    SessionEvent,
    SessionEventKind,
    TranscriptPayload,
)
from backend.services.events.event_enricher import build_tool_call_payload, build_tool_running_payload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine

    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


class EventPipeline:
    """Vendor-agnostic event processor shared by all 4 ingestion paths.

    Adapters/watchers normalize their vendor-specific events, then call the
    ``on_*`` methods below.  This class never touches SDK objects, event-type
    strings, or content-block dicts.

    Constructed with:
    - ``emit``: async callback ``(job_id, event) -> None`` to deliver each
      produced SessionEvent.  The job_id allows multi-job consumers (watchers)
      to route events to the correct session.
    - ``schedule_write``: callback to schedule a fire-and-forget DB write
      coroutine (``_schedule_db_write`` for managed, ``_fire_bg`` wrapper for
      watchers).
    - ``sdk``: SDK name string for telemetry attributes (``"copilot"`` or
      ``"claude"``).
    """

    def __init__(
        self,
        *,
        emit: Callable[[str, SessionEvent], Awaitable[None]],
        schedule_write: Callable[[Coroutine[Any, Any, None]], None],
        sdk: str,
    ) -> None:
        self._emit = emit
        self._schedule_write = schedule_write
        self._sdk = sdk

        # Per-job state
        self._pending_tool_metadata: dict[str, dict[str, str]] = {}
        self._tool_start_times: dict[str, float] = {}
        self._job_tool_ids: dict[str, set[str]] = {}  # job_id → active tool_ids
        self._job_start_times: dict[str, float] = {}
        self._turn_counters: dict[str, int] = {}
        self._current_phases: dict[str, str] = {}
        self._log_seq: dict[str, int] = {}  # job_id → sequence counter

        # Retry trackers per job
        self._retry_trackers: dict[str, Any] = {}

        # Transcript ring buffer per job for motivation context
        self._transcript_buffers: dict[str, list[dict[str, str]]] = {}
        self._TRANSCRIPT_BUFFER_SIZE = 10

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def set_job_start_time(self, job_id: str, start: float | None = None) -> None:
        """Record when a job started (for span offset calculation)."""
        self._job_start_times.setdefault(job_id, start or time.monotonic())

    def set_execution_phase(self, job_id: str, phase: str) -> None:
        """Update the current execution phase for a job."""
        self._current_phases[job_id] = phase

    def advance_turn(self, job_id: str) -> int:
        """Advance the turn counter for a job and return the new value."""
        turn = self._turn_counters.get(job_id, 0) + 1
        self._turn_counters[job_id] = turn
        return turn

    def get_turn(self, job_id: str) -> int:
        """Return the current turn number for a job."""
        return self._turn_counters.get(job_id, 0)

    def cleanup_job(self, job_id: str) -> None:
        """Remove all per-job state."""
        self._job_start_times.pop(job_id, None)
        self._turn_counters.pop(job_id, None)
        self._current_phases.pop(job_id, None)
        self._log_seq.pop(job_id, None)
        self._retry_trackers.pop(job_id, None)
        self._transcript_buffers.pop(job_id, None)
        # Purge any orphaned tool metadata for this job
        orphan_tool_ids = self._job_tool_ids.pop(job_id, set())
        for tid in orphan_tool_ids:
            self._pending_tool_metadata.pop(tid, None)
            self._tool_start_times.pop(tid, None)

    def get_buffered_tool(self, tool_id: str) -> dict[str, str]:
        """Get buffered metadata for a tool_id (for intermediate events)."""
        return self._pending_tool_metadata.get(tool_id, {})

    # ------------------------------------------------------------------
    # Transcript events  (adapter calls these after normalizing)
    # ------------------------------------------------------------------

    async def on_agent_message(
        self,
        job_id: str,
        content: str,
        *,
        title: str | None = None,
    ) -> None:
        """Agent produced a complete text message."""
        self.set_job_start_time(job_id)
        payload = TranscriptPayload(role="agent", content=content)
        if title is not None:
            payload["title"] = title
        await self._emit(job_id, SessionEvent(kind=SessionEventKind.transcript, payload=payload))
        self._buffer_transcript(job_id, payload)
        self._record_message_count(job_id, "agent")

    async def on_agent_delta(self, job_id: str, delta: str) -> None:
        """Streaming chunk of agent text."""
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.transcript,
                payload=TranscriptPayload(role="agent_delta", content=delta),
            ),
        )

    async def on_reasoning(self, job_id: str, content: str) -> None:
        """Agent produced a reasoning/thinking block."""
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.transcript,
                payload=TranscriptPayload(role="reasoning", content=content),
            ),
        )

    async def on_reasoning_delta(self, job_id: str, delta: str) -> None:
        """Streaming chunk of reasoning text."""
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.transcript,
                payload=TranscriptPayload(role="reasoning_delta", content=delta),
            ),
        )

    async def on_user_message(self, job_id: str, content: str) -> None:
        """User/operator sent a message."""
        payload = TranscriptPayload(role="operator", content=content)
        await self._emit(job_id, SessionEvent(kind=SessionEventKind.transcript, payload=payload))
        self._buffer_transcript(job_id, payload)
        self._record_message_count(job_id, "operator")

    # ------------------------------------------------------------------
    # Tool lifecycle
    # ------------------------------------------------------------------

    async def on_tool_start(
        self,
        job_id: str,
        tool_id: str,
        tool_name: str,
        args_str: str | None,
        *,
        intent: str | None = None,
        title: str | None = None,
        turn_id: str | None = None,
        hidden: bool = False,
    ) -> None:
        """A tool execution has started.

        Buffers metadata for pairing with ``on_tool_complete``, emits a
        ``tool_running`` transcript event, and logs the start.
        If *hidden* the tool_running event is suppressed (but metadata is
        still buffered so ``on_tool_complete`` can access it).
        """
        self.set_job_start_time(job_id)
        self._tool_start_times[tool_id] = time.monotonic()
        self._pending_tool_metadata[tool_id] = {
            "tool_name": tool_name,
            "tool_args": args_str or "",
            "turn_id": turn_id or "",
            "tool_intent": intent or "",
            "tool_title": title or "",
        }
        self._job_tool_ids.setdefault(job_id, set()).add(tool_id)

        if hidden:
            return

        payload = build_tool_running_payload(
            tool_name,
            args_str,
            turn_id or "",
            tool_intent=intent,
            tool_title=title,
        )
        await self._emit(job_id, SessionEvent(kind=SessionEventKind.transcript, payload=payload))
        await self._emit_log(job_id, f"Tool started: {tool_name}", "debug")

        # Emit file_changed for file-write tools to trigger diff
        from backend.services.tools.tool_classifier import classify_tool, extract_file_paths

        if classify_tool(tool_name) == "file_write":
            for fpath in extract_file_paths(tool_name, args_str):
                await self.on_file_changed(job_id, fpath)

    async def on_tool_partial(
        self,
        job_id: str,
        tool_id: str,
        chunk: str,
    ) -> None:
        """Streaming output from a running tool."""
        if not chunk:
            return
        buffered = self._pending_tool_metadata.get(tool_id, {})
        tool_name = buffered.get("tool_name", "tool")

        from backend.services.tool_formatters import classify_tool_visibility

        vis = classify_tool_visibility(tool_name, buffered.get("tool_args"))
        if vis == "hidden":
            return

        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.transcript,
                payload=TranscriptPayload(
                    role="tool_output_delta",
                    content=chunk,
                    tool_name=tool_name,
                    tool_call_id=tool_id,
                    turn_id=buffered.get("turn_id", ""),
                ),
            ),
        )

    async def on_tool_complete(
        self,
        job_id: str,
        tool_id: str,
        result_text: str,
        success: bool,
        *,
        hidden: bool = False,
    ) -> None:
        """A tool execution has finished.

        Pairs with a prior ``on_tool_start`` for the same *tool_id* to compute
        duration and retrieve buffered metadata.  Emits a ``tool_call``
        transcript event, a log line, and records full tool telemetry.
        """
        buffered = self._pending_tool_metadata.pop(tool_id, {})
        start = self._tool_start_times.pop(tool_id, None)
        # Remove from job→tool tracking (direct lookup, not scan)
        tids = self._job_tool_ids.get(job_id)
        if tids:
            tids.discard(tool_id)
        tool_name = buffered.get("tool_name", "tool")
        tool_args_str = buffered.get("tool_args") or None
        turn_id = buffered.get("turn_id") or None
        tool_intent = buffered.get("tool_intent") or None
        tool_title = buffered.get("tool_title") or None

        duration_ms = ((time.monotonic() - start) * 1000) if start is not None else None

        payload = build_tool_call_payload(
            tool_name,
            tool_args_str,
            result_text,
            success,
            turn_id=turn_id,
            duration_ms=duration_ms,
            tool_intent=tool_intent,
            tool_title=tool_title,
        )
        final_success = payload["tool_success"]

        if not hidden:
            await self._emit(job_id, SessionEvent(kind=SessionEventKind.transcript, payload=payload))
            self._buffer_transcript(job_id, payload)
            await self._emit_log(
                job_id,
                f"Tool {'completed' if final_success else 'failed'}: {tool_name}",
                "info" if final_success else "warn",
            )

        # Tool telemetry (always, even for hidden tools)
        self._record_tool_telemetry(
            job_id,
            tool_name=tool_name,
            tool_args_str=tool_args_str,
            success=final_success,
            duration_ms=duration_ms or 0.0,
            result_text=result_text,
            turn_id=turn_id,
        )

    # ------------------------------------------------------------------
    # File changes
    # ------------------------------------------------------------------

    async def on_file_changed(self, job_id: str, path: str) -> None:
        """A file was created or modified."""
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.file_changed,
                payload=FileChangedPayload(path=path),
            ),
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def on_done(self, job_id: str, payload: DonePayload | None = None) -> None:
        """Agent session completed."""
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.done,
                payload=payload or DonePayload(),
            ),
        )

    async def on_error(self, job_id: str, payload: ErrorPayload | None = None) -> None:
        """Agent session errored."""
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.error,
                payload=payload or ErrorPayload(),
            ),
        )

    # ------------------------------------------------------------------
    # Usage / telemetry  (all fields are plain values, no SDK objects)
    # ------------------------------------------------------------------

    async def on_usage(
        self,
        job_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        model: str = "",
        is_subagent: bool = False,
        advance_turn: bool = False,
        num_turns: int = 1,
    ) -> None:
        """Record an LLM usage event (token counts, cost, timing)."""
        from backend.services.analytics import telemetry as tel

        attrs: dict[str, Any] = {"job_id": job_id, "sdk": self._sdk}
        tel.tokens_input.add(input_tokens, {**attrs, "model": model})
        tel.tokens_output.add(output_tokens, {**attrs, "model": model})
        tel.tokens_cache_read.add(cache_read_tokens, attrs)
        tel.tokens_cache_write.add(cache_write_tokens, attrs)
        if cost_usd:
            tel.cost_usd.add(cost_usd, attrs)
        if duration_ms:
            tel.llm_duration.record(duration_ms, {**attrs, "is_subagent": is_subagent})

        db_counters: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "llm_call_count": num_turns,
        }
        if cost_usd:
            db_counters["total_cost_usd"] = cost_usd
        if is_subagent and cost_usd:
            db_counters["subagent_cost_usd"] = cost_usd
        if duration_ms:
            db_counters["total_llm_duration_ms"] = int(duration_ms)
        if advance_turn:
            db_counters["total_turns"] = num_turns
        self._schedule_write(self._db_increment(job_id, **db_counters))

        if advance_turn:
            self.advance_turn(job_id)

        if model:
            self._schedule_write(self._db_set_model(job_id, model))

        # LLM span (only if we have meaningful data)
        if duration_ms or input_tokens or output_tokens:
            self._record_llm_span(
                job_id,
                model,
                duration_ms,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
                cost_usd,
            )

        # Log
        if model or input_tokens or output_tokens:
            await self._emit_log(
                job_id,
                f"LLM call: {model} ({input_tokens}+{output_tokens} tokens)",
                "debug",
            )

    async def on_context_update(self, job_id: str, current_tokens: int) -> None:
        """Context window token count updated."""
        from backend.services.analytics import telemetry as tel

        tel.context_tokens_gauge.set(current_tokens, {"job_id": job_id, "sdk": self._sdk})
        self._schedule_write(self._db_set_context(job_id, current_tokens=current_tokens))

    async def on_compaction(
        self,
        job_id: str,
        pre_tokens: int,
        post_tokens: int,
    ) -> None:
        """Context was compacted."""
        from backend.services.analytics import telemetry as tel

        attrs: dict[str, Any] = {"job_id": job_id, "sdk": self._sdk}
        tel.compactions_counter.add(1, attrs)
        tel.tokens_compacted.add(max(0, pre_tokens - post_tokens), attrs)
        self._schedule_write(
            self._db_increment(
                job_id,
                compactions=1,
                tokens_compacted=max(0, pre_tokens - post_tokens),
            )
        )
        if post_tokens:
            tel.context_tokens_gauge.set(post_tokens, attrs)
            self._schedule_write(self._db_set_context(job_id, current_tokens=post_tokens))
        await self._emit_log(
            job_id,
            f"Context compacted: {pre_tokens} \u2192 {post_tokens} tokens",
            "warn",
        )

    async def on_model_change(self, job_id: str, model: str) -> None:
        """Active model changed."""
        self._schedule_write(self._db_set_model(job_id, model))
        await self._emit_log(job_id, f"Model changed to {model}")

    async def on_truncation(self, job_id: str, window_size: int) -> None:
        """Context window size / truncation limit reported."""
        from backend.services.analytics import telemetry as tel

        tel.context_window_gauge.set(window_size, {"job_id": job_id, "sdk": self._sdk})
        self._schedule_write(self._db_set_context(job_id, window_size=window_size))

    async def on_shutdown(
        self,
        job_id: str,
        *,
        premium_requests: float | None = None,
    ) -> None:
        """Session is shutting down; record any final counters."""
        if premium_requests is not None:
            from backend.services.analytics import telemetry as tel

            tel.premium_requests_counter.add(
                premium_requests,
                {"job_id": job_id, "sdk": self._sdk},
            )
            self._schedule_write(
                self._db_increment(
                    job_id,
                    premium_requests=premium_requests,
                )
            )

    # ------------------------------------------------------------------
    # Log event emission
    # ------------------------------------------------------------------

    async def _emit_log(self, job_id: str, message: str, level: str = "info") -> None:
        """Emit a log SessionEvent."""
        seq = self._log_seq.get(job_id, 0) + 1
        self._log_seq[job_id] = seq
        await self._emit(
            job_id,
            SessionEvent(
                kind=SessionEventKind.log,
                payload=LogPayload(
                    seq=seq,
                    timestamp=datetime.now(UTC).isoformat(),
                    level=level,
                    message=message,
                ),
            ),
        )

    # ------------------------------------------------------------------
    # Tool telemetry recording
    # ------------------------------------------------------------------

    def _record_tool_telemetry(
        self,
        job_id: str,
        *,
        tool_name: str,
        tool_args_str: str | None,
        success: bool,
        duration_ms: float,
        result_text: str,
        turn_id: str | None = None,
    ) -> None:
        """Record OTEL metrics + DB writes for a tool execution.

        Handles: tool_duration counter, tool classification, retry detection,
        file access tracking, summary increment, and span insertion.
        """
        from backend.services.analytics import telemetry as tel
        from backend.services.tools.tool_classifier import (
            classify_tool,
            extract_file_paths,
            extract_tool_target,
            refine_shell_category,
        )

        attrs: dict[str, Any] = {
            "job_id": job_id,
            "sdk": self._sdk,
            "tool_name": tool_name,
            "success": bool(success),
        }
        tel.tool_duration.record(duration_ms, attrs)

        category = classify_tool(tool_name)
        if category == "shell":
            refined = refine_shell_category(tool_args_str)
            if refined:
                category = refined
        target = extract_tool_target(tool_name, tool_args_str)
        current_phase = self._current_phases.get(job_id, "agent_reasoning")
        turn_num = self._turn_counters.get(job_id, 0)

        # Retry detection
        from backend.services.job.retry_tracker import RetryTracker

        if job_id not in self._retry_trackers:
            self._retry_trackers[job_id] = RetryTracker()
        retry_result = self._retry_trackers[job_id].record(tool_name, target, 0, success)

        result_size = len(result_text.encode("utf-8", errors="replace")) if result_text else None

        # File access tracking
        file_rw_increment: dict[str, int] = {}
        if category in ("file_read", "file_write"):
            paths = extract_file_paths(tool_name, tool_args_str)
            access_type = "write" if category == "file_write" else "read"
            if access_type == "read":
                file_rw_increment["file_read_count"] = 1
            else:
                file_rw_increment["file_write_count"] = 1
            for fpath in paths:
                self._schedule_write(
                    self._db_record_file_access(
                        job_id=job_id,
                        file_path=fpath,
                        access_type=access_type,
                        turn_number=turn_num,
                    )
                )

        # Summary increment
        self._schedule_write(
            self._db_increment(
                job_id,
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

        self._schedule_write(
            self._db_insert_span(
                job_id=job_id,
                span_type="tool",
                name=tool_name,
                started_at=round(offset, 2),
                duration_ms=duration_ms,
                attrs={
                    "success": success,
                    **({"error_snippet": result_text} if not success and result_text else {}),
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

    def _record_llm_span(
        self,
        job_id: str,
        model: str,
        duration_ms: float,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_write: int,
        cost_usd: float,
    ) -> None:
        """Insert an LLM span."""
        turn_num = self._turn_counters.get(job_id, 0)
        current_phase = self._current_phases.get(job_id, "agent_reasoning")
        job_start = self._job_start_times.get(job_id, time.monotonic())
        offset = time.monotonic() - job_start

        self._schedule_write(
            self._db_insert_span(
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
                },
                turn_number=turn_num,
                execution_phase=current_phase,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=cost_usd,
            )
        )

    def _record_message_count(self, job_id: str, role: str) -> None:
        """Record a message count increment (OTEL + DB)."""
        from backend.services.analytics import telemetry as tel

        tel.messages_counter.add(1, {"job_id": job_id, "sdk": self._sdk, "role": role})
        key = "agent_messages" if role == "agent" else "operator_messages"
        self._schedule_write(self._db_increment(job_id, **{key: 1}))

    # ------------------------------------------------------------------
    # Transcript ring buffer for motivation context
    # ------------------------------------------------------------------

    def _buffer_transcript(self, job_id: str, payload: TranscriptPayload) -> None:
        """Append a compact transcript entry to the per-job ring buffer.

        For completed tool calls (role=tool_call with a tool_result field),
        the raw result content is stored directly so the downstream motivation
        model can interpret it in context.  No separate summarization step —
        the model that generates write motivations already processes
        preceding_context and will extract the relevant signal.
        """
        role = payload.get("role", "")
        if role in ("agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"):
            return
        entry: dict[str, str] = {"role": role}
        tool_name = payload.get("tool_name")
        if role == "tool_call":
            if tool_name:
                entry["tool_name"] = str(tool_name)
            tool_args = payload.get("tool_args")
            if tool_args:
                entry["tool_args"] = str(tool_args)
            raw_result = str(payload.get("tool_result", "") or "")
            if raw_result:
                entry["tool_result"] = raw_result
        else:
            entry["content"] = str(payload.get("content", ""))
            if tool_name:
                entry["tool_name"] = str(tool_name)
        buf = self._transcript_buffers.setdefault(job_id, [])
        buf.append(entry)
        if len(buf) > self._TRANSCRIPT_BUFFER_SIZE:
            del buf[: len(buf) - self._TRANSCRIPT_BUFFER_SIZE]

    def _snapshot_preceding_context(self, job_id: str) -> str | None:
        """Return JSON array of the last transcript entries, or None."""
        buf = self._transcript_buffers.get(job_id)
        if not buf:
            return None
        return json.dumps(list(buf), ensure_ascii=False)

    # Mutative shell command prefixes
    _MUTATIVE_SHELL_PREFIXES: frozenset[str] = frozenset(
        {
            "git commit",
            "git add",
            "git push",
            "git checkout",
            "git merge",
            "git rebase",
            "git reset",
            "git stash",
            "git cherry-pick",
            "git tag",
            "git branch -d",
            "git branch -D",
            "git branch -m",
            "mkdir",
            "mv",
            "rm",
            "cp",
            "ln",
            "chmod",
            "chown",
            "touch",
            "pip install",
            "pip uninstall",
            "uv add",
            "uv remove",
            "uv sync",
            "uv pip install",
            "npm install",
            "npm uninstall",
            "npm ci",
            "yarn add",
            "yarn remove",
            "pnpm add",
            "pnpm remove",
            "docker build",
            "docker run",
            "docker compose up",
            "make",
            "cargo build",
            "go build",
        }
    )

    def _maybe_capture_context(
        self,
        job_id: str,
        category: str,
        tool_args_str: str | None,
    ) -> str | None:
        """Capture preceding transcript context for mutative tool actions."""
        from backend.services.tools.parsing_utils import ensure_dict

        if category in {"file_write", "git_write"}:
            return self._snapshot_preceding_context(job_id)
        if category == "shell" and tool_args_str:
            parsed = ensure_dict(tool_args_str)
            if parsed:
                cmd = str(parsed.get("command", "")).strip().lower()
                if any(cmd.startswith(p) for p in self._MUTATIVE_SHELL_PREFIXES):
                    return self._snapshot_preceding_context(job_id)
        return None

    # ------------------------------------------------------------------
    # DB write helpers (use serialized_write internally)
    # ------------------------------------------------------------------

    async def _db_increment(self, job_id: str, **counters: Any) -> None:
        """Increment telemetry summary counters."""
        try:
            async with self._get_db_session() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                repo = TelemetrySummaryRepository(session)
                totals = await repo.increment(job_id=job_id, **counters)
                if not totals.get("_row_found") and counters:
                    await repo.init_job(job_id, sdk=self._sdk)
                    await repo.increment(job_id=job_id, **counters)
        except Exception:
            log.warning("pipeline_db_write_failed", fn="increment", exc_info=True)

    async def _db_insert_span(self, *, job_id: str, **span_fields: Any) -> None:
        """Insert a telemetry span row."""
        try:
            async with self._get_db_session() as session:
                from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository

                await TelemetrySpansRepository(session).insert(job_id=job_id, **span_fields)
        except Exception:
            log.warning("pipeline_db_write_failed", fn="insert_span", exc_info=True)

    async def _db_set_model(self, job_id: str, model: str) -> None:
        """Record the main model for a job."""
        try:
            async with self._get_db_session() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                await TelemetrySummaryRepository(session).set_model(job_id=job_id, model=model)
        except Exception:
            log.warning("pipeline_db_write_failed", fn="set_model", exc_info=True)

    async def _db_set_context(
        self,
        job_id: str,
        *,
        current_tokens: int | None = None,
        window_size: int | None = None,
    ) -> None:
        """Record context window usage."""
        try:
            async with self._get_db_session() as session:
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                await TelemetrySummaryRepository(session).set_context(
                    job_id=job_id,
                    current_tokens=current_tokens,
                    window_size=window_size,
                )
        except Exception:
            log.warning("pipeline_db_write_failed", fn="set_context", exc_info=True)

    async def _db_record_file_access(
        self,
        *,
        job_id: str,
        file_path: str,
        access_type: str,
        turn_number: int,
    ) -> None:
        """Record a file read/write access."""
        try:
            async with self._get_db_session() as session:
                from backend.persistence.file_access_repo import FileAccessRepository

                await FileAccessRepository(session).record(
                    job_id=job_id,
                    file_path=file_path,
                    access_type=access_type,
                    turn_number=turn_number,
                )
        except Exception:
            log.warning("pipeline_db_write_failed", fn="record_file_access", exc_info=True)

    # ------------------------------------------------------------------
    # DB session helper
    # ------------------------------------------------------------------

    _session_factory: Any = None

    def set_session_factory(self, factory: Any) -> None:
        """Set the SQLAlchemy session factory for DB writes."""
        self._session_factory = factory

    @asynccontextmanager
    async def _get_db_session(self) -> AsyncIterator[AsyncSession]:
        """Yield a scoped DB session with commit and error handling."""
        from backend.persistence.database import serialized_write

        if self._session_factory is None:
            raise RuntimeError("EventPipeline: no session_factory configured")
        async with serialized_write(self._session_factory) as session:
            yield session
