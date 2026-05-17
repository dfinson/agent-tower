"""Tests for ClaudeSessionStateWatcher."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from backend.config import CPLConfig
from backend.models.db import Base
from backend.models.domain import SessionEventKind
from backend.persistence.database import _set_sqlite_pragmas
from backend.services.watcher.claude import (
    _SESSION_FILE_RE,
    ClaudeSessionStateWatcher,
    _encode_cwd,
    _find_claude_pids_at_cwd,
    _is_claude_process_alive,
    _is_pid_alive,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def config() -> CPLConfig:
    return CPLConfig(repos=["/home/user/repos/myproject"])


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def runtime_service() -> MagicMock:
    svc = MagicMock()
    svc.register_external_session = AsyncMock()
    svc.feed_external_event = AsyncMock(return_value=None)
    svc.finalize_external_session = AsyncMock()
    return svc


@pytest.fixture
def git_service() -> AsyncMock:
    git = AsyncMock()
    git.get_current_branch = AsyncMock(return_value="main")
    git.rev_parse = AsyncMock(return_value="abc123")
    return git


@pytest.fixture
def watcher(
    db_session: async_sessionmaker[AsyncSession],
    config: CPLConfig,
    event_bus: AsyncMock,
    runtime_service: MagicMock,
    git_service: AsyncMock,
) -> ClaudeSessionStateWatcher:
    w = ClaudeSessionStateWatcher(
        event_bus=event_bus,
        runtime_service=runtime_service,
        session_factory=db_session,
        config=config,
        git_service=git_service,
    )
    # Prevent pipeline DB writes from hitting the in-memory engine during tests
    w._pipeline._schedule_write = lambda coro: coro.close()  # type: ignore[assignment]
    return w


# ---------------------------------------------------------------------------
# Unit tests: _encode_cwd
# ---------------------------------------------------------------------------


class TestEncodeCwd:
    def test_basic_path(self) -> None:
        assert _encode_cwd("/home/dave01/repos/project") == "-home-dave01-repos-project"

    def test_root(self) -> None:
        assert _encode_cwd("/") == "-"

    def test_nested_path(self) -> None:
        assert _encode_cwd("/a/b/c/d") == "-a-b-c-d"


# ---------------------------------------------------------------------------
# Unit tests: _SESSION_FILE_RE
# ---------------------------------------------------------------------------


class TestSessionFileRegex:
    def test_valid_uuid(self) -> None:
        assert _SESSION_FILE_RE.match("a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl")

    def test_invalid_no_extension(self) -> None:
        assert _SESSION_FILE_RE.match("a1b2c3d4-e5f6-7890-abcd-ef1234567890") is None

    def test_invalid_wrong_format(self) -> None:
        assert _SESSION_FILE_RE.match("not-a-uuid.jsonl") is None

    def test_invalid_uppercase(self) -> None:
        # Regex only matches lowercase hex
        assert _SESSION_FILE_RE.match("A1B2C3D4-E5F6-7890-ABCD-EF1234567890.jsonl") is None


# ---------------------------------------------------------------------------
# Unit tests: pending messages
# ---------------------------------------------------------------------------


class TestPendingMessages:
    def test_get_pending_messages_empty(self, watcher: ClaudeSessionStateWatcher) -> None:
        assert watcher.get_pending_messages("unknown-session") == []

    @pytest.mark.anyio
    async def test_send_and_get_messages(self, watcher: ClaudeSessionStateWatcher) -> None:
        # Simulate a tracked session
        watcher._session_to_job["session-123"] = "job-abc"
        watcher._job_to_session["job-abc"] = "session-123"

        await watcher.send_operator_message("job-abc", "Hello agent")
        await watcher.send_operator_message("job-abc", "Do this next")

        messages = watcher.get_pending_messages("session-123")
        assert messages == ["Hello agent", "Do this next"]

        # Messages should be drained
        assert watcher.get_pending_messages("session-123") == []

    @pytest.mark.anyio
    async def test_abort_queues_message(self, watcher: ClaudeSessionStateWatcher) -> None:
        watcher._session_to_job["session-456"] = "job-def"
        watcher._job_to_session["job-def"] = "session-456"

        await watcher.abort_session("job-def")

        messages = watcher.get_pending_messages("session-456")
        assert len(messages) == 1
        assert "abort" in messages[0].lower()


# ---------------------------------------------------------------------------
# Unit tests: settings hook installation
# ---------------------------------------------------------------------------


class TestHookInstallation:
    def test_install_creates_settings(self, watcher: ClaudeSessionStateWatcher, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        with patch("backend.services.watcher.claude._CLAUDE_SETTINGS_PATH", settings_path):
            watcher._install_stop_hook()

        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]
        assert any("hooks/claude" in url for url in settings["hooks"]["Stop"])

    def test_install_idempotent(self, watcher: ClaudeSessionStateWatcher, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        with patch("backend.services.watcher.claude._CLAUDE_SETTINGS_PATH", settings_path):
            watcher._install_stop_hook()
            watcher._install_stop_hook()

        settings = json.loads(settings_path.read_text())
        # Should only appear once
        assert len(settings["hooks"]["Stop"]) == 1

    def test_install_preserves_existing(self, watcher: ClaudeSessionStateWatcher, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        existing = {"permissions": {"allow": ["Read"]}, "hooks": {"Stop": ["http://other:9999/hook"]}}
        settings_path.write_text(json.dumps(existing))

        with patch("backend.services.watcher.claude._CLAUDE_SETTINGS_PATH", settings_path):
            watcher._install_stop_hook()

        settings = json.loads(settings_path.read_text())
        assert "http://other:9999/hook" in settings["hooks"]["Stop"]
        assert len(settings["hooks"]["Stop"]) == 2
        assert settings["permissions"] == {"allow": ["Read"]}


# ---------------------------------------------------------------------------
# Unit tests: JSONL event processing
# ---------------------------------------------------------------------------


class TestJsonlEventProcessing:
    @pytest.mark.anyio
    async def test_user_event_emits_transcript(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        watcher._session_to_job["sess-1"] = "job-1"
        watcher._job_to_session["job-1"] = "sess-1"

        raw = {
            "type": "user",
            "message": {"content": "Fix the bug in main.py"},
            "cwd": "/home/user/repos/myproject",
        }

        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert ended is False
        runtime_service.feed_external_event.assert_called()
        call_args = runtime_service.feed_external_event.call_args
        session_event = call_args[0][1]
        assert session_event.kind.value == "transcript"
        assert session_event.payload["role"] == "operator"
        assert "Fix the bug" in session_event.payload["content"]

    @pytest.mark.anyio
    async def test_assistant_text_emits_transcript(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        watcher._session_to_job["sess-1"] = "job-1"
        watcher._job_to_session["job-1"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "I'll fix the bug now."}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "model": "claude-sonnet-4-20250514",
            },
        }

        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert ended is False
        # Should have called process_event for the text transcript
        assert runtime_service.feed_external_event.called

    @pytest.mark.anyio
    async def test_assistant_tool_use_emits_tool_running(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        watcher._session_to_job["sess-1"] = "job-1"
        watcher._job_to_session["job-1"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "edit_file", "input": {"path": "main.py"}},
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20},
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert runtime_service.feed_external_event.called
        # Find the tool_running call
        for call in runtime_service.feed_external_event.call_args_list:
            evt = call[0][1]
            if evt.payload.get("role") == "tool_running":
                assert evt.payload["tool_name"] == "edit_file"
                break
        else:
            pytest.fail("No tool_running event emitted")

    @pytest.mark.anyio
    async def test_thinking_block_emits_reasoning(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        watcher._session_to_job["sess-1"] = "job-1"
        watcher._job_to_session["job-1"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": "Let me analyze the code...", "signature": "sig"}],
                "usage": {"input_tokens": 30, "output_tokens": 10},
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        for call in runtime_service.feed_external_event.call_args_list:
            evt = call[0][1]
            if evt.payload.get("role") == "reasoning":
                assert "analyze" in evt.payload["content"]
                break
        else:
            pytest.fail("No reasoning event emitted")

    @pytest.mark.anyio
    async def test_last_prompt_signals_end(self, watcher: ClaudeSessionStateWatcher) -> None:
        raw = {"type": "last-prompt"}
        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert ended is True

    @pytest.mark.anyio
    async def test_queue_operation_skipped(self, watcher: ClaudeSessionStateWatcher) -> None:
        raw = {"type": "queue-operation", "data": {}}
        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert ended is False

    @pytest.mark.anyio
    async def test_attachment_skipped(self, watcher: ClaudeSessionStateWatcher) -> None:
        raw = {"type": "attachment", "data": {}}
        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert ended is False


# ---------------------------------------------------------------------------
# Unit tests: SDK parse_message integration
#
# The watcher now uses the Claude SDK's parse_message() to convert raw JSONL
# dicts into typed objects (AssistantMessage, UserMessage, etc.) instead of
# manual dict.get() parsing. These tests ensure version bumps in the SDK
# that change field requirements or parsing behaviour are caught immediately.
# ---------------------------------------------------------------------------


class TestSdkParserIntegration:
    """Verify _handle_assistant_event and _handle_user_event work through parse_message."""

    @pytest.mark.anyio
    async def test_all_block_types_in_single_message(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """A realistic assistant message with text + thinking + tool_use + tool_result."""
        watcher._session_to_job["sess-1"] = "job-all"
        watcher._job_to_session["job-all"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "I need to check the file.", "signature": "sig1"},
                    {"type": "text", "text": "Let me look at that file."},
                    {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"path": "main.py"}},
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "file contents here"},
                ],
                "model": "claude-sonnet-4-20250514",
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-all")

        calls = runtime_service.feed_external_event.call_args_list
        payloads = [c[0][1].payload for c in calls]
        roles = [p.get("role") for p in payloads]

        assert "reasoning" in roles
        assert "agent" in roles
        assert "tool_running" in roles
        assert "tool_call" in roles

    @pytest.mark.anyio
    async def test_malformed_assistant_silently_skipped(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An assistant event that fails parse_message should log a warning, not crash."""
        watcher._session_to_job["sess-1"] = "job-bad"
        watcher._job_to_session["job-bad"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "hi"}],
                # missing "model" — parse_message will raise MessageParseError
            },
        }

        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-bad")
        assert ended is False
        runtime_service.feed_external_event.assert_not_called()
        captured = capsys.readouterr()
        assert "assistant_parse_failed" in captured.out

    @pytest.mark.anyio
    async def test_malformed_user_silently_skipped(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A user event missing 'message' should log a warning, not crash."""
        watcher._session_to_job["sess-1"] = "job-bad2"
        watcher._job_to_session["job-bad2"] = "sess-1"

        raw = {
            "type": "user",
            # missing "message" entirely
        }

        ended = await watcher._process_jsonl_event(raw, "sess-1", "job-bad2")
        assert ended is False
        runtime_service.feed_external_event.assert_not_called()
        captured = capsys.readouterr()
        assert "user_parse_failed" in captured.out

    @pytest.mark.anyio
    async def test_user_string_content(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """UserMessage with plain string content should emit operator transcript."""
        watcher._session_to_job["sess-1"] = "job-ustr"
        watcher._job_to_session["job-ustr"] = "sess-1"

        raw = {
            "type": "user",
            "message": {"content": "Fix the bug"},
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-ustr")
        call_args = runtime_service.feed_external_event.call_args
        evt = call_args[0][1]
        assert evt.payload["role"] == "operator"
        assert evt.payload["content"] == "Fix the bug"

    @pytest.mark.anyio
    async def test_user_block_list_content(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """UserMessage with a list of TextBlocks should join and emit."""
        watcher._session_to_job["sess-1"] = "job-ublk"
        watcher._job_to_session["job-ublk"] = "sess-1"

        raw = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "First part."},
                    {"type": "text", "text": "Second part."},
                ],
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-ublk")
        call_args = runtime_service.feed_external_event.call_args
        evt = call_args[0][1]
        assert "First part." in evt.payload["content"]
        assert "Second part." in evt.payload["content"]

    @pytest.mark.anyio
    async def test_tool_result_list_content_parsed(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """ToolResultBlock with list content should join TextBlocks into result text."""
        watcher._session_to_job["sess-1"] = "job-trl"
        watcher._job_to_session["job-trl"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "ls"}},
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": [
                            {"type": "text", "text": "file1.py"},
                            {"type": "text", "text": "file2.py"},
                        ],
                    },
                ],
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-trl")
        calls = runtime_service.feed_external_event.call_args_list
        # Find the tool_call event (result)
        for call in calls:
            evt = call[0][1]
            if evt.payload.get("role") == "tool_call":
                assert "file1.py" in evt.payload["tool_result"]
                assert "file2.py" in evt.payload["tool_result"]
                break
        else:
            pytest.fail("No tool_call event emitted")

    @pytest.mark.anyio
    async def test_tool_result_error_flag(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """ToolResultBlock with is_error=True should set tool_success=False."""
        watcher._session_to_job["sess-1"] = "job-err"
        watcher._job_to_session["job-err"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "tu_e", "name": "Bash", "input": {"command": "exit 1"}},
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_e",
                        "content": "command failed",
                        "is_error": True,
                    },
                ],
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-err")
        for call in runtime_service.feed_external_event.call_args_list:
            evt = call[0][1]
            if evt.payload.get("role") == "tool_call":
                assert evt.payload["tool_success"] is False
                break
        else:
            pytest.fail("No tool_call event emitted")

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_usage_extracted_even_when_blocks_malformed(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """Usage telemetry comes from raw dict, not parse_message, so it works even
        when content blocks fail to parse (e.g. missing model)."""
        watcher._session_to_job["sess-1"] = "job-usg"
        watcher._job_to_session["job-usg"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "hi"}],
                # No model → parse_message will raise, but usage should still be extracted
                "usage": {"input_tokens": 999, "output_tokens": 111},
            },
        }

        with patch.object(watcher._pipeline, "on_usage", new_callable=AsyncMock) as mock_usage:
            await watcher._process_jsonl_event(raw, "sess-1", "job-usg")

            # Usage should have been routed through pipeline despite parse failure
            mock_usage.assert_called_once()
            call_kwargs = mock_usage.call_args[1]
            assert call_kwargs["input_tokens"] == 999
            assert call_kwargs["output_tokens"] == 111

    @pytest.mark.anyio
    async def test_empty_text_block_not_emitted(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """Text blocks with only whitespace should be skipped."""
        watcher._session_to_job["sess-1"] = "job-wh"
        watcher._job_to_session["job-wh"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "   "}],
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-wh")
        runtime_service.feed_external_event.assert_not_called()

    @pytest.mark.anyio
    async def test_empty_thinking_block_not_emitted(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """Thinking blocks with only whitespace should be skipped."""
        watcher._session_to_job["sess-1"] = "job-et"
        watcher._job_to_session["job-et"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": "  \n  ", "signature": "sig"}],
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-et")
        runtime_service.feed_external_event.assert_not_called()

    @pytest.mark.anyio
    async def test_user_prompt_captured_on_first_message(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """First user message should trigger prompt capture."""
        watcher._session_to_job["sess-1"] = "job-pc"
        watcher._job_to_session["job-pc"] = "sess-1"

        raw = {
            "type": "user",
            "message": {"content": "Build a REST API"},
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-pc")
        assert "job-pc" in watcher._prompt_captured

    @pytest.mark.anyio
    async def test_user_cwd_captured(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """User event with cwd field should set worktree."""
        watcher._session_to_job["sess-1"] = "job-cwd"
        watcher._job_to_session["job-cwd"] = "sess-1"

        raw = {
            "type": "user",
            "message": {"content": "hello"},
            "cwd": "/home/user/repos/myproject",
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-cwd")
        assert watcher._job_worktrees.get("job-cwd") == "/home/user/repos/myproject"

    @pytest.mark.anyio
    async def test_tool_use_input_serialized(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """Tool input dict should be serialized to JSON string in the payload."""
        watcher._session_to_job["sess-1"] = "job-tin"
        watcher._job_to_session["job-tin"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "tu_s", "name": "Write", "input": {"path": "x.py", "data": "abc"}},
                ],
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-tin")
        for call in runtime_service.feed_external_event.call_args_list:
            evt = call[0][1]
            if evt.payload.get("role") == "tool_running":
                args = evt.payload.get("tool_args", "")
                assert "x.py" in args
                assert "abc" in args
                break
        else:
            pytest.fail("No tool_running event emitted")


# ---------------------------------------------------------------------------
# Unit tests: discovery scan
# ---------------------------------------------------------------------------


class TestDiscoveryScan:
    def test_scan_finds_matching_sessions(
        self,
        watcher: ClaudeSessionStateWatcher,
        tmp_path: Path,
    ) -> None:
        # Create a project directory matching the config repo
        encoded = _encode_cwd("/home/user/repos/myproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)

        # Create a valid session file
        session_file = project_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl"
        session_file.write_text("")

        with patch("backend.services.watcher.claude._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 1
        sid, path, repo = results[0]
        assert sid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert path == session_file
        assert repo == "/home/user/repos/myproject"

    def test_scan_ignores_non_uuid_files(
        self,
        watcher: ClaudeSessionStateWatcher,
        tmp_path: Path,
    ) -> None:
        encoded = _encode_cwd("/home/user/repos/myproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)

        # Non-UUID file
        (project_dir / "random-notes.jsonl").write_text("")

        with patch("backend.services.watcher.claude._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 0

    def test_scan_ignores_already_tracked(
        self,
        watcher: ClaudeSessionStateWatcher,
        tmp_path: Path,
    ) -> None:
        encoded = _encode_cwd("/home/user/repos/myproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)

        session_file = project_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl"
        session_file.write_text("")

        # Pre-mark as tracked
        watcher._tracked_sessions.add("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

        with patch("backend.services.watcher.claude._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 0

    def test_scan_ignores_unmanaged_repos(
        self,
        watcher: ClaudeSessionStateWatcher,
        tmp_path: Path,
    ) -> None:
        # Create project dir for a repo NOT in config
        encoded = _encode_cwd("/home/user/repos/otherproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)
        (project_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl").write_text("")

        with patch("backend.services.watcher.claude._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 0


# ---------------------------------------------------------------------------
# Unit tests: IngestService routing
# ---------------------------------------------------------------------------


class TestIngestServiceRouting:
    @pytest.mark.anyio
    async def test_send_message_routes_to_claude_watcher(
        self,
        db_session: async_sessionmaker[AsyncSession],
    ) -> None:
        from backend.models.domain import Job, JobSource, JobState
        from backend.persistence.job_repo import JobRepository
        from backend.services.events.ingest_service import IngestService

        # Create a claude_cli job via ORM
        async with db_session() as session:
            repo = JobRepository(session)
            job = Job(
                id="job-1",
                repo="/repo",
                prompt="test",
                state=JobState.running,
                source=JobSource.claude_cli,
                external_session_id="sess-1",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                sdk="claude",
                base_ref="HEAD",
                branch="main",
                worktree_path="/repo",
                session_id=None,
            )
            await repo.create(job)
            await session.commit()

        claude_watcher = AsyncMock()
        ingest = IngestService(
            session_factory=db_session,
            claude_watcher=claude_watcher,
        )

        await ingest.send_operator_message("job-1", "Hello")
        claude_watcher.send_operator_message.assert_called_once_with("job-1", "Hello")

    @pytest.mark.anyio
    async def test_abort_routes_to_claude_watcher(
        self,
        db_session: async_sessionmaker[AsyncSession],
    ) -> None:
        from backend.models.domain import Job, JobSource, JobState
        from backend.persistence.job_repo import JobRepository
        from backend.services.events.ingest_service import IngestService

        async with db_session() as session:
            repo = JobRepository(session)
            job = Job(
                id="job-2",
                repo="/repo",
                prompt="test",
                state=JobState.running,
                source=JobSource.claude_cli,
                external_session_id="sess-2",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                sdk="claude",
                base_ref="HEAD",
                branch="main",
                worktree_path="/repo",
                session_id=None,
            )
            await repo.create(job)
            await session.commit()

        claude_watcher = AsyncMock()
        ingest = IngestService(
            session_factory=db_session,
            claude_watcher=claude_watcher,
        )

        await ingest.abort_session("job-2")
        claude_watcher.abort_session.assert_called_once_with("job-2")


# ---------------------------------------------------------------------------
# Unit tests: double finalization guard (RT-4)
# ---------------------------------------------------------------------------


class TestDoubleFinalizationGuard:
    @pytest.mark.anyio
    async def test_finalize_only_runs_once(
        self,
        watcher: ClaudeSessionStateWatcher,
        db_session: async_sessionmaker[AsyncSession],
        event_bus: AsyncMock,
        runtime_service: MagicMock,
    ) -> None:
        """Second call to _finalize_session should be a no-op."""
        from backend.models.domain import Job, JobSource, JobState
        from backend.persistence.job_repo import JobRepository

        async with db_session() as session:
            repo = JobRepository(session)
            job = Job(
                id="job-fin",
                repo="/repo",
                prompt="test",
                state=JobState.running,
                source=JobSource.claude_cli,
                external_session_id="sess-fin",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                sdk="claude",
                base_ref="HEAD",
                branch="main",
                worktree_path="/repo",
                session_id=None,
            )
            await repo.create(job)
            await session.commit()

        watcher._session_to_job["sess-fin"] = "job-fin"
        watcher._job_to_session["job-fin"] = "sess-fin"

        # First call should succeed
        await watcher._finalize_session("job-fin")
        assert event_bus.publish.call_count >= 1

        # Second call should be no-op (guard prevents re-entry)
        call_count_before = event_bus.publish.call_count
        await watcher._finalize_session("job-fin")
        assert event_bus.publish.call_count == call_count_before


# ---------------------------------------------------------------------------
# Unit tests: session cleanup allows re-discovery (RT-10)
# ---------------------------------------------------------------------------


class TestSessionCleanupReDiscovery:
    @pytest.mark.anyio
    async def test_finalize_removes_from_tracked(
        self,
        watcher: ClaudeSessionStateWatcher,
        db_session: async_sessionmaker[AsyncSession],
    ) -> None:
        """After finalization, session_id should be removed from _tracked_sessions."""
        from backend.models.domain import Job, JobSource, JobState
        from backend.persistence.job_repo import JobRepository

        async with db_session() as session:
            repo = JobRepository(session)
            job = Job(
                id="job-re",
                repo="/repo",
                prompt="test",
                state=JobState.running,
                source=JobSource.claude_cli,
                external_session_id="sess-re",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                sdk="claude",
                base_ref="HEAD",
                branch="main",
                worktree_path="/repo",
                session_id=None,
            )
            await repo.create(job)
            await session.commit()

        watcher._tracked_sessions.add("sess-re")
        watcher._session_to_job["sess-re"] = "job-re"
        watcher._job_to_session["job-re"] = "sess-re"

        await watcher._finalize_session("job-re")

        # Session should be removed from tracked set
        assert "sess-re" not in watcher._tracked_sessions


# ---------------------------------------------------------------------------
# Unit tests: liveness check with cwd (RT-1)
# ---------------------------------------------------------------------------


class TestLivenessCheck:
    def test_liveness_returns_false_when_no_proc(self) -> None:
        """On real system with no matching claude process, should return False."""
        result = _is_claude_process_alive("nonexistent-session-id", "/tmp/nonexistent")
        assert result is False

    def test_liveness_with_none_repo_path(self) -> None:
        """Should not crash when repo_path is None. Returns True if any claude process."""
        # This is a smoke test — behavior depends on whether claude is running.
        # Main goal: no exception raised.
        result = _is_claude_process_alive("nonexistent-session-id", None)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Unit tests: cost calculation (RT-7)
# ---------------------------------------------------------------------------


class TestCostCalculation:
    def test_compute_cost_known_model(self) -> None:
        from backend.services.analytics.model_pricing import ModelPricingService

        svc = ModelPricingService(cache_path=Path("/tmp/nonexistent-pricing-cache.json"))
        # Load bundled pricing data synchronously for test
        bundled = svc._read_bundled()
        assert bundled is not None
        svc._pricing = bundled

        cost = svc.compute_cost(
            "claude-sonnet-4-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
        assert cost > 0

    def test_compute_cost_unknown_model(self) -> None:
        from backend.services.analytics.model_pricing import ModelPricingService

        svc = ModelPricingService(cache_path=Path("/tmp/nonexistent-pricing-cache.json"))
        svc._pricing = {"known-model": {"input": 1.0, "output": 2.0}}

        cost = svc.compute_cost(
            "totally-fake-model-xyz",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=100,
            cache_write_tokens=50,
        )
        assert cost == 0.0

    def test_compute_cost_includes_cache(self) -> None:
        from backend.services.analytics.model_pricing import ModelPricingService

        svc = ModelPricingService(cache_path=Path("/tmp/nonexistent-pricing-cache.json"))
        bundled = svc._read_bundled()
        assert bundled is not None
        svc._pricing = bundled

        cost_no_cache = svc.compute_cost(
            "claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
        cost_with_cache = svc.compute_cost(
            "claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=5000,
            cache_write_tokens=2000,
        )
        assert cost_with_cache > cost_no_cache

    @pytest.mark.anyio
    async def test_telemetry_includes_cost(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """_process_usage_telemetry should route cost through pipeline.on_usage."""
        from backend.services.analytics.model_pricing import ModelPricingService

        # Inject a pricing service with bundled data
        pricing_svc = ModelPricingService(cache_path=Path("/tmp/nonexistent-pricing-cache.json"))
        bundled = pricing_svc._read_bundled()
        assert bundled is not None
        pricing_svc._pricing = bundled
        watcher._model_pricing = pricing_svc

        watcher._session_to_job["sess-1"] = "job-cost"
        watcher._job_to_session["job-cost"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Done."}],
                "usage": {
                    "input_tokens": 10000,
                    "output_tokens": 5000,
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 500,
                },
                "model": "claude-sonnet-4-20250514",
            },
        }

        with patch.object(watcher._pipeline, "on_usage", new_callable=AsyncMock) as mock_usage:
            await watcher._process_jsonl_event(raw, "sess-1", "job-cost")

            # Check that pipeline received cost > 0
            mock_usage.assert_called_once()
            call_kwargs = mock_usage.call_args[1]
            assert call_kwargs["cost_usd"] > 0
            assert call_kwargs["model"] == "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Unit tests: file_changed emission on file-write tools (RT-9)
# ---------------------------------------------------------------------------


class TestFileChangedEmission:
    @pytest.mark.anyio
    async def test_file_write_tool_emits_file_changed(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """tool_use with a file_write tool should emit file_changed event."""
        watcher._session_to_job["sess-1"] = "job-fc"
        watcher._job_to_session["job-fc"] = "sess-1"
        watcher._job_worktrees["job-fc"] = "/repo"
        watcher._job_base_refs["job-fc"] = "abc123"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_fc",
                        "name": "edit_file",
                        "input": {"path": "src/main.py", "content": "..."},
                    },
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20},
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-fc")

        # Should have emitted: tool_running + file_changed
        calls = runtime_service.feed_external_event.call_args_list
        kinds = [c[0][1].kind for c in calls]
        assert SessionEventKind.file_changed in kinds

    @pytest.mark.anyio
    async def test_non_write_tool_no_file_changed(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """tool_use with a read tool should NOT emit file_changed."""
        watcher._session_to_job["sess-1"] = "job-nfc"
        watcher._job_to_session["job-nfc"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_nfc",
                        "name": "read_file",
                        "input": {"path": "src/main.py"},
                    },
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20},
                "model": "claude-sonnet-4-20250514",
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-nfc")

        calls = runtime_service.feed_external_event.call_args_list
        kinds = [c[0][1].kind for c in calls]
        assert SessionEventKind.file_changed not in kinds


# ---------------------------------------------------------------------------
# Unit tests: PID-based liveness (RT2-1, RT2-2)
# ---------------------------------------------------------------------------


class TestPidLiveness:
    def test_is_pid_alive_returns_false_for_nonexistent_pid(self) -> None:
        """A PID that doesn't exist should return False."""
        assert _is_pid_alive(999999999) is False

    def test_find_claude_pids_at_nonexistent_cwd(self) -> None:
        """No claude processes should be at a nonexistent path."""
        pids = _find_claude_pids_at_cwd("/tmp/nonexistent-xyzzy-12345")
        assert pids == []

    def test_find_claude_pids_excludes_claimed(self) -> None:
        """Exclude set should filter out already-claimed PIDs."""
        # Even if by some miracle there's a match, exclude_pids filters it
        pids = _find_claude_pids_at_cwd(
            "/tmp/nonexistent-xyzzy-12345",
            exclude_pids=frozenset({1, 2, 3}),
        )
        assert pids == []

    @pytest.mark.anyio
    async def test_session_pid_cached_on_attach(
        self,
        watcher: ClaudeSessionStateWatcher,
    ) -> None:
        """_attach_session should attempt to cache a PID for the session."""
        session_id = "test-pid-session"
        jsonl_path = Path("/tmp/fake.jsonl")
        repo_path = "/tmp/nonexistent-repo-xyz"

        watcher._tracked_sessions.add(session_id)
        with patch.object(watcher, "_create_job", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = None  # Job creation fails → no PID caching
            await watcher._attach_session(session_id, jsonl_path, repo_path)

        # session_id not in _session_pids because job creation returned None
        assert session_id not in watcher._session_pids

    @pytest.mark.anyio
    async def test_session_pid_cleaned_on_finalize(
        self,
        watcher: ClaudeSessionStateWatcher,
        runtime_service: MagicMock,
    ) -> None:
        """_finalize_session should remove the cached PID."""
        watcher._session_to_job["sess-pid"] = "job-pid"
        watcher._job_to_session["job-pid"] = "sess-pid"
        watcher._session_pids["sess-pid"] = 12345
        watcher._job_worktrees["job-pid"] = "/tmp/repo"

        # Mock the DB update so we don't need a real Job row
        with patch("backend.persistence.job_repo.JobRepository.update_state", new_callable=AsyncMock):
            await watcher._finalize_session("job-pid")

        assert "sess-pid" not in watcher._session_pids


# ---------------------------------------------------------------------------
# Unit tests: pricing mtime reload (RT2-3)
# ---------------------------------------------------------------------------


class TestPricingReload:
    def test_pricing_cache_read_write(self, tmp_path: Path) -> None:
        """ModelPricingService should write and read cache files correctly."""
        from backend.services.analytics.model_pricing import ModelPricingService

        cache_path = tmp_path / "pricing_cache.json"
        svc = ModelPricingService(cache_path=cache_path)

        # Write pricing to cache
        pricing_data = {"model-a": {"input": 1.0, "output": 2.0}}
        svc._write_cache(pricing_data)
        assert cache_path.exists()

        # Read it back
        result = svc._read_cache()
        assert result is not None
        assert "model-a" in result
        assert result["model-a"]["input"] == 1.0

    def test_pricing_fallback_to_bundled(self, tmp_path: Path) -> None:
        """When cache doesn't exist, _read_bundled returns bundled data."""
        from backend.services.analytics.model_pricing import ModelPricingService

        svc = ModelPricingService(cache_path=tmp_path / "nonexistent.json")
        bundled = svc._read_bundled()
        assert bundled is not None
        assert len(bundled) > 0

    def test_pricing_normalize_key(self) -> None:
        """Normalized model key lookup should work."""
        from backend.services.analytics.model_pricing import ModelPricingService

        svc = ModelPricingService(cache_path=Path("/tmp/nonexistent.json"))
        svc._pricing = {"claude-sonnet-4": {"input": 3.0, "output": 15.0}}

        # Exact match
        assert svc.get("claude-sonnet-4") is not None
        # Normalized match
        assert svc.get("Claude_Sonnet_4") is not None
        # No match
        assert svc.get("totally-fake") is None
