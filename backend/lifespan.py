"""Application lifespan — startup and shutdown management for CodePlane.

Handles database initialisation, service wiring, background tasks, and
graceful shutdown.  Extracted from main.py to keep concerns separated.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from dishka import make_async_container
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.config import MCP_PATH, VOICE_MAX_AUDIO_SIZE_MB, CPLConfig, get_codeplane_dir, load_config
from backend.di import AppProvider, CachedModelsBySdk, RequestProvider, VoiceMaxBytes
from backend.models.events import DomainEventKind
from backend.persistence.database import create_engine, create_session_factory
from backend.persistence.event_repo import EventRepository
from backend.persistence.step_repo import StepRepository
from backend.services.adapter_registry import AdapterRegistry
from backend.services.approval_service import ApprovalService
from backend.services.diff_service import DiffService
from backend.services.event_bus import EventBus
from backend.services.git_service import GitService
from backend.services.merge_service import MergeService
from backend.services.platform_adapter import PlatformRegistry
from backend.services.push_service import PushService
from backend.services.retention_service import RetentionService
from backend.services.runtime_service import RuntimeService
from backend.services.share_service import ShareService
from backend.services.sister_session import SisterSessionManager
from backend.services.sse_manager import SSEManager
from backend.services.step_persistence import StepPersistenceSubscriber
from backend.services.step_tracker import StepTracker
from backend.services.summarization_service import SummarizationService
from backend.services.vapid_keys import get_or_create_vapid_keys
from backend.services.voice_service import VoiceService

from backend.services.terminal_service import TerminalService

from backend.services.coderecon_service import CodeReconService


class _JobLike:
    """Lightweight adapter matching the fields _generate_review_story expects."""

    __slots__ = ("repo", "worktree_path", "base_ref", "title", "prompt")

    def __init__(self, row: tuple) -> None:
        self.repo = row[0]
        self.worktree_path = row[1]
        self.base_ref = row[2]
        self.title = row[3] if len(row) > 3 else None
        self.prompt = row[4] if len(row) > 4 else None


# Tracks fire-and-forget background tasks so they can be awaited on shutdown.
_ephemeral_tasks: set[asyncio.Task] = set()  # noqa: WPS407


def _fire_and_forget(coro, *, name: str) -> asyncio.Task:
    """Schedule a coroutine as a tracked background task."""
    task = asyncio.create_task(coro, name=name)
    _ephemeral_tasks.add(task)
    task.add_done_callback(_ephemeral_tasks.discard)
    return task


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.models.events import DomainEvent

log = structlog.get_logger()


def _print_qr_code(url: str) -> None:
    """Print a QR code for *url* to the console (best-effort)."""
    try:
        import io

        import qrcode
        from rich.align import Align
        from rich.console import Console
        from rich.text import Text

        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)

        console = Console(stderr=True)
        console.print()
        console.print(Align.center(Text(buf.getvalue().rstrip("\n"))))
        console.print(Align.center(Text.from_markup(f"Scan to open: [bold]{url}[/bold]")))
        console.print()
    except ImportError:
        log.debug("qrcode_not_available")


_EVENT_PERSIST_MAX_ATTEMPTS = 3
_EVENT_PERSIST_RETRY_DELAY_S = 0.05
_DEAD_LETTER_RETRY_INTERVAL_S = 5.0
_DEAD_LETTER_MAX_RETRIES = 10


# ---------------------------------------------------------------------------
# Helper dataclass to bundle core services for easy passing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CoreServices:
    approval_service: ApprovalService
    adapter_registry: AdapterRegistry
    platform_registry: PlatformRegistry
    merge_service: MergeService
    sister_sessions: SisterSessionManager
    runtime_service: RuntimeService
    git_service: GitService
    diff_service: DiffService


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------


def _init_event_infrastructure(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[EventBus, SSEManager, asyncio.Task[None]]:
    """Create event bus and SSE manager with persist-then-broadcast wiring.

    Returns the event bus, SSE manager, and a background task that retries
    events from the dead-letter queue.
    """
    event_bus = EventBus()
    sse_manager = SSEManager()
    persist_lock = asyncio.Lock()
    dead_letter: asyncio.Queue[tuple[DomainEvent, int]] = asyncio.Queue()

    # Persist-then-broadcast subscriber: ensures event.db_id is set
    # (monotonic autoincrement) before SSE frames are built.
    async def _persist_and_broadcast(event: DomainEvent) -> None:
        # agent_delta events are ephemeral streaming chunks — broadcast
        # immediately without writing to DB (the complete agent message
        # that follows is the canonical persisted record).
        if event.kind == DomainEventKind.transcript_updated and event.payload.get("role") == "agent_delta":
            await sse_manager.broadcast_domain_event(event)
            return

        # System-level events (no job association) cannot be persisted to the
        # events table (job_id FK constraint). Broadcast only.
        if event.job_id is None:
            await sse_manager.broadcast_domain_event(event)
            return

        try:
            await _persist_event_with_retry(
                event=event,
                session_factory=session_factory,
                write_lock=persist_lock,
            )
        except OperationalError:
            log.error(
                "event_persist_failed_queued_for_retry",
                event_id=event.event_id,
                job_id=event.job_id,
                kind=event.kind.value,
            )
            dead_letter.put_nowait((event, 0))
            # Broadcast anyway so the SSE stream doesn't silently drop the
            # event; the client will get it without a db_id which means the
            # replay cursor won't cover it, but it's better than silence.
            await sse_manager.broadcast_domain_event(event)
            return
        await sse_manager.broadcast_domain_event(event)

    async def _dead_letter_retry_loop() -> None:
        """Background task: retry persisting events that failed initially."""
        while True:
            try:
                event, attempt = await asyncio.wait_for(dead_letter.get(), timeout=_DEAD_LETTER_RETRY_INTERVAL_S)
            except TimeoutError:
                continue  # normal wait_for timeout — poll again
            except asyncio.CancelledError:
                return

            try:
                await _persist_event_with_retry(
                    event=event,
                    session_factory=session_factory,
                    write_lock=persist_lock,
                )
                log.info(
                    "dead_letter_event_persisted",
                    event_id=event.event_id,
                    job_id=event.job_id,
                    retry_attempt=attempt + 1,
                )
            except OperationalError:
                next_attempt = attempt + 1
                if next_attempt < _DEAD_LETTER_MAX_RETRIES:
                    dead_letter.put_nowait((event, next_attempt))
                    log.warning(
                        "dead_letter_retry_failed",
                        event_id=event.event_id,
                        job_id=event.job_id,
                        attempt=next_attempt,
                    )
                else:
                    log.error(
                        "dead_letter_event_permanently_lost",
                        event_id=event.event_id,
                        job_id=event.job_id,
                        kind=event.kind.value,
                    )

    event_bus.subscribe(_persist_and_broadcast)

    # Step persistence subscriber — persists step_started/step_completed events
    step_repo = StepRepository(session_factory)
    step_persistence = StepPersistenceSubscriber(step_repo)
    event_bus.subscribe(step_persistence)

    retry_task = asyncio.create_task(_dead_letter_retry_loop(), name="dead-letter-retry")
    return event_bus, sse_manager, retry_task


def _is_sqlite_lock_error(exc: OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


async def _persist_event_with_retry(
    *,
    event: DomainEvent,
    session_factory: async_sessionmaker[AsyncSession],
    write_lock: asyncio.Lock,
    max_attempts: int = _EVENT_PERSIST_MAX_ATTEMPTS,
    retry_delay_s: float = _EVENT_PERSIST_RETRY_DELAY_S,
) -> None:
    async with write_lock:
        for attempt in range(max_attempts):
            async with session_factory() as session:
                repo = EventRepository(session)
                try:
                    await repo.append(event)
                    await session.commit()
                    return
                except OperationalError as exc:
                    await session.rollback()
                    if not _is_sqlite_lock_error(exc) or attempt == max_attempts - 1:
                        raise
                    log.warning(
                        "event_persist_retrying_after_sqlite_lock",
                        event_id=event.event_id,
                        job_id=event.job_id,
                        attempt=attempt + 1,
                    )
            await asyncio.sleep(retry_delay_s * (attempt + 1))


async def _wire_core_services(
    session_factory: async_sessionmaker[AsyncSession],
    event_bus: EventBus,
    config: CPLConfig,
    coderecon_service: CodeReconService | None = None,
) -> _CoreServices:
    """Instantiate and wire together the core application services."""
    approval_service = ApprovalService(session_factory=session_factory)
    adapter_registry = AdapterRegistry(
        approval_service=approval_service,
        event_bus=event_bus,
        session_factory=session_factory,
    )
    git_service = GitService(config)
    diff_service = DiffService(git_service=git_service, event_bus=event_bus)
    platform_registry = PlatformRegistry(platform_configs=config.platforms)
    merge_service = MergeService(
        git_service=git_service,
        event_bus=event_bus,
        session_factory=session_factory,
        config=config.completion,
        platform_registry=platform_registry,
        diff_service=diff_service,
    )

    # --- Sister session manager (per-job dedicated utility sessions) ---
    utility_adapter = adapter_registry.get_adapter(config.runtime.default_sdk)
    sister_sessions = SisterSessionManager(
        adapter=utility_adapter,
        model=config.runtime.utility_model,
    )
    log.debug("sister_sessions_starting", model=config.runtime.utility_model, sdk=config.runtime.default_sdk)
    await sister_sessions.start()

    summarization_service = SummarizationService(
        session_factory=session_factory,
        adapter=sister_sessions,
    )

    # Plan-step orchestration is now handled by TrailService (unified timeline)
    # ProgressTrackingService has been retired.

    runtime_service = RuntimeService(
        session_factory=session_factory,
        event_bus=event_bus,
        adapter_registry=adapter_registry,
        config=config,
        approval_service=approval_service,
        diff_service=diff_service,
        git_service=git_service,
        merge_service=merge_service,
        summarization_service=summarization_service,
        platform_registry=platform_registry,
        sister_sessions=sister_sessions,
        step_tracker=StepTracker(
            event_bus=event_bus,
            git_service=git_service,
        ),
        coderecon_service=coderecon_service,
    )

    # Recover orphaned jobs from a previous crash
    await runtime_service.recover_on_startup()

    return _CoreServices(
        approval_service=approval_service,
        adapter_registry=adapter_registry,
        platform_registry=platform_registry,
        merge_service=merge_service,
        sister_sessions=sister_sessions,
        runtime_service=runtime_service,
        git_service=git_service,
        diff_service=diff_service,
    )


@dataclass(frozen=True)
class _OptionalServices:
    """Bundle of optional services and background handles for shutdown."""

    terminal_service: TerminalService | None
    retention_task: asyncio.Task[None]
    mcp_task: asyncio.Task[None]
    mcp_stop_event: asyncio.Event
    voice_service: VoiceService
    voice_max_bytes: int
    cached_models_by_sdk: dict[str, list[dict[str, object]]]


async def _init_optional_services(
    app: FastAPI,
    config: CPLConfig,
    session_factory: async_sessionmaker[AsyncSession],
    services: _CoreServices,
) -> _OptionalServices:
    """Initialise terminal, voice, retention, model cache, and MCP services."""

    # --- Terminal service ---
    terminal_service = None
    if config.terminal.enabled:
        terminal_service = TerminalService(
            max_sessions=config.terminal.max_sessions,
            default_shell=config.terminal.default_shell,
            scrollback_size_kb=config.terminal.scrollback_size_kb,
        )
        services.runtime_service.set_terminal_service(terminal_service)
        log.debug("terminal_service_enabled", max_sessions=config.terminal.max_sessions)

    # --- Model list cache ---
    # Fetch once at startup so the job-creation form renders instantly.
    # Models are keyed by SDK id so the frontend can fetch per-SDK.
    cached_models_by_sdk: dict[str, list[dict[str, object]]] = {}

    # Copilot models — retry up to 3 times since auth tokens may not be ready immediately
    copilot_models: list[dict[str, object]] = []
    for _attempt in range(3):
        try:
            from copilot import CopilotClient

            _model_client = CopilotClient()
            await _model_client.start()
            try:
                copilot_models = [m.to_dict() for m in await _model_client.list_models()]
                log.debug("copilot_models_cached", count=len(copilot_models))
            finally:
                await _model_client.stop()
            break  # success
        except Exception as exc:
            if _attempt < 2:
                log.debug("copilot_model_cache_retry", attempt=_attempt + 1, error=str(exc))
                await asyncio.sleep(2)
            else:
                log.warning("copilot_model_cache_failed", error=str(exc))
    cached_models_by_sdk["copilot"] = copilot_models

    # Claude Code models — loaded from data/claude_models.json
    _claude_models_path = Path(__file__).resolve().parent / "data" / "claude_models.json"
    try:
        import json as _json

        cached_models_by_sdk["claude"] = _json.loads(_claude_models_path.read_text())
        log.debug("claude_models_loaded", count=len(cached_models_by_sdk["claude"]))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("claude_models_load_failed", error=str(exc))
        cached_models_by_sdk["claude"] = []

    # --- Voice service ---
    voice_service = VoiceService()
    # Pre-load the whisper model at startup so the first request is fast
    log.debug("voice_model_preloading", model="base.en")
    await asyncio.to_thread(voice_service._ensure_model)  # noqa: SLF001
    voice_max_bytes = VOICE_MAX_AUDIO_SIZE_MB * 1024 * 1024

    # --- Retention service ---
    retention_service = RetentionService(
        session_factory=session_factory,
        config=config,
    )

    if config.retention.cleanup_on_startup:
        await retention_service.run_cleanup()

    # Start daily retention background task
    retention_task = asyncio.create_task(
        retention_service.daily_loop(),
        name="retention-daily",
    )

    # --- MCP server ---
    #
    # The MCP SDK's streamable_http_app() returns a Starlette app whose lifespan
    # calls session_manager.run() — an anyio task group context manager.  When
    # FastAPI mounts this sub-app it merges the sub-app lifespan into the parent
    # chain.  Because FastAPI's merged lifespan yields (to let the app serve),
    # the anyio task-group scope ends up being entered and exited in different
    # task contexts, causing:
    #
    #   RuntimeError: Attempted to exit cancel scope in a different task
    #
    # Fix: wrap the sub-app in an ASGI middleware that intercepts lifespan
    # events (standard ASGI protocol), preventing the sub-app's own lifespan
    # from firing.  We then manage session_manager.run() ourselves in a
    # dedicated asyncio task where the anyio scope stays within one task.
    #
    from backend.mcp.server import create_mcp_server

    mcp_server = create_mcp_server(
        session_factory=session_factory,
        runtime_service=services.runtime_service,
        approval_service=services.approval_service,
        sister_sessions=services.sister_sessions,
    )
    mcp_app = mcp_server.streamable_http_app()

    class _StripLifespan:
        """ASGI wrapper that handles lifespan events as no-ops.

        All HTTP/WebSocket scopes pass through to the wrapped app unchanged.
        Lifespan scopes are acknowledged immediately without delegating to the
        wrapped app, preventing it from running its own lifespan logic.
        """

        __slots__ = ("_app",)

        def __init__(self, wrapped_app: Any) -> None:
            self._app = wrapped_app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] == "lifespan":
                await receive()  # lifespan.startup
                await send({"type": "lifespan.startup.complete"})
                await receive()  # lifespan.shutdown
                await send({"type": "lifespan.shutdown.complete"})
                return
            await self._app(scope, receive, send)

    app.mount(MCP_PATH, _StripLifespan(mcp_app))

    # Run the session manager in a dedicated asyncio task.  This keeps the
    # anyio task-group scope entirely within one task for its full lifetime.
    mcp_stop_event = asyncio.Event()
    mcp_started_event = asyncio.Event()

    async def _run_mcp_session_manager() -> None:
        async with mcp_server.session_manager.run():
            mcp_started_event.set()
            await mcp_stop_event.wait()

    mcp_task = asyncio.create_task(_run_mcp_session_manager(), name="mcp-session-mgr")
    await mcp_started_event.wait()
    log.debug("mcp_server_mounted", path=MCP_PATH)

    return _OptionalServices(
        terminal_service=terminal_service,
        retention_task=retention_task,
        mcp_task=mcp_task,
        mcp_stop_event=mcp_stop_event,
        voice_service=voice_service,
        voice_max_bytes=voice_max_bytes,
        cached_models_by_sdk=cached_models_by_sdk,
    )


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage engine lifecycle — create on startup, dispose on shutdown."""
    from backend.services.telemetry import init_telemetry

    init_telemetry()

    engine = create_engine()
    session_factory = create_session_factory(engine)

    event_bus, sse_manager, dead_letter_task = _init_event_infrastructure(session_factory)

    # Wire the console dashboard (present only when stderr is an interactive TTY)
    # to the event bus so job state and progress updates appear in the live panel.
    dashboard = getattr(app.state, "dashboard", None)
    if dashboard is not None:
        event_bus.subscribe(dashboard.handle_event)

    config = load_config()

    # --- CodeRecon structural analysis service ---
    coderecon_service = CodeReconService(
        binary=config.coderecon.binary,
        home=config.coderecon.home,
    )
    coderecon_service.set_event_bus(event_bus)

    services = await _wire_core_services(session_factory, event_bus, config, coderecon_service)

    optional = await _init_optional_services(
        app,
        config,
        session_factory,
        services,
    )

    # --- Push notification service ---
    vapid_keys = get_or_create_vapid_keys(get_codeplane_dir())
    push_service = PushService(
        vapid_private_key=vapid_keys["private_key"],
        vapid_public_key=vapid_keys["public_key"],
    )

    async def _push_subscriber(event: DomainEvent) -> None:
        """Send push notifications for approval requests and terminal job states."""
        if event.kind == DomainEventKind.approval_requested:
            desc = event.payload.get("description", "Action requires your approval")
            await push_service.notify(
                title="Approval needed",
                body=str(desc),
                tag=f"approval-{event.payload.get('approval_id', event.job_id)}",
                url=f"/jobs/{event.job_id}",
            )
        elif event.kind == DomainEventKind.job_completed:
            await push_service.notify(
                title="Job completed",
                body=str(event.payload.get("resolution", "done")),
                tag=f"job-{event.job_id}",
                url=f"/jobs/{event.job_id}",
            )
        elif event.kind == DomainEventKind.job_failed:
            reason = event.payload.get("reason", "unknown error")
            await push_service.notify(
                title="Job failed",
                body=str(reason),
                tag=f"job-{event.job_id}",
                url=f"/jobs/{event.job_id}",
            )

    event_bus.subscribe(_push_subscriber)

    # --- Motivation summarization service (background) ---
    from backend.services.motivation_service import MotivationService

    motivation_service = MotivationService(
        session_factory=session_factory,
        completer=services.sister_sessions,
    )
    motivation_task = asyncio.create_task(
        motivation_service.drain_loop(), name="motivation-drain"
    )

    # --- Trail service (agent audit trail) ---
    from backend.services.trail import TrailService

    trail_service = TrailService(
        session_factory=session_factory,
        event_bus=event_bus,
        sister_sessions=services.sister_sessions,
        config=config.trail,
    )
    event_bus.subscribe(trail_service.handle_event)
    services.runtime_service.set_trail_service(trail_service)
    trail_task = asyncio.create_task(
        trail_service.drain_loop(), name="trail-enrichment-drain"
    )

    # --- CodeRecon start (instantiated earlier, before _wire_core_services) ---
    if config.coderecon.enabled:
        await coderecon_service.start()

    # Structural health subscriber — emits warnings at step boundaries (§7.2)
    async def _structural_health_on_step(event: DomainEvent) -> None:
        if event.kind != DomainEventKind.step_completed:
            return
        if not coderecon_service.available:
            return
        worktree_path = event.payload.get("worktree_path")
        if not worktree_path:
            return
        job_id = event.job_id

        async def _run_check() -> None:
            try:
                # Look up repo path from the job record
                from sqlalchemy import text

                async with session_factory() as session:
                    row = await session.execute(
                        text("SELECT repo FROM jobs WHERE id = :jid"),
                        {"jid": job_id},
                    )
                    repo_path = row.scalar_one_or_none()
                if not repo_path:
                    return

                # Resolve repo name via git_dir (same pattern as _cleanup_job_state)
                catalog = await coderecon_service.catalog()
                resolved = Path(repo_path).resolve()
                repo_name = next(
                    (e["name"] for e in catalog
                     if Path(e.get("git_dir", "")).resolve() in (resolved / ".git", resolved)),
                    None,
                )
                if not repo_name:
                    return
                warnings = await coderecon_service.check_step_structural_health(
                    repo_name, worktree=worktree_path
                )
                for w in warnings:
                    await event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=job_id,
                            timestamp=datetime.now(UTC),
                            kind=DomainEventKind.structural_warning,
                            payload=w,
                        )
                    )
            except Exception:
                log.debug("structural_health_check_failed", job_id=job_id, exc_info=True)

        # Fire-and-forget — don't block the event pipeline
        _fire_and_forget(_run_check(), name=f"structural-health-{job_id[:8]}")

    event_bus.subscribe(_structural_health_on_step)

    # Review story prefetch subscriber — pre-generates and caches review story
    # when a job enters review state so the frontend load is instant.
    async def _prefetch_review_story(event: DomainEvent) -> None:
        if event.kind != DomainEventKind.job_review:
            return
        if not coderecon_service.available:
            return
        job_id = event.job_id

        async def _run_prefetch() -> None:
            try:
                from backend.api.job_artifacts import _generate_review_story, _cache_put

                async with session_factory() as session:
                    from sqlalchemy import text

                    row = await session.execute(
                        text("SELECT repo, worktree_path, base_ref, title, prompt FROM jobs WHERE id = :jid"),
                        {"jid": job_id},
                    )
                    job_row = row.one_or_none()
                if not job_row:
                    return

                job_like = _JobLike(job_row)
                result = await _generate_review_story(job_id, job_like, coderecon_service)

                # Cache the result using latest end_sha
                step_repo_local = StepRepository(session_factory)
                all_steps = await step_repo_local.get_by_job(job_id)
                sha = None
                for step in reversed(all_steps):
                    if step.end_sha:
                        sha = step.end_sha
                        break
                _cache_put(job_id, "review-story", sha, result)
                log.debug("review_story_prefetched", job_id=job_id)
            except Exception:
                log.debug("review_story_prefetch_failed", job_id=job_id, exc_info=True)

        _fire_and_forget(_run_prefetch(), name=f"review-story-prefetch-{job_id[:8]}")

    event_bus.subscribe(_prefetch_review_story)

    # --- §11.11 Persist review story as approval artifact on merge ---
    async def _persist_review_story_on_resolve(event: DomainEvent) -> None:
        if event.kind != DomainEventKind.job_resolved:
            return
        resolution = event.payload.get("resolution")
        if resolution not in ("merged", "pr_created", "smart_merged"):
            return
        if not coderecon_service.available:
            return
        job_id = event.job_id

        async def _run_persist() -> None:
            try:
                import hashlib

                from backend.api.job_artifacts import _generate_review_story

                async with session_factory() as session:
                    from sqlalchemy import text

                    row = await session.execute(
                        text("SELECT repo, worktree_path, base_ref, title, prompt FROM jobs WHERE id = :jid"),
                        {"jid": job_id},
                    )
                    job_row = row.one_or_none()
                if not job_row:
                    return

                job_like = _JobLike(job_row)
                result = await _generate_review_story(job_id, job_like, coderecon_service)

                story_json = result.model_dump_json()
                story_hash = hashlib.sha256(story_json.encode()).hexdigest()

                async with session_factory() as session:
                    await session.execute(
                        text(
                            "UPDATE jobs SET review_story_json = :story, review_story_hash = :hash "
                            "WHERE id = :jid"
                        ),
                        {"story": story_json, "hash": story_hash, "jid": job_id},
                    )
                    await session.commit()
                log.debug("review_story_persisted", job_id=job_id)
            except Exception:
                log.debug("review_story_persist_failed", job_id=job_id, exc_info=True)

        _fire_and_forget(_run_persist(), name=f"review-story-persist-{job_id[:8]}")

    event_bus.subscribe(_persist_review_story_on_resolve)

    # --- §7.5 Post-resolution structural analytics ---
    async def _persist_structural_analytics(event: DomainEvent) -> None:
        if event.kind != DomainEventKind.job_resolved:
            return
        resolution = event.payload.get("resolution")
        if resolution not in ("merged", "pr_created", "smart_merged"):
            return
        if not coderecon_service.available:
            return
        job_id = event.job_id

        async def _run_analytics() -> None:
            try:
                from sqlalchemy import text

                async with session_factory() as session:
                    row = await session.execute(
                        text("SELECT repo, worktree_path, base_ref FROM jobs WHERE id = :jid"),
                        {"jid": job_id},
                    )
                    job_row = row.one_or_none()
                if not job_row:
                    return

                repo_path, worktree_path, base_ref = job_row[0], job_row[1], job_row[2]
                if not repo_path or not worktree_path:
                    return

                repo_name = await coderecon_service.ensure_repo_indexed(repo_path)

                # Structural diff for change count and confidence
                diff_result = await coderecon_service.semantic_diff(
                    repo_name, base=base_ref or "HEAD", worktree=worktree_path,
                )
                change_count = len(diff_result.structural_changes)
                merge_confidence = getattr(diff_result, "merge_confidence", None)

                # Did any structural changes touch test files?
                changes_touch_tests = any(
                    c.get("file", "").startswith("test") or "/test" in c.get("file", "")
                    for c in diff_result.structural_changes
                )

                # Cycle count in worktree
                cycle_count = 0
                try:
                    cycles = await coderecon_service.graph_cycles(repo_name, worktree=worktree_path)
                    cycle_count = len(cycles.cycles) if cycles.cycles else 0
                except Exception:
                    pass

                # Cross-community coupling delta
                coupling_delta: float | None = None
                try:
                    communities = await coderecon_service.graph_communities(repo_name, worktree=worktree_path)
                    touched: set[str] = set()
                    for c in diff_result.structural_changes:
                        file_path = c.get("file", "")
                        for comm in communities.communities:
                            if file_path in comm.get("members", []):
                                touched.add(comm.get("name", ""))
                    # Coupling delta = communities touched / total communities (0-1 scale)
                    total = len(communities.communities) if communities.communities else 1
                    coupling_delta = len(touched) / total
                except Exception:
                    pass

                async with session_factory() as session:
                    await session.execute(
                        text(
                            "UPDATE jobs SET "
                            "structural_change_count = :cc, "
                            "structural_cycle_count = :cyc, "
                            "structural_changes_touch_tests = :tc, "
                            "structural_coupling_delta = :cd, "
                            "structural_merge_confidence = :mc "
                            "WHERE id = :jid"
                        ),
                        {
                            "cc": change_count,
                            "cyc": cycle_count,
                            "tc": changes_touch_tests,
                            "cd": coupling_delta,
                            "mc": merge_confidence,
                            "jid": job_id,
                        },
                    )
                    await session.commit()
                log.debug("structural_analytics_persisted", job_id=job_id, changes=change_count)
            except Exception:
                log.debug("structural_analytics_failed", job_id=job_id, exc_info=True)

        _fire_and_forget(_run_analytics(), name=f"struct-analytics-{job_id[:8]}")

    event_bus.subscribe(_persist_structural_analytics)

    # --- IngestService (CLI session import) ---
    from backend.services.ingest_service import IngestService

    steer_client = None
    copilot_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if copilot_token:
        from backend.services.copilot_steer import CopilotSteerClient
        steer_client = CopilotSteerClient(copilot_token)

    ingest_service = IngestService(
        event_bus=event_bus,
        session_factory=session_factory,
        config=config,
        git_service=services.git_service,
        diff_service=services.diff_service,
        merge_service=services.merge_service,
        trail_service=trail_service,
        coderecon_service=coderecon_service,
        steer_client=steer_client,
    )

    # --- OtelFileWatcher (Copilot OTEL file tail) ---
    otel_watcher = None
    if config.copilot_otel_path:
        from backend.services.otel_file_watcher import OtelFileWatcher
        otel_watcher = OtelFileWatcher(config.copilot_otel_path, ingest_service)
        await otel_watcher.start()

    # --- Share service ---
    share_service = ShareService()

    # Build the dishka DI container with all services as context values
    container = make_async_container(
        AppProvider(),
        RequestProvider(),
        context={
            CPLConfig: config,
            async_sessionmaker: session_factory,
            EventBus: event_bus,
            SSEManager: sse_manager,
            ApprovalService: services.approval_service,
            RuntimeService: services.runtime_service,
            MergeService: services.merge_service,
            PlatformRegistry: services.platform_registry,
            SisterSessionManager: services.sister_sessions,
            VoiceService: optional.voice_service,
            CachedModelsBySdk: CachedModelsBySdk(optional.cached_models_by_sdk),
            VoiceMaxBytes: VoiceMaxBytes(optional.voice_max_bytes),
            PushService: push_service,
            ShareService: share_service,
            TrailService: trail_service,
            TerminalService: optional.terminal_service,
            CodeReconService: coderecon_service,
            IngestService: ingest_service,
        },
    )
    app.state.dishka_container = container

    # Activate the Rich live display — connection info is shown
    # persistently in the dashboard header.  Print the QR code once
    # before the live display takes over the terminal.
    banner_args = getattr(app.state, "banner_args", None)
    if banner_args:
        tunnel_url = banner_args.get("tunnel_url")
        local_url = f"http://{banner_args.get('host', '127.0.0.1')}:{banner_args.get('port', 8080)}"
        _print_qr_code(tunnel_url or local_url)
    if dashboard is not None:
        if banner_args:
            host = banner_args.get("host", "127.0.0.1")
            port = banner_args.get("port", 8080)
            dashboard.set_server_info(
                server_url=f"http://{host}:{port}",
                tunnel_url=banner_args.get("tunnel_url"),
                password=banner_args.get("password"),
            )
        dashboard.start()

    yield

    # Shutdown in reverse initialisation order.
    # Stop the live dashboard first so subsequent log output prints cleanly.
    if dashboard is not None:
        dashboard.stop()
    await container.close()
    optional.mcp_stop_event.set()
    await optional.mcp_task
    optional.retention_task.cancel()
    motivation_task.cancel()
    trail_task.cancel()
    dead_letter_task.cancel()
    if optional.terminal_service is not None:
        await optional.terminal_service.shutdown()
    # Stop OtelFileWatcher and steer client
    if otel_watcher is not None:
        await otel_watcher.stop()
    if steer_client is not None:
        await steer_client.close()
    # Drain any in-flight ephemeral background tasks before tearing down services.
    if _ephemeral_tasks:
        await asyncio.gather(*_ephemeral_tasks, return_exceptions=True)
    await coderecon_service.stop()
    await services.sister_sessions.shutdown()
    await services.runtime_service.shutdown()
    sse_manager.close_all()
    await engine.dispose()
