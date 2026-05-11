"""SessionStateWatcher — discovers and tails Copilot CLI sessions.

Polls ``~/.copilot/session-store.db`` for sessions matching CodePlane-managed
workspaces (by ``cwd``) with ``host_type='github'`` (started with ``--remote``).

For each discovered session, tails ``events.jsonl`` using the same
``session_event_from_dict()`` parser that the SDK uses internally, then feeds
parsed events through the existing CopilotAdapter telemetry + event pipeline.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog

from backend.models.domain import Job, JobSource, JobState, Preset, SessionEvent, SessionEventKind
from backend.models.events import DomainEvent, DomainEventKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.config import CPLConfig
    from backend.services.coderecon_service import CodeReconService
    from backend.services.copilot_steer import CopilotSteerClient
    from backend.services.event_bus import EventBus
    from backend.services.event_processor import EventProcessor
    from backend.services.git_service import GitService
    from backend.services.sister_session import SisterSessionManager

log = structlog.get_logger()

_SESSION_STORE_PATH = Path.home() / ".copilot" / "session-store.db"
_SESSION_STATE_DIR = Path.home() / ".copilot" / "session-state"

# How often to poll session-store.db for new sessions
_DISCOVERY_POLL_S = 2.0
# How often to check events.jsonl for new lines
_TAIL_POLL_S = 0.3

# Max bytes to read from events.jsonl in a single read (prevent memory spike)
_MAX_READ_CHUNK = 256 * 1024  # 256 KB — will catch up over multiple polls

# Acceptable characters for session IDs (alphanumeric, hyphens, underscores)
_SESSION_ID_PATTERN = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


class SessionStateWatcher:
    """Discovers and ingests Copilot CLI sessions from the local session store."""

    def __init__(
        self,
        event_bus: EventBus,
        event_processor: EventProcessor,
        session_factory: async_sessionmaker[AsyncSession],
        config: CPLConfig,
        git_service: GitService | None = None,
        coderecon_service: CodeReconService | None = None,
        steer_client: CopilotSteerClient | None = None,
        sister_sessions: SisterSessionManager | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._processor = event_processor
        self._session_factory = session_factory
        self._config = config
        self._git = git_service
        self._coderecon = coderecon_service
        self._steer = steer_client
        self._sister_sessions = sister_sessions

        # Track which session IDs we're already tailing
        self._tracked_sessions: set[str] = set()
        # session_id → job_id
        self._session_to_job: dict[str, str] = {}
        # session_id → tail task
        self._tail_tasks: dict[str, asyncio.Task] = {}
        # Discovery loop task
        self._discovery_task: asyncio.Task | None = None
        self._running = False
        # Per-job context for event processor
        self._job_worktrees: dict[str, str] = {}  # job_id → worktree_path
        self._job_base_refs: dict[str, str] = {}  # job_id → base_ref
        # Instance-level background tasks (DB writes, coderecon indexing)
        self._bg_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Begin discovery polling. Called from lifespan startup."""
        if not _SESSION_STORE_PATH.exists():
            log.info("session_state_watcher_no_store", path=str(_SESSION_STORE_PATH))
            return
        self._running = True

        # Pre-populate tracked set from existing jobs so we don't re-import
        await self._load_existing_sessions()

        self._discovery_task = asyncio.create_task(
            self._discovery_loop(), name="session-state-discovery"
        )
        log.info("session_state_watcher_started", repos=self._config.repos)

    async def _load_existing_sessions(self) -> None:
        """Load session IDs from existing jobs to avoid re-import.

        For copilot_cli jobs still in running state, re-attach with the
        persisted tail offset so we resume ingestion where we left off.
        Terminal copilot_cli jobs and all managed sessions are marked
        tracked so they are never re-imported.
        """
        running_jobs: list[tuple[str, str, int, str | None, str | None, str | None]] = []
        try:
            async with self._session_factory() as session:
                from sqlalchemy import text

                # sdk_session_id = sessions launched by CopilotAdapter — always skip
                result_sdk = await session.execute(
                    text("SELECT sdk_session_id FROM jobs WHERE sdk_session_id IS NOT NULL")
                )
                for row in result_sdk:
                    self._tracked_sessions.add(row[0])

                # copilot_cli jobs: re-attach running ones, skip terminal ones
                result_cli = await session.execute(
                    text(
                        "SELECT id, external_session_id, state, tail_offset, "
                        "       worktree_path, base_ref, repo "
                        "FROM jobs WHERE external_session_id IS NOT NULL AND source = 'copilot_cli'"
                    )
                )
                for row in result_cli:
                    job_id, ext_sid, state, offset, wt, base, repo = (
                        row[0], row[1], row[2], row[3] or 0, row[4], row[5], row[6],
                    )
                    self._tracked_sessions.add(ext_sid)
                    if state == "running":
                        # Collect running jobs for liveness check after query
                        running_jobs.append((job_id, ext_sid, offset, wt, base, repo))

                # Non-CLI external sessions (e.g. claude_cli)
                result_other = await session.execute(
                    text(
                        "SELECT external_session_id FROM jobs "
                        "WHERE external_session_id IS NOT NULL AND source != 'copilot_cli'"
                    )
                )
                for row in result_other:
                    self._tracked_sessions.add(row[0])

            log.debug("session_state_watcher_loaded_existing", count=len(self._tracked_sessions))

            # Re-attach or finalize running copilot_cli jobs
            for job_id, ext_sid, offset, wt, base, repo in running_jobs:
                alive = True
                if self._steer:
                    alive = await self._steer.check_alive(ext_sid)

                if not alive:
                    # Session died while CodePlane was down — finalize as failed
                    log.info(
                        "session_state_watcher_orphan_detected",
                        job_id=job_id, session_id=ext_sid,
                    )
                    await self._finalize_session(
                        job_id, error_reason="session ended while CodePlane was offline",
                    )
                else:
                    # Still alive — re-attach and resume tailing
                    self._session_to_job[ext_sid] = job_id
                    self._job_worktrees[job_id] = wt or repo or ""
                    self._job_base_refs[job_id] = base or "HEAD"
                    self._processor.register_worktree(job_id, self._job_worktrees[job_id])
                    events_path = _SESSION_STATE_DIR / ext_sid / "events.jsonl"
                    task = asyncio.create_task(
                        self._tail_events(ext_sid, job_id, events_path, initial_offset=offset),
                        name=f"tail-{ext_sid[:8]}",
                    )
                    self._tail_tasks[ext_sid] = task
                    task.add_done_callback(lambda _t, sid=ext_sid: self._tail_tasks.pop(sid, None))
                    log.info("session_state_watcher_reattached", job_id=job_id, offset=offset)
        except Exception:
            log.warning("session_state_watcher_load_existing_failed", exc_info=True)

    async def stop(self) -> None:
        """Stop all tailing and discovery. Called from lifespan shutdown."""
        self._running = False
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass
            self._discovery_task = None
        # Cancel all tail tasks
        for task in self._tail_tasks.values():
            task.cancel()
        if self._tail_tasks:
            await asyncio.gather(*self._tail_tasks.values(), return_exceptions=True)
        self._tail_tasks.clear()
        # Drain in-flight background tasks (DB writes, coderecon indexing)
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        log.info("session_state_watcher_stopped")

    def _fire_bg(self, coro: Any, *, name: str) -> asyncio.Task:
        """Create a background task tracked for clean shutdown."""
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def send_message(self, session_id: str, message: str) -> None:
        """Send an operator message to a tracked session via steer API."""
        if self._steer is None:
            log.warning("session_state_watcher_no_steer_client")
            return
        # For --remote sessions, session_id IS the task_id
        await self._steer.send_message(session_id, message)

    async def abort_session(self, session_id: str) -> None:
        """Abort a tracked session via steer API."""
        if self._steer is None:
            log.warning("session_state_watcher_no_steer_client")
            return
        await self._steer.abort(session_id)

    # ------------------------------------------------------------------
    # Discovery loop
    # ------------------------------------------------------------------

    async def _discovery_loop(self) -> None:
        """Poll session-store.db for new matching sessions."""
        while self._running:
            try:
                new_sessions = await asyncio.to_thread(self._query_new_sessions)
                for sid, cwd, summary in new_sessions:
                    if sid in self._tracked_sessions:
                        continue
                    self._tracked_sessions.add(sid)
                    log.info(
                        "session_state_watcher_discovered",
                        session_id=sid,
                        cwd=cwd,
                        summary=summary[:80] if summary else "",
                    )
                    # Create job and start tailing
                    await self._attach_session(sid, cwd, summary)
            except asyncio.CancelledError:
                return
            except Exception:
                log.debug("session_state_watcher_discovery_error", exc_info=True)
            await asyncio.sleep(_DISCOVERY_POLL_S)

    def _query_new_sessions(self) -> list[tuple[str, str, str]]:
        """Query session-store.db for sessions matching our workspace config.

        Returns list of (session_id, cwd, summary) tuples.
        """
        if not _SESSION_STORE_PATH.exists():
            return []

        managed_paths = set(self._config.repos)
        if not managed_paths:
            return []

        results: list[tuple[str, str, str]] = []
        try:
            db = sqlite3.connect(str(_SESSION_STORE_PATH), timeout=2.0)
            db.execute("PRAGMA journal_mode=WAL")
            try:
                # Query sessions with host_type='github' (--remote flag)
                rows = db.execute(
                    "SELECT id, cwd, summary FROM sessions WHERE host_type = 'github'"
                ).fetchall()
                for row in rows:
                    sid, cwd, summary = row[0], row[1] or "", row[2] or ""
                    if sid in self._tracked_sessions:
                        continue
                    # Validate session ID format (defense-in-depth against path traversal)
                    if not sid or not all(c in _SESSION_ID_PATTERN for c in sid):
                        continue
                    # Match cwd against managed repo paths
                    # cwd may be a subdirectory of the repo path
                    for repo_path in managed_paths:
                        if cwd == repo_path or cwd.startswith(repo_path + "/"):
                            results.append((sid, cwd, summary))
                            break
            finally:
                db.close()
        except (sqlite3.Error, OSError):
            log.debug("session_state_watcher_db_error", exc_info=True)
        return results

    # ------------------------------------------------------------------
    # Session attachment (job creation + tail start)
    # ------------------------------------------------------------------

    async def _attach_session(self, session_id: str, cwd: str, summary: str) -> None:
        """Create a CodePlane job for the discovered session and start tailing."""
        job = await self._create_job(session_id, cwd)
        if job is None:
            self._tracked_sessions.discard(session_id)
            return

        job_id = job.id
        self._session_to_job[session_id] = job_id
        self._job_worktrees[job_id] = job.worktree_path or cwd
        self._job_base_refs[job_id] = job.base_ref or "HEAD"

        # Register with event processor for diff/step tracking
        self._processor.register_worktree(job_id, self._job_worktrees[job_id])

        # Start tailing events.jsonl
        events_path = _SESSION_STATE_DIR / session_id / "events.jsonl"
        task = asyncio.create_task(
            self._tail_events(session_id, job_id, events_path),
            name=f"tail-{session_id[:8]}",
        )
        self._tail_tasks[session_id] = task
        task.add_done_callback(lambda _t, sid=session_id: self._tail_tasks.pop(sid, None))

        # Background: CodeRecon indexing
        if self._coderecon:
            async def _index(repo: str = job.repo, jid: str = job_id) -> None:
                try:
                    await self._coderecon.ensure_repo_indexed(repo)
                except Exception:
                    log.debug("session_watcher_coderecon_failed", job_id=jid, exc_info=True)
            self._fire_bg(_index(), name=f"watcher-coderecon-{job_id[:8]}")

    async def _create_job(self, session_id: str, cwd: str) -> Job | None:
        """Create a Job record from a discovered session."""
        import hashlib

        if not self._git:
            log.warning("session_state_watcher_no_git_service")
            return None

        # Resolve git root
        try:
            repo_root = await self._git._run_git(  # noqa: SLF001
                "rev-parse", "--show-toplevel", cwd=cwd,
            )
            repo_path = repo_root.strip()
        except Exception:
            repo_path = cwd

        # Git metadata
        try:
            branch = await self._git.get_current_branch(cwd=cwd)
        except Exception:
            branch = "unknown"

        try:
            base_ref = await self._git.rev_parse("HEAD", cwd=cwd)
        except Exception:
            base_ref = "HEAD"

        # Deterministic job ID from session_id (12 hex chars = 48 bits → negligible collision)
        hex_suffix = hashlib.sha256(session_id.encode()).hexdigest()[:12]
        repo_slug = Path(repo_path).name
        job_id = f"{repo_slug}-{hex_suffix}"

        now = datetime.now(UTC)
        job = Job(
            id=job_id,
            repo=repo_path,
            prompt="(discovered CLI session)",
            state=JobState.running,
            base_ref=base_ref,
            branch=branch,
            worktree_path=cwd,
            session_id=None,
            created_at=now,
            updated_at=now,
            sdk="copilot",
            source=JobSource.copilot_cli,
            external_session_id=session_id,
        )

        # Persist job + initialize telemetry summary row
        try:
            async with self._session_factory() as session:
                from backend.persistence.job_repo import JobRepository
                from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
                repo = JobRepository(session)
                await repo.create(job)
                await TelemetrySummaryRepository(session).init_job(
                    job_id, sdk="copilot", repo=repo_path, branch=branch,
                )
                await session.commit()
        except Exception:
            log.warning("session_state_watcher_job_create_failed", session_id=session_id, exc_info=True)
            return None

        # Publish creation events
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.job_created,
            payload={
                "repo": repo_path,
                "branch": branch,
                "base_ref": base_ref,
                "source": JobSource.copilot_cli,
                "prompt": job.prompt,
            },
        ))
        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.job_state_changed,
            payload={"state": JobState.running, "new_state": JobState.running},
        ))

        # Sister session for title generation
        if self._sister_sessions:
            self._sister_sessions.create_for_job(job_id)

        log.info(
            "session_state_watcher_job_created",
            job_id=job_id,
            session_id=session_id,
            repo=repo_path,
            branch=branch,
        )
        return job

    # ------------------------------------------------------------------
    # Events.jsonl tailer
    # ------------------------------------------------------------------

    async def _tail_events(
        self, session_id: str, job_id: str, events_path: Path, *, initial_offset: int = 0,
    ) -> None:
        """Tail events.jsonl and process each event through the standard pipeline."""
        from copilot.generated.session_events import session_event_from_dict

        offset = initial_offset
        last_persisted_offset = offset
        buffer = ""
        shutdown_seen = False
        error_reason: str | None = None

        while self._running and not shutdown_seen:
            try:
                if not events_path.exists():
                    await asyncio.sleep(_TAIL_POLL_S)
                    continue

                current_size = events_path.stat().st_size
                if current_size <= offset:
                    if current_size < offset:
                        # File truncated — reset
                        offset = 0
                        buffer = ""
                    await asyncio.sleep(_TAIL_POLL_S)
                    continue

                # Read new bytes
                new_data = await asyncio.to_thread(self._read_from, events_path, offset)
                offset += len(new_data)

                buffer += new_data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        sdk_event = session_event_from_dict(raw)
                        await self._process_sdk_event(sdk_event, session_id, job_id)
                        # Detect session end
                        kind_str = sdk_event.type.value if sdk_event.type else ""
                        if kind_str == "session.error":
                            # Capture error details for finalization (#7)
                            data = sdk_event.data
                            error_reason = str(getattr(data, "message", None) or getattr(data, "error", None) or "session error")
                        elif kind_str == "session.shutdown":
                            shutdown_seen = True
                            await self._finalize_session(job_id, error_reason=error_reason)
                    except json.JSONDecodeError:
                        log.debug("session_watcher_invalid_json", line=line[:200])
                    except Exception:
                        log.debug("session_watcher_event_error", exc_info=True)

                # Persist tail offset periodically (every 64 KB of progress)
                if offset - last_persisted_offset >= 65536:
                    self._schedule_offset_persist(job_id, offset)
                    last_persisted_offset = offset

            except asyncio.CancelledError:
                # Persist final offset on graceful shutdown
                self._schedule_offset_persist(job_id, offset)
                return
            except Exception:
                log.debug("session_watcher_tail_error", exc_info=True)

            await asyncio.sleep(_TAIL_POLL_S)

        # Persist final offset when session ends
        self._schedule_offset_persist(job_id, offset)

    @staticmethod
    def _read_from(path: Path, offset: int) -> bytes:
        """Read file from byte offset, bounded to _MAX_READ_CHUNK (called in thread)."""
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(_MAX_READ_CHUNK)

    # ------------------------------------------------------------------
    # SDK event → telemetry + session queue
    # ------------------------------------------------------------------

    async def _process_sdk_event(
        self,
        sdk_event: Any,
        session_id: str,
        job_id: str,
    ) -> None:
        """Process a single SDK SessionEvent through the telemetry + event pipeline.

        Maps SDK events to the same SessionEvent objects that the managed adapter
        produces, then feeds them through EventProcessor for diffs, steps, and
        domain event publishing.
        """
        from copilot.generated.session_events import (
            SessionEventType,
        )

        kind_str = sdk_event.type.value if sdk_event.type else ""
        data = sdk_event.data

        # --- Telemetry extraction (mirrors CopilotAdapter._on_event) ---
        if data:
            await self._extract_telemetry(kind_str, data, job_id)

        # --- Map to SessionEvent for the EventProcessor ---
        session_event = self._map_to_session_event(kind_str, data)
        if session_event is None:
            return

        # Feed through the standard processing pipeline
        worktree = self._job_worktrees.get(job_id)
        base_ref = self._job_base_refs.get(job_id)
        await self._processor.process_event(
            job_id, session_event,
            worktree_path=worktree,
            base_ref=base_ref,
        )

    async def _extract_telemetry(self, kind_str: str, data: Any, job_id: str) -> None:
        """Extract telemetry metrics from SDK events (cost, tokens, tools)."""
        from backend.services import telemetry as tel

        if kind_str == "assistant.usage":
            input_toks = int(getattr(data, "input_tokens", 0) or 0)
            output_toks = int(getattr(data, "output_tokens", 0) or 0)
            cache_read = int(getattr(data, "cache_read_tokens", 0) or 0)
            cache_write = int(getattr(data, "cache_write_tokens", 0) or 0)
            cost = float(getattr(data, "cost", 0) or 0)
            model = getattr(data, "model", "") or ""
            duration_ms = float(getattr(data, "duration", 0) or 0)

            attrs = {"job_id": job_id, "sdk": "copilot"}
            tel.llm_calls_counter.add(1, attrs)
            tel.input_tokens_counter.add(input_toks, {**attrs, "model": model})
            tel.output_tokens_counter.add(output_toks, {**attrs, "model": model})
            tel.cost_counter.add(cost, attrs)

            # Persist to telemetry summary via atomic increment
            self._schedule_telemetry_increment(job_id, {
                "input_tokens": input_toks,
                "output_tokens": output_toks,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "total_cost_usd": cost,
                "llm_call_count": 1,
                "total_llm_duration_ms": int(duration_ms),
            })
            if model:
                self._schedule_model_update(job_id, model)

        elif kind_str == "session.usage_info":
            current = int(getattr(data, "current_tokens", 0) or 0)
            tel.context_tokens_gauge.set(current, {"job_id": job_id, "sdk": "copilot"})
            self._schedule_context_update(job_id, current)

        elif kind_str == "session.compaction_complete":
            pre = int(getattr(data, "pre_compaction_tokens", 0) or 0)
            post = int(getattr(data, "post_compaction_tokens", 0) or 0)
            tel.compactions_counter.add(1, {"job_id": job_id, "sdk": "copilot"})
            tel.tokens_compacted.add(max(0, pre - post), {"job_id": job_id, "sdk": "copilot"})
            self._schedule_telemetry_increment(job_id, {
                "compactions": 1,
                "tokens_compacted": max(0, pre - post),
            })

        elif kind_str == "assistant.message":
            tel.messages_counter.add(1, {"job_id": job_id, "sdk": "copilot", "role": "agent"})
            self._schedule_telemetry_increment(job_id, {"agent_messages": 1})

        elif kind_str == "user.message":
            tel.messages_counter.add(1, {"job_id": job_id, "sdk": "copilot", "role": "operator"})
            self._schedule_telemetry_increment(job_id, {"operator_messages": 1})

    def _schedule_telemetry_increment(self, job_id: str, counters: dict[str, Any]) -> None:
        """Schedule an atomic telemetry summary increment via TelemetrySummaryRepository."""

        async def _write() -> None:
            try:
                async with self._session_factory() as session:
                    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
                    await TelemetrySummaryRepository(session).increment(job_id=job_id, **counters)
                    await session.commit()
            except Exception:
                log.debug("session_watcher_telemetry_increment_failed", job_id=job_id, exc_info=True)

        self._fire_bg(_write(), name=f"watcher-tel-{job_id[:8]}")

    def _schedule_model_update(self, job_id: str, model: str) -> None:
        """Schedule a model update on the telemetry summary row."""

        async def _write() -> None:
            try:
                async with self._session_factory() as session:
                    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
                    await TelemetrySummaryRepository(session).set_model(job_id=job_id, model=model)
                    await session.commit()
            except Exception:
                log.debug("session_watcher_model_update_failed", job_id=job_id, exc_info=True)

        self._fire_bg(_write(), name=f"watcher-model-{job_id[:8]}")

    def _schedule_context_update(self, job_id: str, current_tokens: int) -> None:
        """Schedule a context window update on the telemetry summary row."""

        async def _write() -> None:
            try:
                async with self._session_factory() as session:
                    from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
                    await TelemetrySummaryRepository(session).set_context(
                        job_id=job_id, current_tokens=current_tokens,
                    )
                    await session.commit()
            except Exception:
                log.debug("session_watcher_context_update_failed", job_id=job_id, exc_info=True)

        self._fire_bg(_write(), name=f"watcher-ctx-{job_id[:8]}")

    def _schedule_offset_persist(self, job_id: str, offset: int) -> None:
        """Schedule a tail-offset persist via JobRepository.update_tail_offset."""

        async def _write() -> None:
            try:
                async with self._session_factory() as session:
                    from backend.persistence.job_repo import JobRepository
                    await JobRepository(session).update_tail_offset(job_id, offset)
                    await session.commit()
            except Exception:
                log.debug("session_watcher_offset_persist_failed", job_id=job_id, exc_info=True)

        self._fire_bg(_write(), name=f"watcher-offset-{job_id[:8]}")

    def _map_to_session_event(self, kind_str: str, data: Any) -> SessionEvent | None:
        """Map an SDK event type to a CodePlane SessionEvent."""
        # Event kind mapping (same as CopilotAdapter._SDK_KIND_MAP)
        _KIND_MAP: dict[str, SessionEventKind] = {
            "session.task_complete": SessionEventKind.done,
            "session.idle": SessionEventKind.done,
            "session.shutdown": SessionEventKind.done,
            "session.error": SessionEventKind.error,
            "assistant.message": SessionEventKind.transcript,
            "assistant.message_delta": SessionEventKind.transcript,
            "assistant.reasoning": SessionEventKind.transcript,
            "assistant.reasoning_delta": SessionEventKind.transcript,
            "user.message": SessionEventKind.transcript,
            "tool.execution_complete": SessionEventKind.transcript,
            "tool.execution_start": SessionEventKind.transcript,
            "tool.execution_partial_result": SessionEventKind.transcript,
            "session.workspace_file_changed": SessionEventKind.file_changed,
        }

        kind = _KIND_MAP.get(kind_str)
        if kind is None:
            return None

        payload: dict[str, Any] = {}

        if kind == SessionEventKind.transcript:
            if kind_str == "assistant.message":
                content = getattr(data, "content", "") or ""
                if not content.strip():
                    return None
                payload = {"role": "agent", "content": content}
            elif kind_str == "assistant.message_delta":
                delta = getattr(data, "delta_content", "") or ""
                if not delta:
                    return None
                payload = {"role": "agent_delta", "content": delta}
            elif kind_str == "assistant.reasoning":
                content = getattr(data, "content", "") or ""
                payload = {"role": "reasoning", "content": content}
            elif kind_str == "assistant.reasoning_delta":
                delta = getattr(data, "delta_content", "") or ""
                if not delta:
                    return None
                payload = {"role": "reasoning_delta", "content": delta}
            elif kind_str == "user.message":
                content = getattr(data, "content", "") or ""
                if "<system_notification>" in content:
                    return None
                payload = {"role": "operator", "content": content}
            elif kind_str == "tool.execution_start":
                tool_name = getattr(data, "tool_name", None) or getattr(data, "mcp_tool_name", None) or "tool"
                mcp_server = getattr(data, "mcp_server_name", None)
                if mcp_server and getattr(data, "mcp_tool_name", None):
                    tool_name = f"{mcp_server}/{data.mcp_tool_name}"
                args = getattr(data, "arguments", None)
                args_str = None
                if args is not None:
                    try:
                        args_str = json.dumps(args) if not isinstance(args, str) else args
                    except (TypeError, ValueError):
                        args_str = str(args)
                # Skip report_intent from transcript
                if tool_name == "report_intent":
                    return None
                payload = {
                    "role": "tool_running",
                    "tool_name": tool_name,
                    "tool_args": args_str,
                    "content": tool_name,
                }
            elif kind_str == "tool.execution_complete":
                tool_name = getattr(data, "tool_name", None) or "tool"
                success = bool(getattr(data, "success", True))
                result_text = ""
                result_obj = getattr(data, "result", None)
                if result_obj is not None:
                    content_attr = getattr(result_obj, "content", None)
                    if content_attr:
                        if isinstance(content_attr, list):
                            parts = []
                            for item in content_attr:
                                text = getattr(item, "text", None)
                                if text:
                                    parts.append(text)
                            result_text = "\n".join(parts)
                        else:
                            result_text = str(content_attr)
                    elif not result_text:
                        result_text = str(result_obj)
                # Skip internal tools
                if tool_name == "report_intent":
                    return None
                payload = {
                    "role": "tool_call",
                    "tool_name": tool_name,
                    "tool_result": result_text,
                    "tool_success": success,
                    "content": tool_name,
                }
            elif kind_str == "tool.execution_partial_result":
                chunk = getattr(data, "partial_output", "") or ""
                if not chunk:
                    return None
                tool_name = getattr(data, "tool_name", None) or "tool"
                payload = {
                    "role": "tool_output_delta",
                    "content": chunk,
                    "tool_name": tool_name,
                }
        elif kind == SessionEventKind.file_changed:
            file_path = getattr(data, "file_path", None) or ""
            payload = {"file": file_path}

        return SessionEvent(kind=kind, payload=payload)

    # ------------------------------------------------------------------
    # Session finalization
    # ------------------------------------------------------------------

    async def _finalize_session(
        self, job_id: str, *, error_reason: str | None = None,
    ) -> None:
        """Transition job to review (clean shutdown) or failed (error/orphan)."""
        now = datetime.now(UTC)
        if error_reason:
            new_state = JobState.failed
        else:
            new_state = JobState.review

        try:
            async with self._session_factory() as session:
                from backend.persistence.job_repo import JobRepository
                repo = JobRepository(session)
                await repo.update_state(
                    job_id, new_state, updated_at=now, completed_at=now,
                    failure_reason=error_reason,
                )
                await session.commit()
        except Exception:
            log.warning("session_watcher_finalize_failed", job_id=job_id, exc_info=True)
            return

        await self._event_bus.publish(DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id=job_id,
            timestamp=now,
            kind=DomainEventKind.job_state_changed,
            payload={"state": new_state, "new_state": new_state},
        ))

        if new_state == JobState.review:
            await self._event_bus.publish(DomainEvent(
                event_id=DomainEvent.make_event_id(),
                job_id=job_id,
                timestamp=now,
                kind=DomainEventKind.job_review,
                payload={"resolution": "done"},
            ))

        # Notify processor for step cleanup
        await self._processor.on_job_terminal(job_id, new_state)

        log.info(
            "session_state_watcher_session_finalized",
            job_id=job_id, state=new_state, error_reason=error_reason,
        )
