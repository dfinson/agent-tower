"""ClaudeSessionStateWatcher — discovers and tails Claude CLI sessions.

Polls ``~/.claude/projects/{encoded-cwd}/`` for JSONL session files matching
CodePlane-managed workspaces. For each discovered session, tails the JSONL
file and feeds parsed events through RuntimeService's full processing pipeline.

Operator messaging is handled via a pending-message queue: the Stop hook
endpoint polls get_pending_messages() and returns them in the hook response.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.domain import Job, JobSource, JobState, SessionEvent, SessionEventKind
from backend.models.events import DomainEvent, DomainEventKind
from backend.services.events.event_enricher import ToolEventEnricher
from backend.services.watcher.telemetry_mixin import WatcherTelemetryMixin

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.services.coderecon.coderecon_service import CodeReconService
    from backend.services.events.event_bus import EventBus
    from backend.services.git.git_service import GitService
    from backend.services.runtime import RuntimeService

log = structlog.get_logger()

_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# How often to poll for new session files
_DISCOVERY_POLL_S = 2.0
# How often to check JSONL files for new lines
_TAIL_POLL_S = 0.3

# Max bytes to read in a single tail read (prevent memory spike)
_MAX_READ_CHUNK = 256 * 1024  # 256 KB

# After this many consecutive idle polls, probe liveness via /proc
_IDLE_POLLS_BEFORE_LIVENESS = math.ceil(_DISCOVERY_POLL_S / _TAIL_POLL_S)

# Acceptable characters for session IDs (UUIDs with hyphens)
_SESSION_ID_PATTERN = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

# Regex to match JSONL session files (UUID format)
_SESSION_FILE_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$")

# ---------------------------------------------------------------------------
# Model pricing cache (reloads automatically when file changes)
# ---------------------------------------------------------------------------

_MODEL_PRICING: dict[str, dict[str, float]] | None = None
_PRICING_MTIME: float = 0.0
_PRICING_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "model_pricing.json"


def _get_pricing() -> dict[str, dict[str, float]]:
    """Load model pricing data ($/MTok) from bundled JSON. Reloads on file change."""
    global _MODEL_PRICING, _PRICING_MTIME  # noqa: PLW0603
    try:
        current_mtime = _PRICING_PATH.stat().st_mtime
    except OSError:
        if _MODEL_PRICING is None:
            _MODEL_PRICING = {}
        return _MODEL_PRICING

    if _MODEL_PRICING is None or current_mtime != _PRICING_MTIME:
        try:
            _MODEL_PRICING = json.loads(_PRICING_PATH.read_text())
            _PRICING_MTIME = current_mtime
        except (json.JSONDecodeError, OSError):
            log.debug("claude_watcher_pricing_unavailable")
            if _MODEL_PRICING is None:
                _MODEL_PRICING = {}
    return _MODEL_PRICING


def _normalize_model_key(model: str) -> str:
    """Normalize model name to match pricing keys (lowercase, non-alnum → hyphen)."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", model.lower())).strip("-")


def _compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    """Compute USD cost from token counts using bundled pricing data.

    Returns 0.0 if model is unknown or pricing data unavailable.
    """
    pricing = _get_pricing()
    entry = pricing.get(model) or pricing.get(_normalize_model_key(model))
    if not entry:
        return 0.0
    # Pricing values are $/MTok (per 1M tokens)
    cost = (
        input_tokens * entry.get("input", 0)
        + output_tokens * entry.get("output", 0)
        + cache_read_tokens * entry.get("cache_read", 0)
        + cache_write_tokens * entry.get("cache_write", 0)
    ) / 1_000_000
    return cost


def _encode_cwd(path: str) -> str:
    """Encode a cwd path to the Claude projects directory name format.

    Claude CLI uses path.replace('/', '-') with leading slash becoming leading hyphen.
    e.g. /home/dave01/repos/project → -home-dave01-repos-project
    """
    return path.replace("/", "-")


def _is_pid_alive(pid: int) -> bool:
    """O(1) check: is this specific PID still a claude process?"""
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        return b"claude" in cmdline
    except (OSError, PermissionError):
        return False


def _find_claude_pids_at_cwd(repo_path: str, exclude_pids: frozenset[int] = frozenset()) -> list[int]:
    """Find all claude PIDs whose cwd matches repo_path, excluding already-claimed PIDs."""
    results: list[int] = []
    try:
        repo_resolved = Path(repo_path).resolve()
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            pid = int(pid_dir.name)
            if pid in exclude_pids:
                continue
            try:
                cmdline = (pid_dir / "cmdline").read_bytes()
                if b"claude" not in cmdline:
                    continue
                proc_cwd = (pid_dir / "cwd").resolve()
                if proc_cwd == repo_resolved:
                    results.append(pid)
            except (OSError, PermissionError):
                continue
    except OSError:
        pass
    return results


