"""Workspace memory — persistent cross-job knowledge per repository.

Memory is stored at ``~/.codeplane/memory/<slug>/`` with:

- ``decisions.md`` — active shared context (curated subset injected per job)
- ``wisdom.md``    — permanent truths (always included in curation input)
- ``inbox/``       — write buffer: one file per completed job, merged later
- ``archive.md``   — compacted old decisions (never loaded into prompts)

All files are plain markdown, human-editable.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import tempfile
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
# Write (inbox) — atomic via temp + rename
# ---------------------------------------------------------------------------


def append_to_inbox(repo_path: str, job_id: str, entries: str) -> None:
    """Write extracted memory entries to ``inbox/<job_id>.md``.

    Uses write-to-temp + os.rename for atomicity — a crash mid-write
    leaves no partial file in the inbox.
    """
    entries = entries.strip()
    if not entries:
        return
    d = _ensure_dir(repo_path)
    inbox_dir = d / "inbox"
    target = inbox_dir / f"{job_id}.md"

    # Write to temp in same dir (same filesystem → rename is atomic on POSIX)
    fd, tmp_path = tempfile.mkstemp(dir=str(inbox_dir), suffix=".tmp")
    try:
        os.write(fd, (entries + "\n").encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.rename(tmp_path, str(target))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    log.info("workspace_memory.inbox_written", repo=_repo_slug(repo_path), job_id=job_id)


# ---------------------------------------------------------------------------
# File locking helper
# ---------------------------------------------------------------------------


def _locked_merge(repo_path: str) -> tuple[int, int]:
    """Synchronous file-locked merge of inbox → decisions.md.

    Appends all inbox entries unconditionally — deduplication is handled
    by the LLM during compaction (the compaction prompt removes duplicates).

    Returns (files_merged, new_entries_count). Runs in a thread via to_thread.
    """
    d = _memory_dir(repo_path)
    inbox = d / "inbox"
    if not inbox.is_dir():
        return 0, 0

    inbox_files = sorted(inbox.glob("*.md"))
    if not inbox_files:
        return 0, 0

    d.mkdir(parents=True, exist_ok=True)
    decisions_path = d / "decisions.md"
    lock_path = d / ".merge.lock"
    lock_path.touch(exist_ok=True)

    with lock_path.open("w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            existing = ""
            if decisions_path.is_file():
                existing = decisions_path.read_text(encoding="utf-8")

            # Append all inbox entries (LLM handles dedup during compaction)
            new_entries: list[str] = []
            for f in inbox_files:
                text = f.read_text(encoding="utf-8").strip()
                if text:
                    new_entries.append(text)

            if new_entries:
                combined = existing.rstrip() + "\n\n" + "\n\n".join(new_entries) + "\n"
                decisions_path.write_text(combined.lstrip(), encoding="utf-8")

            # Clean up inbox files regardless
            for f in inbox_files:
                f.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    return len(inbox_files), len(new_entries)


def _locked_write_compaction(repo_path: str, original_content: str, summarized: str) -> bool:
    """Synchronous file-locked CAS write for compaction.

    Only writes if decisions.md still contains *original_content* (hasn't been
    modified by a concurrent merge). Archives the original, writes the summary.

    Returns True if write succeeded.
    """
    d = _memory_dir(repo_path)
    decisions_path = d / "decisions.md"
    lock_path = d / ".merge.lock"
    lock_path.touch(exist_ok=True)

    with lock_path.open("w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            # CAS: verify content hasn't changed
            if not decisions_path.is_file():
                return False
            current = decisions_path.read_text(encoding="utf-8").strip()
            if current != original_content:
                # Content changed during LLM call — abort
                log.info("workspace_memory.compact_cas_failed", repo=_repo_slug(repo_path))
                return False

            # Write to archive (with LRU cap)
            archive_path = d / "archive.md"
            archive_existing = ""
            if archive_path.is_file():
                archive_existing = archive_path.read_text(encoding="utf-8")

            archive_combined = archive_existing.rstrip() + "\n\n" + original_content + "\n"
            archive_combined = archive_combined.lstrip()

            # Cap archive: keep at most 5 compaction generations.
            # Each generation is at most _ARCHIVE_THRESHOLD_BYTES (~20KB),
            # so cap = 5 × 20KB = 100KB.
            _cap_archive(archive_path, archive_combined, _MAX_ARCHIVE_BYTES)

            # Replace decisions with the summarized version
            decisions_path.write_text(summarized.strip() + "\n", encoding="utf-8")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    return True


def _cap_archive(archive_path: Path, content: str, max_bytes: int) -> None:
    """Write *content* to archive, trimming oldest paragraphs if over *max_bytes*.

    Linear scan: compute byte sizes per paragraph, drop from the front until
    total fits within the budget.
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        archive_path.write_text(content, encoding="utf-8")
        return

    paragraphs = content.split("\n\n")
    # Pre-compute byte size of each paragraph (including the \n\n separator)
    separator_bytes = len("\n\n".encode("utf-8"))
    sizes = [len(p.encode("utf-8")) for p in paragraphs]

    total = sum(sizes) + separator_bytes * (len(sizes) - 1)
    start = 0
    while total > max_bytes and start < len(paragraphs) - 1:
        total -= sizes[start] + separator_bytes
        start += 1

    archive_path.write_text("\n\n".join(paragraphs[start:]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Merge inbox → decisions (async, thread-offloaded locking)
# ---------------------------------------------------------------------------


async def merge_inbox(repo_path: str, compacter: MemoryCompacter) -> int:
    """Move inbox entries into ``decisions.md`` and delete inbox files.

    File I/O with locking runs in a thread to avoid blocking the event loop.
    After merge, triggers compaction if needed.

    Returns the number of inbox files merged.
    """
    merged_count, new_count = await asyncio.to_thread(_locked_merge, repo_path)

    if merged_count == 0:
        return 0

    log.info(
        "workspace_memory.inbox_merged",
        repo=_repo_slug(repo_path),
        count=merged_count,
        new_entries=new_count,
    )

    # Auto-compact after merge
    await compact_decisions(repo_path, compacter)

    return merged_count


# ---------------------------------------------------------------------------
# Compact decisions → archive (LLM-summarized, CAS write)
# ---------------------------------------------------------------------------

# 20 KB — derived from typical context-window budget for system prompts
# (~4K tokens at ~5 bytes/token).
_ARCHIVE_THRESHOLD_BYTES = 20 * 1024

# Archive cap: 5 generations of compacted content (5 × 20KB).
_MAX_ARCHIVE_BYTES = 5 * _ARCHIVE_THRESHOLD_BYTES


async def compact_decisions(repo_path: str, compacter: MemoryCompacter) -> bool:
    """When ``decisions.md`` exceeds the threshold, use the LLM to summarize
    and move old content to ``archive.md``.

    Uses a CAS pattern: reads content, calls LLM (no lock held), then
    re-acquires lock and only writes if content hasn't changed.

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

    # Call LLM without holding any lock
    try:
        summarized = await compacter.compact(content)
    except Exception:
        log.warning("workspace_memory.compaction_failed", repo=_repo_slug(repo_path), exc_info=True)
        return False

    if not summarized or not summarized.strip():
        return False

    # CAS write in a thread (re-acquires lock, verifies content unchanged)
    written = await asyncio.to_thread(_locked_write_compaction, repo_path, content, summarized)

    if written:
        log.info(
            "workspace_memory.compacted",
            repo=_repo_slug(repo_path),
            original_bytes=size,
            summarized_bytes=len(summarized.encode("utf-8")),
        )
    return written


# ---------------------------------------------------------------------------
# Direct read/write for API
# ---------------------------------------------------------------------------


def read_memory_text(repo_path: str) -> str:
    """Return the full memory text (decisions + wisdom) for the API."""
    return load_workspace_memory(repo_path) or ""


def read_memory_detail(repo_path: str) -> dict[str, str]:
    """Return decisions, wisdom, and archive as separate fields."""
    d = _memory_dir(repo_path)
    result: dict[str, str] = {"decisions": "", "wisdom": "", "archive": ""}

    decisions = d / "decisions.md"
    if decisions.is_file():
        result["decisions"] = decisions.read_text(encoding="utf-8").strip()

    wisdom = d / "wisdom.md"
    if wisdom.is_file():
        result["wisdom"] = wisdom.read_text(encoding="utf-8").strip()

    archive = d / "archive.md"
    if archive.is_file():
        result["archive"] = archive.read_text(encoding="utf-8").strip()

    return result


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
