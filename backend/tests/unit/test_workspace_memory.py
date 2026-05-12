"""Unit tests for workspace memory service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.memory_extractor import _EXTRACTOR_CHUNK_CHARS, _split_decisions
from backend.services.workspace_memory import (
    _ARCHIVE_THRESHOLD_BYTES,
    _cap_archive,
    _repo_slug,
    append_to_inbox,
    compact_decisions,
    format_entry,
    load_workspace_memory,
    merge_inbox,
    read_memory_text,
    write_decisions,
    write_wisdom,
)

if TYPE_CHECKING:
    from pathlib import Path


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

    def test_append_is_atomic(self, repo_path: str, memory_root: Path) -> None:
        """Inbox files are written atomically — no .tmp files left behind."""
        append_to_inbox(repo_path, "atomic-job", "### 2026-05-12: Test\nEntry.")
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        inbox = mem_dir / "inbox"
        # Only the final file exists, no .tmp remnants
        assert (inbox / "atomic-job.md").is_file()
        assert list(inbox.glob("*.tmp")) == []

    @pytest.mark.asyncio
    async def test_merge_no_inbox(self, repo_path: str, mock_compacter: AsyncMock) -> None:
        assert await merge_inbox(repo_path, mock_compacter) == 0

    @pytest.mark.asyncio
    async def test_merge_appends_to_existing(
        self,
        repo_path: str,
        memory_root: Path,
        mock_compacter: AsyncMock,
    ) -> None:
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
    async def test_merge_appends_all_without_dedup(
        self,
        repo_path: str,
        memory_root: Path,
        mock_compacter: AsyncMock,
    ) -> None:
        """Merge appends unconditionally — LLM handles dedup during compaction."""
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "inbox").mkdir()
        existing_text = "### 2026-05-10: Existing\nOld entry."
        (mem_dir / "decisions.md").write_text(existing_text + "\n")
        # Inbox contains same text — it still gets appended (dedup is LLM's job)
        (mem_dir / "inbox" / "dup-job.md").write_text(existing_text)

        await merge_inbox(repo_path, mock_compacter)
        decisions = (mem_dir / "decisions.md").read_text()
        # Both instances present — LLM will deduplicate during compaction
        assert decisions.count("Existing") == 2


class TestCompaction:
    @pytest.mark.asyncio
    async def test_no_compaction_under_threshold(
        self,
        repo_path: str,
        memory_root: Path,
        mock_compacter: AsyncMock,
    ) -> None:
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)
        (mem_dir / "decisions.md").write_text("### 2026-05-12: Small\nTiny entry.")
        assert await compact_decisions(repo_path, mock_compacter) is False

    @pytest.mark.asyncio
    async def test_compaction_over_threshold(
        self,
        repo_path: str,
        memory_root: Path,
        mock_compacter: AsyncMock,
    ) -> None:
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

    @pytest.mark.asyncio
    async def test_compaction_cas_fails_on_concurrent_modify(self, repo_path: str, memory_root: Path) -> None:
        """If decisions.md changes during LLM call, compaction aborts."""
        slug = _repo_slug(repo_path)
        mem_dir = memory_root / ".codeplane" / "memory" / slug
        mem_dir.mkdir(parents=True)

        content = "x" * (_ARCHIVE_THRESHOLD_BYTES + 1000)
        (mem_dir / "decisions.md").write_text(content)

        async def modify_during_compact(text: str, **kwargs) -> str:
            # Simulate concurrent modification
            (mem_dir / "decisions.md").write_text("MODIFIED BY ANOTHER JOB")
            return "### Summarized\nContent."

        compacter = AsyncMock()
        compacter.compact.side_effect = modify_during_compact

        result = await compact_decisions(repo_path, compacter)
        assert result is False

        # The concurrent modification should remain
        assert (mem_dir / "decisions.md").read_text() == "MODIFIED BY ANOTHER JOB"


class TestArchiveCap:
    def test_under_cap(self, tmp_path: Path) -> None:
        archive = tmp_path / "archive.md"
        _cap_archive(archive, "small content", 1024)
        assert archive.read_text() == "small content"

    def test_over_cap_trims_oldest(self, tmp_path: Path) -> None:
        archive = tmp_path / "archive.md"
        paragraphs = [f"Paragraph {i}: {'x' * 100}" for i in range(20)]
        content = "\n\n".join(paragraphs)
        # Cap at 500 bytes — should trim from front
        _cap_archive(archive, content, 500)
        result = archive.read_text()
        assert len(result.encode("utf-8")) <= 500
        # Last paragraph should survive
        assert "Paragraph 19" in result
        # First paragraph should be gone
        assert "Paragraph 0" not in result


class TestExtractorChunking:
    def test_small_text_no_split(self) -> None:
        text = "- Decision A\n- Decision B"
        chunks = _split_decisions(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_large_text_splits_on_lines(self) -> None:
        # Create text larger than chunk size
        lines = [f"- Decision {i}: {'x' * 200}" for i in range(200)]
        text = "\n".join(lines)
        assert len(text) > _EXTRACTOR_CHUNK_CHARS

        chunks = _split_decisions(text)
        assert len(chunks) > 1
        # Each chunk should be under the limit (or a single line that exceeds it)
        for chunk in chunks[:-1]:
            assert len(chunk) <= _EXTRACTOR_CHUNK_CHARS + 250  # line boundary tolerance
        # All content preserved
        reassembled = "\n".join(chunks)
        assert reassembled == text


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
