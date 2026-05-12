"""Unit tests for workspace memory service."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.workspace_memory import (
    _repo_slug,
    append_to_inbox,
    compact_decisions,
    format_entry,
    load_workspace_memory,
    merge_inbox,
    read_memory_text,
    write_decisions,
    write_wisdom,
    _ARCHIVE_THRESHOLD_BYTES,
)


@pytest.fixture()
def memory_root(tmp_path: Path) -> Path:
    """Create a temp codeplane dir and patch get_codeplane_dir."""
    codeplane_dir = tmp_path / ".codeplane"
    codeplane_dir.mkdir()
    with patch("backend.services.workspace_memory.get_codeplane_dir", return_value=codeplane_dir):
        yield tmp_path


@pytest.fixture()
def repo_path(memory_root: Path) -> str:
    """Create a fake repo directory."""
    repo = memory_root / "my-project"
    repo.mkdir()
    return str(repo)


@pytest.fixture()
def mock_compacter() -> AsyncMock:
    """Create a mock MemoryCompacter that returns condensed text."""
    compacter = AsyncMock()
    compacter.compact.return_value = "### 2026-05-12: Condensed\nSummarized content."
    return compacter


class TestRepoSlug:
    def test_includes_hash(self) -> None:
        slug = _repo_slug("/home/user/repos/my-project")
        assert slug.startswith("my-project-")
        assert len(slug) == len("my-project-") + 8  # name + dash + 8-char hash

    def test_different_paths_different_slugs(self) -> None:
        slug1 = _repo_slug("/home/user/repos/my-project")
        slug2 = _repo_slug("/opt/repos/my-project")
        assert slug1 != slug2

    def test_same_path_same_slug(self) -> None:
        slug1 = _repo_slug("/home/user/repos/my-project")
        slug2 = _repo_slug("/home/user/repos/my-project")
        assert slug1 == slug2


class TestLoadWorkspaceMemory:
    def test_no_memory_dir(self, repo_path: str) -> None:
        assert load_workspace_memory(repo_path) is None

    def test_empty_files(self, repo_path: str, memory_root: Path) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "decisions.md").write_text("")
        assert load_workspace_memory(repo_path) is None

    def test_decisions_only(self, repo_path: str, memory_root: Path) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "decisions.md").write_text("### 2026-05-12: Test\nDecision body.")
        result = load_workspace_memory(repo_path)
        assert result is not None
        assert "Decision body" in result

    def test_wisdom_and_decisions(self, repo_path: str, memory_root: Path) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "wisdom.md").write_text("Always use uv, never pip.")
        (mem_dir / "decisions.md").write_text("### 2026-05-12: Test\nBody.")
        result = load_workspace_memory(repo_path)
        assert result is not None
        assert "uv" in result
        assert "Test" in result
        # Wisdom comes first
        assert result.index("uv") < result.index("Test")


class TestInbox:
    @pytest.mark.asyncio
    async def test_append_and_merge(self, repo_path: str, memory_root: Path, mock_compacter: AsyncMock) -> None:
        append_to_inbox(repo_path, "fix-login", "### 2026-05-12: Auth\nUse JWT.")
        append_to_inbox(repo_path, "add-tests", "### 2026-05-12: Tests\nUse pytest.")

        # Verify inbox files exist
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        inbox = mem_dir / "inbox"
        assert (inbox / "fix-login.md").is_file()
        assert (inbox / "add-tests.md").is_file()

        # Merge
        count = await merge_inbox(repo_path, mock_compacter)
        assert count == 2

        # Inbox should be empty
        assert list(inbox.glob("*.md")) == []

        # Decisions should contain both entries
        decisions = (mem_dir / "decisions.md").read_text()
        assert "Auth" in decisions
        assert "Tests" in decisions

    def test_append_empty_is_noop(self, repo_path: str, memory_root: Path) -> None:
        append_to_inbox(repo_path, "empty-job", "   ")
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        inbox = mem_dir / "inbox"
        assert not (inbox / "empty-job.md").exists()

    @pytest.mark.asyncio
    async def test_merge_no_inbox(self, repo_path: str, mock_compacter: AsyncMock) -> None:
        assert await merge_inbox(repo_path, mock_compacter) == 0

    @pytest.mark.asyncio
    async def test_merge_appends_to_existing(self, repo_path: str, memory_root: Path, mock_compacter: AsyncMock) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "inbox").mkdir()
        (mem_dir / "decisions.md").write_text("### 2026-05-10: Existing\nOld entry.\n")
        (mem_dir / "inbox" / "new-job.md").write_text("### 2026-05-12: New\nNew entry.")

        await merge_inbox(repo_path, mock_compacter)
        decisions = (mem_dir / "decisions.md").read_text()
        assert "Existing" in decisions
        assert "New" in decisions

    @pytest.mark.asyncio
    async def test_merge_deduplicates(self, repo_path: str, memory_root: Path, mock_compacter: AsyncMock) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "inbox").mkdir()
        existing_text = "### 2026-05-10: Existing\nOld entry."
        (mem_dir / "decisions.md").write_text(existing_text + "\n")
        # Inbox contains same text as existing decisions
        (mem_dir / "inbox" / "dup-job.md").write_text(existing_text)

        await merge_inbox(repo_path, mock_compacter)
        decisions = (mem_dir / "decisions.md").read_text()
        # Should only appear once
        assert decisions.count("Existing") == 1


class TestCompaction:
    @pytest.mark.asyncio
    async def test_no_compaction_under_threshold(self, repo_path: str, memory_root: Path, mock_compacter: AsyncMock) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "decisions.md").write_text("### 2026-05-12: Small\nTiny entry.")
        assert await compact_decisions(repo_path, mock_compacter) is False

    @pytest.mark.asyncio
    async def test_compaction_over_threshold(self, repo_path: str, memory_root: Path, mock_compacter: AsyncMock) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)

        # Create content that exceeds threshold
        content = "x" * (_ARCHIVE_THRESHOLD_BYTES + 1000)
        (mem_dir / "decisions.md").write_text(content)

        # Compact
        result = await compact_decisions(repo_path, mock_compacter)
        assert result is True

        # Compacter should have been called
        mock_compacter.compact.assert_called_once()

        # Archive should contain original content
        archive = (mem_dir / "archive.md").read_text()
        assert "x" * 100 in archive

        # Decisions should contain the summarized content
        remaining = (mem_dir / "decisions.md").read_text()
        assert "Condensed" in remaining

    @pytest.mark.asyncio
    async def test_compaction_failure_is_safe(self, repo_path: str, memory_root: Path) -> None:
        """When the compacter fails, decisions.md is unchanged."""
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)

        content = "x" * (_ARCHIVE_THRESHOLD_BYTES + 1000)
        (mem_dir / "decisions.md").write_text(content)

        failing_compacter = AsyncMock()
        failing_compacter.compact.side_effect = TimeoutError("LLM timeout")

        result = await compact_decisions(repo_path, failing_compacter)
        assert result is False

        # Original content should be unchanged
        assert (mem_dir / "decisions.md").read_text() == content


class TestDirectReadWrite:
    def test_write_and_read_decisions(self, repo_path: str) -> None:
        write_decisions(repo_path, "### 2026-05-12: Test\nBody.")
        assert "Test" in read_memory_text(repo_path)

    def test_write_and_read_wisdom(self, repo_path: str) -> None:
        write_wisdom(repo_path, "Always use uv.")
        assert "uv" in read_memory_text(repo_path)


class TestFormatEntry:
    def test_format(self) -> None:
        entry = format_entry("Use structlog", "Always use structlog with bound context.")
        assert "### " in entry
        assert "Use structlog" in entry
        assert "bound context" in entry