def _is_claude_process_alive(session_id: str, repo_path: str | None = None) -> bool:
    """Fallback liveness check when no cached PID is available.

    Scans /proc for any claude process whose cwd matches repo_path.
    Used only during startup recovery when we don't have a PID yet.
    """
    if not repo_path:
        try:
            for pid_dir in Path("/proc").iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    cmdline = (pid_dir / "cmdline").read_bytes()
                    if b"claude" in cmdline:
                        return True
                except (OSError, PermissionError):
                    continue
        except OSError:
            pass
        return False
    return len(_find_claude_pids_at_cwd(repo_path)) > 0


class ClaudeSessionStateWatcher(WatcherTelemetryMixin):
    """Discovers and ingests Claude CLI sessions from local JSONL files."""

    _watcher_log_prefix = "claude_watcher"

    def __init__(
        self,
        event_bus: EventBus,
        runtime_service: RuntimeService,
        session_factory: async_sessionmaker[AsyncSession],
        config: CPLConfig,
        git_service: GitService | None = None,
        coderecon_service: CodeReconService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._runtime = runtime_service
        self._session_factory = session_factory
        self._config = config
        self._git = git_service
        self._coderecon = coderecon_service

        # Track which session IDs we're already tailing
        self._tracked_sessions: set[str] = set()
        # session_id → job_id
        self._session_to_job: dict[str, str] = {}
        # job_id → session_id (reverse map)
        self._job_to_session: dict[str, str] = {}
        # session_id → tail task
        self._tail_tasks: dict[str, asyncio.Task[Any]] = {}
        # Discovery loop task
        self._discovery_task: asyncio.Task[Any] | None = None
        self._running = False
        # Per-job context for event processor
        self._job_worktrees: dict[str, str] = {}  # job_id → worktree_path
        self._job_base_refs: dict[str, str] = {}  # job_id → base_ref
        # Per-job tool event enricher (pairs tool_use→tool_result with metadata)
        self._enrichers: dict[str, ToolEventEnricher] = {}  # job_id → enricher
        # Instance-level background tasks (DB writes, coderecon indexing)
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        # Per-job accumulated telemetry deltas (flushed atomically with offset)
        self._pending_telemetry: dict[str, dict[str, float | int]] = {}
        # Operator message queue: job_id → list of messages
        self._pending_messages: dict[str, list[str]] = {}
        # Per-job prompt capture (first user message)
        self._prompt_captured: set[str] = set()
        # Guard: jobs currently being finalized (prevent double finalization)
        self._finalizing: set[str] = set()
        # session_id → PID of the owning claude process (O(1) liveness)
        self._session_pids: dict[str, int] = {}
        # Startup timestamp — sessions whose JSONL was last modified before
        # this are ignored unless they already have a job in the DB (handled
        # by _load_existing_sessions).
        self._started_at: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Begin discovery polling. Called from lifespan startup."""
        # Auto-configure Stop hook in ~/.claude/settings.json
        self._install_stop_hook()

        if not _CLAUDE_PROJECTS_DIR.exists():
            log.info("claude_watcher_no_projects_dir", path=str(_CLAUDE_PROJECTS_DIR))
            return
        self._running = True
        self._started_at = datetime.now(UTC).timestamp()

        # Pre-populate tracked set from existing jobs
        await self._load_existing_sessions()

        self._discovery_task = asyncio.create_task(self._discovery_loop(), name="claude-session-discovery")
        log.info("claude_watcher_started", repos=self._config.repos)

    async def stop(self) -> None:
        """Stop all tailing and discovery. Called from lifespan shutdown."""
        self._running = False
        if self._discovery_task:
            self._discovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._discovery_task
            self._discovery_task = None
        # Cancel all tail tasks
        for task in self._tail_tasks.values():
            task.cancel()
        if self._tail_tasks:
            await asyncio.gather(*self._tail_tasks.values(), return_exceptions=True)
        self._tail_tasks.clear()
        # Drain in-flight background tasks
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        # Note: we intentionally do NOT remove the Stop hook from settings.
        # The hook URL is idempotent — if CodePlane isn't running, Claude
        # gets connection refused which it handles gracefully. This avoids
        # races when multiple sessions are active or CodePlane restarts.
        log.info("claude_watcher_stopped")

    def get_pending_messages(self, session_id: str) -> list[str]:
        """Drain and return pending operator messages for a session (called by Stop hook)."""
        job_id = self._session_to_job.get(session_id)
        if not job_id:
            return []
        messages = self._pending_messages.pop(job_id, [])
        return messages

    async def send_operator_message(self, job_id: str, message: str) -> None:
        """Queue an operator message for delivery via the next Stop hook."""
        self._pending_messages.setdefault(job_id, []).append(message)
        log.info("claude_operator_message_queued", job_id=job_id)

    async def abort_session(self, job_id: str) -> None:
        """Queue an abort message for the next Stop hook."""
        self._pending_messages.setdefault(job_id, []).append(
            "OPERATOR: Session abort requested. Please stop immediately."
        )
        log.info("claude_abort_queued", job_id=job_id)

    # ------------------------------------------------------------------
    # Settings auto-configuration
    # ------------------------------------------------------------------

    def _get_hook_url(self) -> str:
        """Build the Stop hook URL from config."""
        host = self._config.server.host if hasattr(self._config, "server") else "127.0.0.1"
        port = self._config.server.port if hasattr(self._config, "server") else 8080
        return f"http://{host}:{port}/api/hooks/claude"

    def _install_stop_hook(self) -> None:
        """Write Stop hook entry into ~/.claude/settings.json.

        Uses atomic write (temp file + rename) to avoid TOCTOU races with
        concurrent writers (other Claude instances, user edits).
        """
        import tempfile

        hook_url = self._get_hook_url()
        settings_dir = _CLAUDE_SETTINGS_PATH.parent
        settings_dir.mkdir(parents=True, exist_ok=True)

        try:
            if _CLAUDE_SETTINGS_PATH.exists():
                content = _CLAUDE_SETTINGS_PATH.read_text()
                settings = json.loads(content) if content.strip() else {}
            else:
                settings = {}

            # Ensure hooks.Stop exists as a list
            hooks = settings.setdefault("hooks", {})
            stop_hooks = hooks.setdefault("Stop", [])

            # Add our hook URL if not already present
            if hook_url not in stop_hooks:
                stop_hooks.append(hook_url)
                # Atomic write: write temp file in same dir, then rename
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(settings_dir),
                    suffix=".tmp",
                    prefix=".settings-",
                )
                try:
                    with open(fd, "w") as f:
                        json.dump(settings, f, indent=2)
                        f.write("\n")
                    Path(tmp_path).replace(_CLAUDE_SETTINGS_PATH)
                except BaseException:
                    Path(tmp_path).unlink(missing_ok=True)
                    raise
                log.info("claude_watcher_hook_installed", url=hook_url)
            else:
                log.debug("claude_watcher_hook_already_present", url=hook_url)
        except Exception:
            log.warning("claude_watcher_hook_install_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Startup recovery
    # ------------------------------------------------------------------

    def _make_pop_callback(self, sid: str) -> Callable[[object], None]:
        """Create a done-callback that removes *sid* from tail_tasks."""

        def _cb(_t: object) -> None:
            self._tail_tasks.pop(sid, None)

        return _cb

    async def _load_existing_sessions(self) -> None:
        """Load session IDs from existing claude_cli jobs to avoid re-import."""
        running_jobs: list[tuple[str, str, int, str | None, str | None, str | None]] = []
        try:
            async with self._session_factory() as session:
                from sqlalchemy import text

                result = await session.execute(
                    text(
                        "SELECT id, external_session_id, state, tail_offset, "
                        "       worktree_path, base_ref, repo "
                        "FROM jobs WHERE external_session_id IS NOT NULL AND source = 'claude_cli'"
                    )
                )
                for row in result:
                    job_id, ext_sid, state, offset, wt, base, repo = (
                        row[0],
                        row[1],
                        row[2],
                        row[3] or 0,
                        row[4],
                        row[5],
                        row[6],
                    )
                    self._tracked_sessions.add(ext_sid)
                    if state == "running":
                        running_jobs.append((job_id, ext_sid, offset, wt, base, repo))

            log.debug("claude_watcher_loaded_existing", count=len(self._tracked_sessions))

            # Re-attach or finalize running claude_cli jobs
            for job_id, ext_sid, offset, wt, base, repo in running_jobs:
                repo_for_liveness = wt or repo or None
                alive = await asyncio.to_thread(
                    _is_claude_process_alive,
                    ext_sid,
                    repo_for_liveness,
                )

                if not alive:
                    log.info("claude_watcher_orphan_detected", job_id=job_id, session_id=ext_sid)
                    await self._finalize_session(
                        job_id,
                        error_reason="session ended while CodePlane was offline",
                    )
                else:
                    # Re-attach and resume tailing
                    self._session_to_job[ext_sid] = job_id
                    self._job_to_session[job_id] = ext_sid
                    self._job_worktrees[job_id] = wt or repo or ""
                    self._job_base_refs[job_id] = base or "HEAD"
                    await self._runtime.register_external_session(
                        job_id, self._job_worktrees[job_id], self._job_base_refs[job_id]
                    )
                    jsonl_path = self._find_session_file(ext_sid)
                    if jsonl_path:
                        task = asyncio.create_task(
                            self._tail_events(ext_sid, job_id, jsonl_path, initial_offset=offset),
                            name=f"claude-tail-{ext_sid[:8]}",
                        )
                        self._tail_tasks[ext_sid] = task
                        task.add_done_callback(self._make_pop_callback(ext_sid))
                        log.info("claude_watcher_reattached", job_id=job_id, offset=offset)
        except Exception:
            log.warning("claude_watcher_load_existing_failed", exc_info=True)

    def _find_session_file(self, session_id: str) -> Path | None:
        """Find the JSONL file for a given session ID across all project dirs."""
        if not _CLAUDE_PROJECTS_DIR.exists():
            return None
        for project_dir in _CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
        return None

    # ------------------------------------------------------------------
    # Discovery loop
    # ------------------------------------------------------------------

    async def _discovery_loop(self) -> None:
        """Poll ~/.claude/projects/ for new session JSONL files."""
        while self._running:
            try:
                new_sessions = await asyncio.to_thread(self._scan_for_new_sessions)
                for session_id, jsonl_path, repo_path in new_sessions:
                    if session_id in self._tracked_sessions:
                        continue
                    self._tracked_sessions.add(session_id)
                    log.info(
                        "claude_watcher_discovered",
                        session_id=session_id,
                        repo=repo_path,
                    )
                    await self._attach_session(session_id, jsonl_path, repo_path)
            except asyncio.CancelledError:
                return
            except Exception:
                log.debug("claude_watcher_discovery_error", exc_info=True)
            await asyncio.sleep(_DISCOVERY_POLL_S)

    def _scan_for_new_sessions(self) -> list[tuple[str, Path, str]]:
        """Scan for new JSONL session files matching our managed repos.

        Returns list of (session_id, jsonl_path, repo_path) tuples.
        """
        if not _CLAUDE_PROJECTS_DIR.exists():
            return []

        managed_paths = set(self._config.repos)
        if not managed_paths:
            return []

        results: list[tuple[str, Path, str]] = []

        for repo_path in managed_paths:
            encoded = _encode_cwd(repo_path)
            project_dir = _CLAUDE_PROJECTS_DIR / encoded
            if not project_dir.is_dir():
                continue

            try:
                for entry in project_dir.iterdir():
                    if not entry.is_file():
                        continue
                    if not _SESSION_FILE_RE.match(entry.name):
                        continue
                    session_id = entry.stem  # filename without .jsonl
                    if session_id in self._tracked_sessions:
                        continue
                    # Validate session ID chars (path traversal defense)
                    if not all(c in _SESSION_ID_PATTERN for c in session_id):
                        continue
                    # Skip session files last modified before this watcher
                    # started — they are stale leftovers, not new sessions.
                    try:
                        if entry.stat().st_mtime < self._started_at:
                            continue
                    except OSError:
                        continue
                    results.append((session_id, entry, repo_path))
            except OSError:
                continue

        return results

    # ------------------------------------------------------------------
    # Session attachment
    # ------------------------------------------------------------------

    async def _attach_session(self, session_id: str, jsonl_path: Path, repo_path: str) -> None:
        """Create a CodePlane job and start tailing the JSONL file."""
        job = await self._create_job(session_id, repo_path)
        if job is None:
            self._tracked_sessions.discard(session_id)
            return

        job_id = job.id
        self._session_to_job[session_id] = job_id
        self._job_to_session[job_id] = session_id
        self._job_worktrees[job_id] = job.worktree_path or repo_path
        self._job_base_refs[job_id] = job.base_ref or "HEAD"

        # Discover and cache the owning Claude PID for O(1) liveness checks
        claimed_pids = frozenset(self._session_pids.values())
        pids = await asyncio.to_thread(_find_claude_pids_at_cwd, repo_path, claimed_pids)
        if pids:
            self._session_pids[session_id] = pids[0]

        # Register with RuntimeService for full pipeline processing
        # (sidecar session, heartbeat, stall detection, step tracking)
        await self._runtime.register_external_session(job_id, self._job_worktrees[job_id], self._job_base_refs[job_id])

        # Start tailing
        task = asyncio.create_task(
            self._tail_events(session_id, job_id, jsonl_path),
            name=f"claude-tail-{session_id[:8]}",
        )
        self._tail_tasks[session_id] = task
        task.add_done_callback(lambda _t: self._tail_tasks.pop(session_id, None))

        # Background: CodeRecon indexing
        coderecon = self._coderecon
        if coderecon:

            async def _index(repo: str = repo_path, jid: str = job_id) -> None:
                try:
                    await coderecon.ensure_repo_indexed(repo)
                except Exception:
                    log.debug("claude_watcher_coderecon_failed", job_id=jid, exc_info=True)

            self._fire_bg(_index(), name=f"claude-coderecon-{job_id[:8]}")

    async def _create_job(self, session_id: str, repo_path: str) -> Job | None:
        """Create a Job record for a discovered Claude session."""
        if not self._git:
            log.warning("claude_watcher_no_git_service")
            return None

        # Git metadata
        try:
            branch = await self._git.get_current_branch(cwd=repo_path)
        except Exception:
            branch = "unknown"

        try:
            base_ref = await self._git.rev_parse("HEAD", cwd=repo_path)
        except Exception:
            base_ref = "HEAD"

        # Deterministic job ID from session_id
        hex_suffix = hashlib.sha256(session_id.encode()).hexdigest()[:12]
        repo_slug = Path(repo_path).name
        job_id = f"{repo_slug}-{hex_suffix}"

        now = datetime.now(UTC)

        # Check if job already exists (resumed session after finalization)
        try:
            from backend.persistence.database import serialized_write

            async with serialized_write(self._session_factory) as session:
                from backend.persistence.job_repo import JobRepository

                repo = JobRepository(session)
                existing = await repo.get(job_id)
                if existing is not None:
                    # Re-activate the existing job — clear finalization guard
                    self._finalizing.discard(job_id)
                    await repo.update_state(
                        job_id,
                        JobState.running,
                        updated_at=now,
                    )
                    log.info(
                        "claude_watcher_job_reactivated",
                        job_id=job_id,
                        session_id=session_id,
                    )
                    await self._event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=job_id,
                            timestamp=now,
                            kind=DomainEventKind.job_state_changed,
                            payload={"state": JobState.running, "new_state": JobState.running},
                        )
                    )
                    return existing
        except Exception:
            log.debug("claude_watcher_job_check_failed", job_id=job_id, exc_info=True)

        job = Job(
            id=job_id,
            repo=repo_path,
            prompt="(discovered CLI session)",
            state=JobState.running,
            base_ref=base_ref,
            branch=branch,
            worktree_path=repo_path,
            session_id=None,
            created_at=now,
            updated_at=now,
            sdk="claude",
            source=JobSource.claude_cli,
            external_session_id=session_id,
        )

        # Persist job + initialize telemetry summary
        try:
            from backend.persistence.database import serialized_write

            async with serialized_write(self._session_factory) as session:
                from backend.persistence.job_repo import JobRepository
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository

                repo = JobRepository(session)
                await repo.create(job)
                await TelemetrySummaryRepository(session).init_job(
                    job_id,
                    sdk="claude",
                    repo=repo_path,
                    branch=branch,
                )
        except Exception:
            log.warning("claude_watcher_job_create_failed", session_id=session_id, exc_info=True)
            return None

        # Publish creation events
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.job_created,
                payload={
                    "repo": repo_path,
                    "branch": branch,
                    "base_ref": base_ref,
                    "source": JobSource.claude_cli,
                    "prompt": job.prompt,
                },
            )
        )
        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.job_state_changed,
                payload={"state": JobState.running, "new_state": JobState.running},
            )
        )

        # Sidecar session creation is handled by RuntimeService.register_external_session()

        log.info(
            "claude_watcher_job_created",
            job_id=job_id,
            session_id=session_id,
            repo=repo_path,
            branch=branch,
        )
        return job

    # ------------------------------------------------------------------
    # JSONL tailer
    # ------------------------------------------------------------------

    async def _tail_events(
        self,
        session_id: str,
        job_id: str,
        jsonl_path: Path,
        *,
        initial_offset: int = 0,
    ) -> None:
        """Tail a Claude JSONL session file and process events."""
        offset = initial_offset
        last_persisted_offset = offset
        buffer = ""
        session_ended = False
        idle_polls = 0

        while self._running and not session_ended:
            try:
                if not jsonl_path.exists():
                    idle_polls += 1
                    if idle_polls >= _IDLE_POLLS_BEFORE_LIVENESS:
                        idle_polls = 0
                        cached_pid = self._session_pids.get(session_id)
                        if cached_pid is not None:
                            alive = await asyncio.to_thread(_is_pid_alive, cached_pid)
                        else:
                            repo_path = self._job_worktrees.get(job_id)
                            alive = await asyncio.to_thread(
                                _is_claude_process_alive,
                                session_id,
                                repo_path,
                            )
                        if not alive:
                            self._schedule_offset_persist(job_id, offset)
                            await self._finalize_session(job_id, error_reason="session file disappeared")
                            session_ended = True
                            break
                    await asyncio.sleep(_TAIL_POLL_S)
                    continue

                current_size = jsonl_path.stat().st_size
                if current_size <= offset:
                    if current_size < offset:
                        # File truncated — reset
                        offset = 0
                        buffer = ""
                    idle_polls += 1
                    if idle_polls >= _IDLE_POLLS_BEFORE_LIVENESS:
                        idle_polls = 0
                        cached_pid = self._session_pids.get(session_id)
                        if cached_pid is not None:
                            alive = await asyncio.to_thread(_is_pid_alive, cached_pid)
                        else:
                            repo_path = self._job_worktrees.get(job_id)
                            alive = await asyncio.to_thread(
                                _is_claude_process_alive,
                                session_id,
                                repo_path,
                            )
                        if not alive:
                            self._schedule_offset_persist(job_id, offset)
                            await self._finalize_session(job_id)
                            session_ended = True
                            break
                    await asyncio.sleep(_TAIL_POLL_S)
                    continue

                # Read new bytes
                new_data = await asyncio.to_thread(self._read_from, jsonl_path, offset)
                offset += len(new_data)
                idle_polls = 0

                buffer += new_data.decode("utf-8", errors="replace")

                # Prevent unbounded buffer growth from a single massive line
                if "\n" not in buffer and len(buffer) > _MAX_READ_CHUNK:
                    log.warning(
                        "claude_watcher_line_too_long",
                        job_id=job_id,
                        size=len(buffer),
                    )
                    buffer = ""

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        ended = await self._process_jsonl_event(raw, session_id, job_id)
                        if ended:
                            session_ended = True
                            self._schedule_offset_persist(job_id, offset)
                            await self._finalize_session(job_id)
                            break
                    except json.JSONDecodeError:
                        log.debug("claude_watcher_invalid_json", line=line[:200])
                    except Exception:
                        log.debug("claude_watcher_event_error", exc_info=True)

                # Persist tail offset periodically (every 64 KB)
                if offset - last_persisted_offset >= 65536:
                    self._schedule_offset_persist(job_id, offset)
                    last_persisted_offset = offset

            except asyncio.CancelledError:
                self._schedule_offset_persist(job_id, offset)
                return
            except Exception:
                log.debug("claude_watcher_tail_error", exc_info=True)

            await asyncio.sleep(_TAIL_POLL_S)

    @staticmethod
    def _read_from(path: Path, offset: int) -> bytes:
        """Read file from byte offset, bounded to _MAX_READ_CHUNK."""
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(_MAX_READ_CHUNK)

    # ------------------------------------------------------------------
    # JSONL event processing
    # ------------------------------------------------------------------

    async def _process_jsonl_event(self, raw: dict[str, Any], session_id: str, job_id: str) -> bool:
        """Process a single JSONL event. Returns True if session ended.

        Claude JSONL event types:
        - "user": role=user message (has cwd, gitBranch, sessionId, version)
        - "assistant": role=assistant message (content blocks, usage)
        - "last-prompt": session end signal
        - "queue-operation": skip
        - "attachment": skip
        """
        event_type = raw.get("type", "")

        if event_type == "last-prompt":
            return True

        if event_type in ("queue-operation", "attachment"):
            return False

        if event_type == "user":
            await self._handle_user_event(raw, session_id, job_id)
            return False

        if event_type == "assistant":
            await self._handle_assistant_event(raw, session_id, job_id)
            return False

        return False

    async def _handle_user_event(self, raw: dict[str, Any], session_id: str, job_id: str) -> None:
        """Handle a user-type JSONL event."""
        message = raw.get("message", {})
        content = message.get("content", "")

        # Extract text from content (can be string or list of blocks)
        text_content = ""
        if isinstance(content, str):
            text_content = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            text_content = "\n".join(parts)

        # Capture first user message as job prompt
        if job_id not in self._prompt_captured and text_content.strip():
            self._prompt_captured.add(job_id)
            self._fire_bg(
                self._set_job_prompt(job_id, text_content),
                name=f"claude-prompt-{job_id[:8]}",
            )

        # Feed as transcript event
        if text_content.strip():
            session_event = SessionEvent(
                kind=SessionEventKind.transcript,
                payload={"role": "operator", "content": text_content},
            )
            await self._feed_event(job_id, session_event)

        # Extract metadata from cwd field if present
        cwd = raw.get("cwd")
        if cwd and job_id not in self._job_worktrees:
            self._job_worktrees[job_id] = cwd

    async def _handle_assistant_event(self, raw: dict[str, Any], session_id: str, job_id: str) -> None:
        """Handle an assistant-type JSONL event."""
        from backend.services.tools.tool_classifier import classify_tool, extract_file_paths

        message = raw.get("message", {})
        content_blocks = message.get("content", [])
        usage = message.get("usage")

        # Process usage/telemetry
        if usage:
            await self._extract_usage_telemetry(usage, job_id, message)

        # Process content blocks
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "")
                    if text.strip():
                        session_event = SessionEvent(
                            kind=SessionEventKind.transcript,
                            payload={"role": "agent", "content": text},
                        )
                        await self._feed_event(job_id, session_event)

                elif block_type == "thinking":
                    thinking_text = block.get("thinking", "")
                    if thinking_text.strip():
                        session_event = SessionEvent(
                            kind=SessionEventKind.transcript,
                            payload={"role": "reasoning", "content": thinking_text},
                        )
                        await self._feed_event(job_id, session_event)

                elif block_type == "tool_use":
                    tool_name = block.get("name", "tool")
                    tool_id = block.get("id", "")
                    tool_input = block.get("input")
                    args_str = None
                    if tool_input is not None:
                        try:
                            args_str = json.dumps(tool_input) if not isinstance(tool_input, str) else tool_input
                        except (TypeError, ValueError):
                            args_str = str(tool_input)

                    # Use enricher to produce enriched tool_running payload
                    enricher = self._enrichers.get(job_id)
                    if enricher is None:
                        enricher = ToolEventEnricher()
                        self._enrichers[job_id] = enricher
                    payload = enricher.on_tool_start(
                        tool_id,
                        tool_name,
                        args_str,
                        None,
                    )
                    session_event = SessionEvent(
                        kind=SessionEventKind.transcript,
                        payload=payload,
                    )
                    await self._feed_event(job_id, session_event)

                    # Emit file_changed for file-write tools to trigger diff
                    if classify_tool(tool_name) == "file_write":
                        paths = extract_file_paths(tool_name, args_str)
                        for fpath in paths:
                            await self._feed_event(
                                job_id,
                                SessionEvent(
                                    kind=SessionEventKind.file_changed,
                                    payload={"path": fpath},
                                ),
                            )

                elif block_type == "tool_result":
                    tool_use_id = block.get("tool_use_id", "")
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        parts = []
                        for item in result_content:
                            if isinstance(item, dict):
                                parts.append(item.get("text", ""))
                        result_content = "\n".join(parts)

                    is_error = block.get("is_error", False)
                    # Use enricher to produce enriched tool_call payload
                    enricher = self._enrichers.get(job_id)
                    if enricher is None:
                        enricher = ToolEventEnricher()
                        self._enrichers[job_id] = enricher
                    payload = enricher.on_tool_complete(
                        tool_use_id,
                        str(result_content),
                        not is_error,
                        tool_name_fallback=block.get("name", "tool"),
                    )
                    session_event = SessionEvent(
                        kind=SessionEventKind.transcript,
                        payload=payload,
                    )
                    await self._feed_event(job_id, session_event)

    async def _extract_usage_telemetry(
        self,
        usage: dict[str, Any],
        job_id: str,
        message: dict[str, Any],
    ) -> None:
        """Extract token usage and cost telemetry from assistant message."""
        from backend.services.analytics import telemetry as tel

        input_toks = int(usage.get("input_tokens", 0))
        output_toks = int(usage.get("output_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        cache_write = int(usage.get("cache_creation_input_tokens", 0))
        model = message.get("model", "") or ""

        attrs = {"job_id": job_id, "sdk": "claude"}
        tel.tokens_input.add(input_toks, {**attrs, "model": model})
        tel.tokens_output.add(output_toks, {**attrs, "model": model})
        tel.tokens_cache_read.add(cache_read, attrs)
        tel.tokens_cache_write.add(cache_write, attrs)
        tel.messages_counter.add(1, {**attrs, "role": "agent"})

        # Compute cost from bundled model pricing
        cost_usd = _compute_cost(model, input_toks, output_toks, cache_read, cache_write)
        if cost_usd > 0:
            tel.cost_usd.add(cost_usd, attrs)

        # Accumulate for atomic flush with offset
        self._accumulate_telemetry(
            job_id,
            {
                "input_tokens": input_toks,
                "output_tokens": output_toks,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "total_cost_usd": cost_usd,
                "llm_call_count": 1,
            },
        )
        if model:
            self._schedule_model_update(job_id, model)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _feed_event(self, job_id: str, session_event: SessionEvent) -> None:
        """Feed a SessionEvent through RuntimeService's full processing pipeline."""
        worktree = self._job_worktrees.get(job_id)
        base_ref = self._job_base_refs.get(job_id)
        await self._runtime.feed_external_event(
            job_id,
            session_event,
            worktree_path=worktree,
            base_ref=base_ref,
        )

    async def _set_job_prompt(self, job_id: str, content: str) -> None:
        """Set job prompt from first user message."""
        try:
            from backend.persistence.database import serialized_write

            async with serialized_write(self._session_factory) as session:
                from backend.persistence.job_repo import JobRepository

                repo = JobRepository(session)
                job = await repo.get(job_id)
                if job and job.prompt == "(discovered CLI session)":
                    await repo.update_prompt(job_id, content[:500])
        except Exception:
            log.debug("claude_watcher_prompt_update_failed", job_id=job_id, exc_info=True)

    # ------------------------------------------------------------------
    # Session finalization
    # ------------------------------------------------------------------

    async def _finalize_session(
        self,
        job_id: str,
        *,
        error_reason: str | None = None,
    ) -> None:
        """Transition job to review (clean) or failed (error/orphan)."""
        # Guard against double finalization (liveness + last-prompt race)
        if job_id in self._finalizing:
            return
        self._finalizing.add(job_id)

        now = datetime.now(UTC)
        new_state = JobState.failed if error_reason else JobState.review

        try:
            from backend.persistence.database import serialized_write

            async with serialized_write(self._session_factory) as session:
                from backend.persistence.job_repo import JobRepository

                repo = JobRepository(session)
                await repo.update_state(
                    job_id,
                    new_state,
                    updated_at=now,
                    completed_at=now,
                    failure_reason=error_reason,
                )
        except Exception:
            log.warning("claude_watcher_finalize_failed", job_id=job_id, exc_info=True)
            return

        await self._event_bus.publish(
            DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.job_state_changed,
                payload={"state": new_state, "new_state": new_state},
            )
        )

        if new_state == JobState.review:
            await self._event_bus.publish(
                DomainEvent(
                    event_id=DomainEvent.make_event_id(),
                    job_id=job_id,
                    timestamp=now,
                    kind=DomainEventKind.job_review,
                    payload={"resolution": "unresolved"},
                )
            )

        # Delegate cleanup to RuntimeService (sidecar session, heartbeat,
        # stall detection, trail service, step tracker, diff service)
        await self._runtime.finalize_external_session(
            job_id,
            worktree_path=self._job_worktrees.get(job_id),
            base_ref=self._job_base_refs.get(job_id),
            error_reason=error_reason,
        )

        # Clean up watcher-local state
        self._job_worktrees.pop(job_id, None)
        self._job_base_refs.pop(job_id, None)
        self._pending_telemetry.pop(job_id, None)
        self._pending_messages.pop(job_id, None)
        self._prompt_captured.discard(job_id)
        enricher = self._enrichers.pop(job_id, None)
        if enricher:
            enricher.cleanup()
        # Note: do NOT remove from _finalizing here — the guard must persist
        # to prevent double-finalization from concurrent triggers.
        sid_to_remove = self._job_to_session.pop(job_id, None)
        if sid_to_remove:
            self._session_to_job.pop(sid_to_remove, None)
            # Allow re-discovery if session is resumed later
            self._tracked_sessions.discard(sid_to_remove)
            self._tail_tasks.pop(sid_to_remove, None)
            self._session_pids.pop(sid_to_remove, None)

        log.info(
            "claude_watcher_session_finalized",
            job_id=job_id,
            state=new_state,
            error_reason=error_reason,
        )
