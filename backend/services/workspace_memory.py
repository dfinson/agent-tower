"""Workspace memory — persistent cross-job knowledge per repository.

Memory is stored at ``~/.codeplane/memory/<slug>/`` with:

- ``decisions.md`` — active shared context (curated subset injected per job)
- ``wisdom.md``    — permanent truths (always included in curation input)
- ``inbox/``       — write buffer: one file per completed job, merged later
- ``archive.md``   — compacted old decisions (never loaded into prompts)

All files are plain markdown, human-editable.
"""

from __future__ import annotations

import fcntl
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from backend.config import get_codeplane_dir

if TYPE_CHECKING:
    from backend.services.memory_compacter import MemoryCompacter

log = structlog.get_logger()


def _repo_slug(repo_path: str) -> str:
    """Derive a unique filesystem-safe slug from a repo path.

    Uses the directory name plus a short hash of the full resolved path
    to avoid collisions between same-named repos at different locations.
    """
    resolved = str(Path(repo_path).resolve())
    name = Path(resolved).name
    h = hashlib.sha256(resolved.encode()).hexdigest()[:8]
    return f"{name}-{h}"


def _memory_dir(repo_path: str) -> Path:
    """Return the memory directory for a repo."""
    return get_codeplane_dir() / "memory" / _repo_slug(repo_path)


def _ensure_dir(repo_path: str) -> Path:
    """Create the memory directory if needed, return its path."""
    d = _memory_dir(repo_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "inbox").mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def load_workspace_memory(repo_path: str) -> str | None:
    """Read ``decisions.md`` + ``wisdom.md`` and return combined text.

    Returns ``None`` if no memory exists yet.
    """
    d = _memory_dir(repo_path)
    parts: list[str] = []

    wisdom = d / "wisdom.md"
    if wisdom.is_file():
        text = wisdom.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)

    decisions = d / "decisions.md"
    if decisions.is_file():
        text = decisions.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)

    return "\n\n".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Write (inbox)
# ---------------------------------------------------------------------------


def append_to_inbox(repo_path: str, job_id: str, entries: str) -> None:
    """Write extracted memory entries to ``inbox/<job_id>.md``."""
    entries = entries.strip()
    if not entries:
        return
    d = _ensure_dir(repo_path)
    inbox_file = d / "inbox" / f"{job_id}.md"
    inbox_file.write_text(entries + "\n", encoding="utf-8")
    log.info("workspace_memory.inbox_written", repo=_repo_slug(repo_path), job_id=job_id)


# ---------------------------------------------------------------------------
# Merge inbox → decisions (file-locked)
# ---------------------------------------------------------------------------


async def merge_inbox(repo_path: str, compacter: MemoryCompacter) -> int:
    """Move inbox entries into ``decisions.md`` and delete inbox files.

    Uses a file lock to prevent parallel jobs from corrupting decisions.md.
    Deduplicates: skips inbox content already present in decisions.

    Returns the number of inbox files merged.
    """
    d = _memory_dir(repo_path)
    inbox = d / "inbox"
    if not inbox.is_dir():
        return 0

    inbox_files = sorted(inbox.glob("*.md"))
    if not inbox_files:
        return 0

    d.mkdir(parents=True, exist_ok=True)
    decisions_path = d / "decisions.md"
    lock_path = d / ".merge.lock"

    # Acquire exclusive lock
    lock_path.touch(exist_ok=True)
    lock_fd = lock_path.open("w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Read existing decisions for dedup
        existing = ""
        if decisions_path.is_file():
            existing = decisions_path.read_text(encoding="utf-8")

        # Collect new entries, deduplicating
        new_entries: list[str] = []
        for f in inbox_files:
            text = f.read_text(encoding="utf-8").strip()
            if text and text not in existing:
                new_entries.append(text)

        if new_entries:
            combined = existing.rstrip() + "\n\n" + "\n\n".join(new_entries) + "\n"
            decisions_path.write_text(combined.lstrip(), encoding="utf-8")

        # Clean up inbox files regardless
        for f in inbox_files:
            f.unlink(missing_ok=True)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    merged_count = len(inbox_files)
    log.info(
        "workspace_memory.inbox_merged",
        repo=_repo_slug(repo_path),
        count=merged_count,
        new_entries=len(new_entries) if new_entries else 0,
    )

    # Auto-compact after merge
    await compact_decisions(repo_path, compacter)

    return merged_count


# ---------------------------------------------------------------------------
# Compact decisions → archive (LLM-summarized)
# ---------------------------------------------------------------------------

# 20 KB — derived from typical context-window budget for system prompts
# (~4K tokens at ~5 bytes/token).
_ARCHIVE_THRESHOLD_BYTES = 20 * 1024


async def compact_decisions(repo_path: str, compacter: MemoryCompacter) -> bool:
    """When ``decisions.md`` exceeds the threshold, use the LLM to summarize
    and move old content to ``archive.md``.

    The compacter distills decisions down to the most valuable entries.
    Returns ``True`` if compaction occurred.
    """
    d = _memory_dir(repo_path)
    decisions_path = d / "decisions.md"
    if not decisions_path.is_file():
        return False

    size = decisions_path.stat().st_size
    if size <= _ARCHIVE_THRESHOLD_BYTES:
        return False

    content = decisions_path.read_text(encoding="utf-8").strip()
    if not content:
        return False

    try:
        summarized = await compacter.compact(content)
    except Exception:
        log.warning("workspace_memory.compaction_failed", repo=_repo_slug(repo_path), exc_info=True)
        return False

    if not summarized or not summarized.strip():
        return False

    # Archive the original content
    archive_path = d / "archive.md"
    archive_existing = ""
    if archive_path.is_file():
        archive_existing = archive_path.read_text(encoding="utf-8")

    archive_combined = archive_existing.rstrip() + "\n\n" + content + "\n"
    archive_path.write_text(archive_combined.lstrip(), encoding="utf-8")

    # Replace decisions with the summarized version
    decisions_path.write_text(summarized.strip() + "\n", encoding="utf-8")

    log.info(
        "workspace_memory.compacted",
        repo=_repo_slug(repo_path),
        original_bytes=size,
        summarized_bytes=len(summarized.encode("utf-8")),
    )
    return True


# ---------------------------------------------------------------------------
# Direct read/write for API
# ---------------------------------------------------------------------------


def read_memory_text(repo_path: str) -> str:
    """Return the full memory text (decisions + wisdom) for the API."""
    return load_workspace_memory(repo_path) or ""


def write_decisions(repo_path: str, content: str) -> None:
    """Overwrite ``decisions.md`` with *content*."""
    d = _ensure_dir(repo_path)
    (d / "decisions.md").write_text(content, encoding="utf-8")
    log.info("workspace_memory.decisions_written", repo=_repo_slug(repo_path))


def write_wisdom(repo_path: str, content: str) -> None:
    """Overwrite ``wisdom.md`` with *content*."""
    d = _ensure_dir(repo_path)
    (d / "wisdom.md").write_text(content, encoding="utf-8")
    log.info("workspace_memory.wisdom_written", repo=_repo_slug(repo_path))


def format_entry(title: str, body: str) -> str:
    """Format a single memory entry as markdown."""
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"### {date}: {title}\n{body}"
