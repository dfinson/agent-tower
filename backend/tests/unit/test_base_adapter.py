"""Tests for backend.services.base_adapter — shared adapter infrastructure.

Covers the pure-logic helpers and state management that don't require
a running SDK subprocess:
  - _is_mutative_shell classification
  - _build_permission_description formatting
  - Transcript ring buffer
  - Queue / session state management
  - Permission description building
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.base_adapter import BaseAgentAdapter, PermissionDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ConcreteAdapter(BaseAgentAdapter):
    """Minimal concrete subclass for testing shared BaseAgentAdapter logic."""

    async def create_session(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError

    async def send_message(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError

    async def abort_session(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError

    async def complete(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError

    async def stream_events(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError


def _make_adapter(**kwargs) -> BaseAgentAdapter:
    """Create a concrete BaseAgentAdapter with mocked collaborators."""
    defaults = {
        "approval_service": None,
        "event_bus": None,
        "session_factory": None,
    }
    defaults.update(kwargs)
    return _ConcreteAdapter(**defaults)


# ===================================================================
# _is_mutative_shell — pure static, no deps
# ===================================================================


class TestIsMutativeShell:
    def test_git_commit(self) -> None:
        args = json.dumps({"command": "git commit -m 'fix'"})
        assert BaseAgentAdapter._is_mutative_shell(args) is True

    def test_git_push(self) -> None:
        args = json.dumps({"command": "git push origin main"})
        assert BaseAgentAdapter._is_mutative_shell(args) is True

    def test_rm_command(self) -> None:
        args = json.dumps({"command": "rm -rf build/"})
        assert BaseAgentAdapter._is_mutative_shell(args) is True

    def test_pip_install(self) -> None:
        args = json.dumps({"command": "pip install requests"})
        assert BaseAgentAdapter._is_mutative_shell(args) is True

    def test_read_only_git(self) -> None:
        args = json.dumps({"command": "git log --oneline"})
        assert BaseAgentAdapter._is_mutative_shell(args) is False

    def test_cat_command(self) -> None:
        args = json.dumps({"command": "cat README.md"})
        assert BaseAgentAdapter._is_mutative_shell(args) is False

    def test_none_input(self) -> None:
        assert BaseAgentAdapter._is_mutative_shell(None) is False

    def test_empty_string(self) -> None:
        assert BaseAgentAdapter._is_mutative_shell("") is False

    def test_malformed_json(self) -> None:
        assert BaseAgentAdapter._is_mutative_shell("{bad json") is False

    def test_missing_command_key(self) -> None:
        args = json.dumps({"cmd": "rm -rf /"})
        assert BaseAgentAdapter._is_mutative_shell(args) is False

    def test_docker_build(self) -> None:
        args = json.dumps({"command": "docker build -t myapp ."})
        assert BaseAgentAdapter._is_mutative_shell(args) is True

    def test_npm_install(self) -> None:
        args = json.dumps({"command": "npm install express"})
        assert BaseAgentAdapter._is_mutative_shell(args) is True

    def test_case_insensitive(self) -> None:
        args = json.dumps({"command": "Git Commit -m 'fix'"})
        assert BaseAgentAdapter._is_mutative_shell(args) is True


# ===================================================================
# _build_permission_description — pure static
# ===================================================================


class TestBuildPermissionDescription:
    def test_shell_with_command(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "shell", "Bash", {"command": "ls -la"}, "ls -la"
        )
        assert desc.startswith("Run shell:")
        assert "ls -la" in desc

    def test_shell_no_input(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "shell", "Bash", None, "echo hi"
        )
        assert "echo hi" in desc

    def test_write_file(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "write", "Edit", {"file_path": "/tmp/foo.py"}, None
        )
        assert desc.startswith("Write file:")
        assert "/tmp/foo.py" in desc

    def test_web_search(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "search", "WebSearch", {"query": "python async"}, None
        )
        assert "Web search:" in desc
        assert "python async" in desc

    def test_web_fetch(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "url", "WebFetch", {"url": "https://example.com"}, None
        )
        assert "Fetch URL:" in desc

    def test_read_file(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "read", "Read", {"file_path": "/etc/hosts"}, None
        )
        assert desc.startswith("Read file:")

    def test_generic_tool(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "custom", "MyTool", {"arg": "val"}, None
        )
        assert desc.startswith("MyTool:")

    def test_fallback_to_command_text(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "unknown", "", None, "some raw text"
        )
        assert desc == "some raw text"

    def test_fallback_to_kind(self) -> None:
        desc = BaseAgentAdapter._build_permission_description(
            "unknown", "", None, None
        )
        assert desc == "unknown"


# ===================================================================
# Transcript ring buffer
# ===================================================================


class TestTranscriptBuffer:
    def test_buffer_and_snapshot(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        adapter._buffer_transcript("s1", {
            "role": "agent",
            "content": "hello world",
        })
        snap = adapter._snapshot_preceding_context("j1")
        assert snap is not None
        parsed = json.loads(snap)
        assert len(parsed) == 1
        assert parsed[0]["role"] == "agent"
        assert parsed[0]["content"] == "hello world"

    def test_ring_buffer_eviction(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        buf_size = adapter._TRANSCRIPT_BUFFER_SIZE
        for i in range(buf_size + 5):
            adapter._buffer_transcript("s1", {
                "role": "agent",
                "content": f"msg-{i}",
            })
        buf = adapter._transcript_buffers["j1"]
        assert len(buf) == buf_size
        # Oldest entries should have been evicted
        assert buf[0]["content"] == f"msg-5"

    def test_skips_delta_roles(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        for role in ("agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"):
            adapter._buffer_transcript("s1", {"role": role, "content": "x"})
        assert "j1" not in adapter._transcript_buffers

    def test_snapshot_empty(self) -> None:
        adapter = _make_adapter()
        assert adapter._snapshot_preceding_context("nonexistent") is None

    def test_content_truncation(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        long_content = "a" * (adapter._TRANSCRIPT_CONTENT_MAX + 100)
        adapter._buffer_transcript("s1", {"role": "agent", "content": long_content})
        buf = adapter._transcript_buffers["j1"]
        assert len(buf[0]["content"]) == adapter._TRANSCRIPT_CONTENT_MAX

    def test_tool_name_captured(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        adapter._buffer_transcript("s1", {
            "role": "tool_result",
            "content": "ok",
            "tool_name": "read_file",
            "tool_args": '{"path": "/foo"}',
        })
        buf = adapter._transcript_buffers["j1"]
        assert buf[0]["tool_name"] == "read_file"
        assert "tool_args" in buf[0]

    def test_no_job_mapping_ignored(self) -> None:
        adapter = _make_adapter()
        adapter._buffer_transcript("unknown_session", {"role": "agent", "content": "x"})
        assert len(adapter._transcript_buffers) == 0


# ===================================================================
# _maybe_capture_context
# ===================================================================


class TestMaybeCaptureContext:
    def test_file_write_captures(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        adapter._buffer_transcript("s1", {"role": "agent", "content": "writing file"})
        ctx = adapter._maybe_capture_context("j1", "file_write", None)
        assert ctx is not None

    def test_git_write_captures(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        adapter._buffer_transcript("s1", {"role": "agent", "content": "committing"})
        ctx = adapter._maybe_capture_context("j1", "git_write", None)
        assert ctx is not None

    def test_read_only_does_not_capture(self) -> None:
        adapter = _make_adapter()
        ctx = adapter._maybe_capture_context("j1", "file_read", None)
        assert ctx is None

    def test_mutative_shell_captures(self) -> None:
        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        adapter._buffer_transcript("s1", {"role": "agent", "content": "running"})
        args = json.dumps({"command": "rm -rf build/"})
        ctx = adapter._maybe_capture_context("j1", "shell", args)
        assert ctx is not None

    def test_nonmutative_shell_no_capture(self) -> None:
        adapter = _make_adapter()
        args = json.dumps({"command": "cat README.md"})
        ctx = adapter._maybe_capture_context("j1", "shell", args)
        assert ctx is None


# ===================================================================
# Queue and session state management
# ===================================================================


class TestSessionState:
    def test_set_job_id(self) -> None:
        adapter = _make_adapter()
        adapter.set_job_id("s1", "j1")
        assert adapter._session_to_job["s1"] == "j1"
        assert "j1" in adapter._job_start_times

    def test_pause_and_resume_tools(self) -> None:
        adapter = _make_adapter()
        adapter.pause_tools("s1")
        assert "s1" in adapter._paused_sessions
        adapter.resume_tools("s1")
        assert "s1" not in adapter._paused_sessions

    def test_resume_nonexistent_is_noop(self) -> None:
        adapter = _make_adapter()
        adapter.resume_tools("nonexistent")  # should not raise

    def test_cleanup_session_state(self) -> None:
        adapter = _make_adapter()
        adapter.set_job_id("s1", "j1")
        adapter._queues["s1"] = asyncio.Queue()
        adapter._clients["s1"] = object()
        adapter._paused_sessions.add("s1")
        adapter._turn_counters["j1"] = 5
        adapter._current_phases["j1"] = "agent_reasoning"
        adapter._transcript_buffers["j1"] = [{"role": "agent", "content": "x"}]

        adapter._cleanup_session_state("s1")

        assert "s1" not in adapter._session_to_job
        assert "s1" not in adapter._queues
        assert "s1" not in adapter._clients
        assert "s1" not in adapter._paused_sessions
        assert "j1" not in adapter._job_start_times
        assert "j1" not in adapter._turn_counters
        assert "j1" not in adapter._current_phases
        assert "j1" not in adapter._transcript_buffers

    def test_cleanup_unknown_session(self) -> None:
        adapter = _make_adapter()
        adapter._cleanup_session_state("nonexistent")  # should not raise

    def test_set_execution_phase(self) -> None:
        from backend.models.api_schemas import ExecutionPhase

        adapter = _make_adapter()
        adapter.set_execution_phase("j1", ExecutionPhase.agent_reasoning)
        assert adapter._current_phases["j1"] == ExecutionPhase.agent_reasoning


# ===================================================================
# Enqueue helpers
# ===================================================================


class TestEnqueue:
    def test_enqueue_to_existing_queue(self) -> None:
        from backend.models.domain import SessionEvent, SessionEventKind

        adapter = _make_adapter()
        q: asyncio.Queue[SessionEvent | None] = asyncio.Queue()
        adapter._queues["s1"] = q
        evt = SessionEvent(kind=SessionEventKind.log, payload={"msg": "hi"})
        adapter._enqueue("s1", evt)
        assert q.qsize() == 1

    def test_enqueue_to_missing_queue(self) -> None:
        from backend.models.domain import SessionEvent, SessionEventKind

        adapter = _make_adapter()
        evt = SessionEvent(kind=SessionEventKind.log, payload={"msg": "hi"})
        adapter._enqueue("no-queue", evt)  # should not raise

    def test_enqueue_transcript_buffers(self) -> None:
        from backend.models.domain import SessionEvent, SessionEventKind

        adapter = _make_adapter()
        adapter._session_to_job["s1"] = "j1"
        adapter._queues["s1"] = asyncio.Queue()
        evt = SessionEvent(
            kind=SessionEventKind.transcript,
            payload={"role": "agent", "content": "test"},
        )
        adapter._enqueue("s1", evt)
        assert "j1" in adapter._transcript_buffers

    def test_enqueue_log_increments_seq(self) -> None:
        adapter = _make_adapter()
        adapter._queues["s1"] = asyncio.Queue()
        seq = [0]
        adapter._enqueue_log("s1", "msg1", seq=seq)
        assert seq[0] == 1
        adapter._enqueue_log("s1", "msg2", seq=seq)
        assert seq[0] == 2


# ===================================================================
# DB write scheduling (backpressure)
# ===================================================================


class TestScheduleDbWrite:
    @pytest.mark.asyncio
    async def test_schedule_write_creates_task(self) -> None:
        adapter = _make_adapter()
        called = asyncio.Event()

        async def fake_coro() -> None:
            called.set()

        adapter._schedule_db_write(fake_coro())
        await asyncio.sleep(0.01)
        assert called.is_set()

    @pytest.mark.asyncio
    async def test_backpressure_drops_writes(self) -> None:
        adapter = _make_adapter()
        # Fill with fake pending tasks that never complete
        for _ in range(adapter._MAX_PENDING_WRITES):
            async def _block() -> None:
                await asyncio.sleep(999)
            task = asyncio.create_task(_block())
            adapter._write_tasks.append(task)

        dropped = asyncio.Event()

        async def should_not_run() -> None:
            dropped.set()

        adapter._schedule_db_write(should_not_run())
        await asyncio.sleep(0.01)
        assert not dropped.is_set()

        # Clean up
        for t in adapter._write_tasks:
            t.cancel()
        await asyncio.sleep(0.01)


# ===================================================================
# Permission evaluation — paused / trust bypass / hard block
# ===================================================================


class TestEvaluatePermission:
    @pytest.mark.asyncio
    async def test_paused_session_denied(self) -> None:
        adapter = _make_adapter()
        adapter._paused_sessions.add("s1")
        from backend.services.permission_policy import PermissionRequest
        result = await adapter._evaluate_permission(
            "s1", "j1",
            PermissionRequest(kind="shell", workspace_path=""),
            tool_name="Bash",
        )
        assert result == PermissionDecision.deny

    @pytest.mark.asyncio
    async def test_trusted_job_allowed(self) -> None:
        mock_approval = MagicMock()
        mock_approval.is_trusted.return_value = True
        adapter = _make_adapter(approval_service=mock_approval)

        from backend.services.permission_policy import PermissionRequest
        result = await adapter._evaluate_permission(
            "s1", "j1",
            PermissionRequest(kind="read", workspace_path=""),
            tool_name="Read",
        )
        assert result == PermissionDecision.allow

    @pytest.mark.asyncio
    async def test_git_reset_hard_blocked(self) -> None:
        mock_approval = MagicMock()
        mock_approval.create_request = AsyncMock(return_value=MagicMock(id="a1"))
        mock_approval.wait_for_resolution = AsyncMock(return_value="denied")
        adapter = _make_adapter(approval_service=mock_approval)
        adapter._queues["s1"] = asyncio.Queue()

        from backend.services.permission_policy import PermissionRequest
        result = await adapter._evaluate_permission(
            "s1", "j1",
            PermissionRequest(kind="shell", workspace_path="", full_command_text="git reset --hard HEAD~1"),
            tool_name="Bash",
        )
        assert result == PermissionDecision.deny

    @pytest.mark.asyncio
    async def test_git_reset_hard_approved(self) -> None:
        mock_approval = MagicMock()
        mock_approval.create_request = AsyncMock(return_value=MagicMock(id="a1"))
        mock_approval.wait_for_resolution = AsyncMock(return_value="approved")
        adapter = _make_adapter(approval_service=mock_approval)
        adapter._queues["s1"] = asyncio.Queue()

        from backend.services.permission_policy import PermissionRequest
        result = await adapter._evaluate_permission(
            "s1", "j1",
            PermissionRequest(kind="shell", workspace_path="", full_command_text="git reset --hard HEAD~1"),
            tool_name="Bash",
        )
        assert result == PermissionDecision.allow
