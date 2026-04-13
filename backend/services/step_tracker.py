"""Turn-based step boundary detection.

Maps adapter-provided turnId changes to step lifecycle events. Pure state
machine — no LLM, no heuristics, no time-gap guessing.

SDK-agnostic: depends on the adapter contract (§2.2) not on SDK internals.
The adapters guarantee non-empty turn_id on every transcript event. If an
adapter violates this, the tracker logs a warning and assigns the event to
the current step (no phantom split).

Tracks: file paths touched per step, Git SHA at step boundaries.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.event_bus import EventBus
    from backend.services.git_service import GitService

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.git_service import GitError

log = structlog.get_logger()

_MAX_FILES_PER_STEP = 200

_READ_TOOLS = frozenset({
    "read_file", "grep_search", "file_search", "semantic_search", "view_image",
    "list_dir", "glob", "grep", "open_file",
    # Claude SDK PascalCase
    "Glob", "LS", "Grep", "NotebookRead",
})
_WRITE_TOOLS = frozenset({
    "replace_string_in_file", "create_file", "multi_replace_string_in_file", "create_directory",
    "edit", "write", "str_replace_based_edit_tool", "str_replace_editor",
    "insert_edit_into_file", "edit_file", "write_file", "delete_file",
    "create", "create_or_update_file", "apply_patch",
    # Claude SDK PascalCase
    "Edit", "Write", "NotebookEdit",
})


def _extract_file_path(tool_name: str, tool_args: str) -> str | None:
    """Best-effort extract of workspace-relative file path from tool args."""
    if not tool_args:
        return None
    try:
        args = json.loads(tool_args) if tool_args.startswith("{") else {}
        return args.get("filePath") or args.get("file_path") or args.get("path") or args.get("query")
    except (json.JSONDecodeError, AttributeError):
        return None


@dataclass
class _StepState:
    step_id: str
    step_number: int
    turn_id: str | None
    intent: str
    trigger: str
    started_at: datetime
    start_sha: str | None = None
    tool_count: int = 0
    last_agent_message: str | None = None
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)


class StepTracker:
    """Track step boundaries from transcript events using turnId.

    Rules (exhaustive):
    1. Operator message → always starts a new step
    2. First event of a new turnId → starts a new step (closes previous)
    3. First transcript event for a job → starts the first step
    4. Job terminal → closes the current step

    Idempotent: replayed events (e.g. after SSE reconnection) do not
    corrupt state — _open() is a no-op if the turnId is already active,
    and _close() tolerates closing an already-closed step.
    """

    def __init__(self, event_bus: EventBus, git_service: GitService | None = None) -> None:
        self._event_bus = event_bus
        self._git_service = git_service
        self._current: dict[str, _StepState] = {}
        self._counters: dict[str, int] = {}
        self._worktree_paths: dict[str, str] = {}  # job_id → worktree cwd

    def register_worktree(self, job_id: str, worktree_path: str) -> None:
        """Set the worktree path for a job. Called from _execute_session_attempt."""
        self._worktree_paths[job_id] = worktree_path

    def current_step(self, job_id: str) -> _StepState | None:
        return self._current.get(job_id)

    async def on_transcript_event(self, job_id: str, event: DomainEvent) -> None:
        """Process a TranscriptUpdated event."""
        payload = event.payload
        role = payload.get("role", "")
        content = payload.get("content", "")
        turn_id = payload.get("turn_id") or ""
        tool_intent = payload.get("tool_intent", "")

        if role == "agent_delta":
            return

        # Skip SDK-internal tools (they carry a new turn_id but shouldn't
        # trigger a step boundary).
        tool_name = payload.get("tool_name", "")
        if tool_name == "report_intent":
            # Extract the intent label and attach it to the current step
            # so the title generator can use it later.
            current = self._current.get(job_id)
            if current:
                args_raw = payload.get("tool_args") or ""
                if isinstance(args_raw, str):
                    import json as _json
                    try:
                        args_obj = _json.loads(args_raw)
                    except (ValueError, TypeError):
                        args_obj = {}
                else:
                    args_obj = args_raw
                intent_text = args_obj.get("intent") or args_obj.get("description") or ""
                if intent_text:
                    current.intent = intent_text[:120]
            return

        if not turn_id and role not in ("operator", "divider"):
            log.warning(
                "step_tracker_missing_turn_id",
                job_id=job_id,
                role=role,
                event_id=event.event_id,
            )

        current = self._current.get(job_id)

        new_step_trigger: str | None = None
        intent = ""

        if role == "operator":
            new_step_trigger = "operator_message"
            first_line = content.split("\n")[0].strip()
            intent = first_line[:120] if first_line else "Operator request"

        elif current is None:
            new_step_trigger = "job_start"
            intent = tool_intent or content[:120] or "Starting work"

        elif turn_id and turn_id != current.turn_id:
            new_step_trigger = "turn_change"
            intent = tool_intent or content[:120] or "Continuing work"

        # Idempotency: if turn_id matches current, no new step
        if new_step_trigger:
            if current:
                await self._close(job_id, current, "completed")
            await self._open(job_id, intent, turn_id, new_step_trigger)
            current = self._current[job_id]

        if current:
            if turn_id and not current.turn_id:
                current.turn_id = turn_id
            if role == "tool_call":
                current.tool_count += 1
                tool_name = payload.get("tool_name", "")
                tool_args = payload.get("tool_args", "")
                path = _extract_file_path(tool_name, tool_args)
                if path:
                    # Strip worktree prefix to get repo-relative path
                    wt = self._worktree_paths.get(job_id, "")
                    if wt and path.startswith(wt):
                        path = path[len(wt):].lstrip("/")
                    if tool_name in _READ_TOOLS and path not in current.files_read:
                        if len(current.files_read) < _MAX_FILES_PER_STEP:
                            current.files_read.append(path)
                    elif tool_name in _WRITE_TOOLS and path not in current.files_written:
                        if len(current.files_written) < _MAX_FILES_PER_STEP:
                            current.files_written.append(path)
            if role == "agent" and len(content) > 20:
                current.last_agent_message = content

    async def on_job_terminal(self, job_id: str, outcome: str) -> None:
        """Close current step when job reaches terminal state."""
        current = self._current.get(job_id)
        if not current:
            return  # Already closed or never opened — idempotent
        status = "completed" if outcome in ("review", "completed") else outcome
        await self._close(job_id, current, status)

    async def _open(
        self, job_id: str, intent: str, turn_id: str | None, trigger: str,
    ) -> None:
        n = self._counters.get(job_id, 0) + 1
        self._counters[job_id] = n
        step_id = f"step-{uuid.uuid4().hex[:12]}"

        start_sha: str | None = None
        if self._git_service:
            cwd = self._worktree_paths.get(job_id)
            if cwd:
                try:
                    start_sha = await self._git_service.rev_parse("HEAD", cwd=cwd)
                except GitError:
                    log.debug("step_open_rev_parse_failed", job_id=job_id, exc_info=True)

        state = _StepState(
            step_id=step_id,
            step_number=n,
            turn_id=turn_id,
            intent=intent,
            trigger=trigger,
            started_at=datetime.now(UTC),
            start_sha=start_sha,
        )
        self._current[job_id] = state
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=state.started_at,
            kind=DomainEventKind.step_started,
            payload={
                "step_id": step_id,
                "step_number": n,
                "turn_id": turn_id,
                "intent": intent,
                "trigger": trigger,
            },
        ))

    async def _close(
        self, job_id: str, state: _StepState, status: str,
    ) -> None:
        if job_id not in self._current:
            return  # Already closed — idempotent

        now = datetime.now(UTC)
        duration_ms = int((now - state.started_at).total_seconds() * 1000)

        end_sha: str | None = None
        if self._git_service:
            cwd = self._worktree_paths.get(job_id)
            if cwd:
                try:
                    # Auto-commit any uncommitted work so the SHA boundary
                    # captures exactly this step's changes.  ~50 ms, no-op
                    # when the worktree is clean.
                    await self._git_service.auto_commit(
                        cwd=cwd,
                        message=f"codeplane: step {state.step_number}",
                    )
                    end_sha = await self._git_service.rev_parse("HEAD", cwd=cwd)
                except GitError:
                    log.debug("step_close_git_failed", job_id=job_id, exc_info=True)

        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.step_completed,
            payload={
                "step_id": state.step_id,
                "turn_id": state.turn_id,
                "status": status,
                "tool_count": state.tool_count,
                "duration_ms": duration_ms,
                "has_summary": state.last_agent_message is not None,
                "agent_message": state.last_agent_message,
                "files_read": state.files_read[:20],
                "files_written": state.files_written[:20],
                "start_sha": state.start_sha,
                "end_sha": end_sha,
            },
        ))
        self._current.pop(job_id, None)

    def cleanup(self, job_id: str) -> None:
        """Remove all in-memory state for a job."""
        self._current.pop(job_id, None)
        self._counters.pop(job_id, None)
        self._worktree_paths.pop(job_id, None)
