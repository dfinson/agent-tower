"""Tests for ClaudeSessionStateWatcher."""

from __future__ import annotations

import json
import os
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
from backend.persistence.database import _set_sqlite_pragmas
from backend.services.claude_session_watcher import (
    ClaudeSessionStateWatcher,
    _encode_cwd,
    _is_claude_process_alive,
    _SESSION_FILE_RE,
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
def event_processor() -> MagicMock:
    proc = MagicMock()
    proc.process_event = AsyncMock()
    proc.on_job_terminal = AsyncMock()
    proc.register_worktree = MagicMock()
    return proc


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
    event_processor: MagicMock,
    git_service: AsyncMock,
) -> ClaudeSessionStateWatcher:
    return ClaudeSessionStateWatcher(
        event_bus=event_bus,
        event_processor=event_processor,
        session_factory=db_session,
        config=config,
        git_service=git_service,
    )


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
        with patch("backend.services.claude_session_watcher._CLAUDE_SETTINGS_PATH", settings_path):
            watcher._install_stop_hook()

        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]
        assert any("hooks/claude" in url for url in settings["hooks"]["Stop"])

    def test_install_idempotent(self, watcher: ClaudeSessionStateWatcher, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        with patch("backend.services.claude_session_watcher._CLAUDE_SETTINGS_PATH", settings_path):
            watcher._install_stop_hook()
            watcher._install_stop_hook()

        settings = json.loads(settings_path.read_text())
        # Should only appear once
        assert len(settings["hooks"]["Stop"]) == 1

    def test_install_preserves_existing(self, watcher: ClaudeSessionStateWatcher, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        existing = {"permissions": {"allow": ["Read"]}, "hooks": {"Stop": ["http://other:9999/hook"]}}
        settings_path.write_text(json.dumps(existing))

        with patch("backend.services.claude_session_watcher._CLAUDE_SETTINGS_PATH", settings_path):
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
        self, watcher: ClaudeSessionStateWatcher, event_processor: MagicMock,
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
        event_processor.process_event.assert_called()
        call_args = event_processor.process_event.call_args
        session_event = call_args[0][1]
        assert session_event.kind.value == "transcript"
        assert session_event.payload["role"] == "operator"
        assert "Fix the bug" in session_event.payload["content"]

    @pytest.mark.anyio
    async def test_assistant_text_emits_transcript(
        self, watcher: ClaudeSessionStateWatcher, event_processor: MagicMock,
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
        assert event_processor.process_event.called

    @pytest.mark.anyio
    async def test_assistant_tool_use_emits_tool_running(
        self, watcher: ClaudeSessionStateWatcher, event_processor: MagicMock,
    ) -> None:
        watcher._session_to_job["sess-1"] = "job-1"
        watcher._job_to_session["job-1"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "edit_file", "input": {"path": "main.py"}},
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20},
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        assert event_processor.process_event.called
        # Find the tool_running call
        for call in event_processor.process_event.call_args_list:
            evt = call[0][1]
            if evt.payload.get("role") == "tool_running":
                assert evt.payload["tool_name"] == "edit_file"
                break
        else:
            pytest.fail("No tool_running event emitted")

    @pytest.mark.anyio
    async def test_thinking_block_emits_reasoning(
        self, watcher: ClaudeSessionStateWatcher, event_processor: MagicMock,
    ) -> None:
        watcher._session_to_job["sess-1"] = "job-1"
        watcher._job_to_session["job-1"] = "sess-1"

        raw = {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": "Let me analyze the code..."}],
                "usage": {"input_tokens": 30, "output_tokens": 10},
            },
        }

        await watcher._process_jsonl_event(raw, "sess-1", "job-1")
        for call in event_processor.process_event.call_args_list:
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
# Unit tests: discovery scan
# ---------------------------------------------------------------------------


class TestDiscoveryScan:
    def test_scan_finds_matching_sessions(
        self, watcher: ClaudeSessionStateWatcher, tmp_path: Path,
    ) -> None:
        # Create a project directory matching the config repo
        encoded = _encode_cwd("/home/user/repos/myproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)

        # Create a valid session file
        session_file = project_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl"
        session_file.write_text("")

        with patch("backend.services.claude_session_watcher._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 1
        sid, path, repo = results[0]
        assert sid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert path == session_file
        assert repo == "/home/user/repos/myproject"

    def test_scan_ignores_non_uuid_files(
        self, watcher: ClaudeSessionStateWatcher, tmp_path: Path,
    ) -> None:
        encoded = _encode_cwd("/home/user/repos/myproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)

        # Non-UUID file
        (project_dir / "random-notes.jsonl").write_text("")

        with patch("backend.services.claude_session_watcher._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 0

    def test_scan_ignores_already_tracked(
        self, watcher: ClaudeSessionStateWatcher, tmp_path: Path,
    ) -> None:
        encoded = _encode_cwd("/home/user/repos/myproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)

        session_file = project_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl"
        session_file.write_text("")

        # Pre-mark as tracked
        watcher._tracked_sessions.add("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

        with patch("backend.services.claude_session_watcher._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 0

    def test_scan_ignores_unmanaged_repos(
        self, watcher: ClaudeSessionStateWatcher, tmp_path: Path,
    ) -> None:
        # Create project dir for a repo NOT in config
        encoded = _encode_cwd("/home/user/repos/otherproject")
        project_dir = tmp_path / encoded
        project_dir.mkdir(parents=True)
        (project_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl").write_text("")

        with patch("backend.services.claude_session_watcher._CLAUDE_PROJECTS_DIR", tmp_path):
            results = watcher._scan_for_new_sessions()

        assert len(results) == 0


# ---------------------------------------------------------------------------
# Unit tests: IngestService routing
# ---------------------------------------------------------------------------


class TestIngestServiceRouting:
    @pytest.mark.anyio
    async def test_send_message_routes_to_claude_watcher(
        self, db_session: async_sessionmaker[AsyncSession],
    ) -> None:
        from backend.models.domain import Job, JobSource, JobState
        from backend.persistence.job_repo import JobRepository
        from backend.services.ingest_service import IngestService

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
        self, db_session: async_sessionmaker[AsyncSession],
    ) -> None:
        from backend.models.domain import Job, JobSource, JobState
        from backend.persistence.job_repo import JobRepository
        from backend.services.ingest_service import IngestService

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
