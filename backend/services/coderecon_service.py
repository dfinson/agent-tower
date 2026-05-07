"""CodeRecon integration — structural analysis via the CodeRecon daemon.

Wraps the CodeRecon SDK. Manages daemon lifecycle and provides structural
diff, reference analysis, and repository health queries for the review
dashboard and agent tool provisioning.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from coderecon.sdk.client import CodeRecon
    from coderecon.sdk.types import (
        CommunitiesResult,
        CyclesResult,
        DiffResult,
        Event,
        ImpactResult,
        MapResult,
        ReconResult,
        StatusResult,
    )

    from backend.services.event_bus import EventBus

log = structlog.get_logger(__name__)

# Crash recovery constants (§4.3)
_MAX_RESTART_BACKOFF_S = 30.0
_DEGRADED_THRESHOLD = 3  # crashes within window → degraded
_DEGRADED_WINDOW_S = 60.0


class DaemonState(Enum):
    """Daemon lifecycle state."""

    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"


class CodeReconService:
    """Wraps the CodeRecon SDK. Manages daemon lifecycle and repo handles.

    This is the single integration surface between CodePlane and CodeRecon.
    No other service imports the SDK or speaks to the daemon directly.
    """

    def __init__(self, *, binary: str | None = None, home: str | Path | None = None) -> None:
        self._binary = binary
        self._home = home
        self._sdk: CodeRecon | None = None
        self._state = DaemonState.STOPPED
        self._restart_count = 0
        self._restart_lock = asyncio.Lock()
        self._event_bus: EventBus | None = None
        self._event_bridge_task: asyncio.Task[None] | None = None
        self._crash_timestamps: list[float] = []
        self._restart_task: asyncio.Task[None] | None = None
        self._shutting_down = False

    @property
    def state(self) -> DaemonState:
        return self._state

    @property
    def available(self) -> bool:
        return self._state == DaemonState.READY

    def set_event_bus(self, event_bus: EventBus) -> None:
        """Connect the event bus for forwarding index progress to SSE."""
        self._event_bus = event_bus

    # ── Lifecycle ──

    async def start(self) -> None:
        """Spawn the daemon. Blocks until ready."""
        from coderecon.sdk.client import CodeRecon

        self._shutting_down = False
        self._state = DaemonState.STARTING
        try:
            self._sdk = CodeRecon(binary=self._binary, home=self._home)
            await self._sdk.start()
            self._state = DaemonState.READY
            self._restart_count = 0
            self._crash_timestamps.clear()
            self._event_bridge_task = asyncio.create_task(
                self._bridge_events(), name="coderecon-event-bridge"
            )
            log.info("coderecon.daemon_started")
        except Exception:
            self._state = DaemonState.DEGRADED
            log.warning("coderecon.start_failed", exc_info=True)

    async def stop(self) -> None:
        """Graceful shutdown of the daemon."""
        self._shutting_down = True
        if self._restart_task is not None:
            self._restart_task.cancel()
            self._restart_task = None
        if self._event_bridge_task is not None:
            self._event_bridge_task.cancel()
            self._event_bridge_task = None
        if self._sdk is not None:
            try:
                await self._sdk.stop()
            except Exception:
                log.debug("coderecon.stop_error", exc_info=True)
            self._sdk = None
        self._state = DaemonState.STOPPED
        log.info("coderecon.daemon_stopped")

    async def _handle_crash(self) -> None:
        """Handle a daemon crash — schedule restart with backoff (§4.3).

        If 3+ crashes within 60s, enter degraded mode permanently (until
        manual restart via stop/start).
        """
        now = time.monotonic()
        self._crash_timestamps.append(now)
        # Prune timestamps outside the window
        self._crash_timestamps = [
            t for t in self._crash_timestamps if now - t < _DEGRADED_WINDOW_S
        ]

        if len(self._crash_timestamps) >= _DEGRADED_THRESHOLD:
            self._state = DaemonState.DEGRADED
            log.error(
                "coderecon.degraded_mode",
                crashes_in_window=len(self._crash_timestamps),
            )
            return

        self._restart_count += 1
        backoff = min(2 ** (self._restart_count - 1), _MAX_RESTART_BACKOFF_S)
        log.warning(
            "coderecon.scheduling_restart",
            restart_count=self._restart_count,
            backoff_s=backoff,
        )
        self._state = DaemonState.STARTING
        self._restart_task = asyncio.create_task(
            self._restart_after(backoff), name="coderecon-restart"
        )

    async def _restart_after(self, delay: float) -> None:
        """Wait then restart the daemon."""
        try:
            await asyncio.sleep(delay)
            if self._shutting_down:
                return
            await self.start()
        except asyncio.CancelledError:
            pass
        except Exception:
            self._state = DaemonState.DEGRADED
            log.error("coderecon.restart_failed", exc_info=True)

    async def _ensure_available(self) -> CodeRecon:
        """Return the SDK handle or raise if unavailable."""
        if self._sdk is None or self._state != DaemonState.READY:
            raise CodeReconUnavailableError
        return self._sdk

    # ── Repository Management ──

    async def register_repo(self, path: str | Path) -> dict[str, Any]:
        """Register a repository for structural indexing.

        Triggers a full index build. Progress events are forwarded to the
        event bus as repo_index_progress SSE events so the frontend can
        show progress UI during onboarding.
        """
        sdk = await self._ensure_available()
        result = await sdk.register(str(path))
        log.info("coderecon.repo_registered", repo=result.repo)
        return {"repo": result.repo}

    async def ensure_repo_indexed(self, path: str | Path) -> str:
        """Register a repo if not already known. Returns repo name.

        This is the primary hook for the repo-add flow. Onboarded repos
        are always indexed — this is not optional.
        """
        sdk = await self._ensure_available()
        # Check if already registered
        entries = await sdk.catalog()
        resolved = str(Path(path).resolve())
        for entry in entries:
            if Path(entry.git_dir).resolve() == Path(resolved) / ".git" or Path(entry.git_dir).resolve() == Path(resolved):
                return entry.name
        # Not registered — register now (triggers indexing)
        result = await sdk.register(resolved)
        log.info("coderecon.repo_registered", repo=result.repo, path=resolved)
        return result.repo

    async def register_worktree(self, repo: str, worktree_path: str | Path) -> None:
        """Register a worktree with the daemon to activate live reindexing.

        Called during job setup after the worktree is created. This tells
        the daemon to watch the worktree for file changes and maintain a
        live structural index as the agent writes code.

        Uses `reindex(repo, worktree=path)` which activates the worktree
        column key and triggers an initial index pass for the worktree state.
        """
        sdk = await self._ensure_available()
        await sdk.reindex(repo, worktree=str(worktree_path))
        log.info("coderecon.worktree_registered", repo=repo, worktree=str(worktree_path))

    async def repo_status(self, repo: str) -> StatusResult:
        """Get index status for a repo."""
        sdk = await self._ensure_available()
        return await sdk.status(repo)

    async def catalog(self) -> list[dict[str, Any]]:
        """List all registered repos."""
        sdk = await self._ensure_available()
        entries = await sdk.catalog()
        return [{"name": e.name, "git_dir": e.git_dir, "worktrees": e.worktrees} for e in entries]

    # ── Structural Analysis ──

    async def semantic_diff(
        self,
        repo: str,
        *,
        base: str = "HEAD",
        target: str | None = None,
        paths: list[str] | None = None,
        worktree: str | None = None,
        format: str = "structured",
    ) -> DiffResult:
        """Run structural diff between two states.

        Returns per-symbol change classification with impact data.
        Uses format='structured' by default for programmatic access to
        ref tiers, entity IDs, and impact metadata.
        """
        sdk = await self._ensure_available()
        return await sdk.semantic_diff(
            repo,
            base=base,
            target=target,
            paths=paths,
            worktree=worktree,
            format=format,
        )

    async def recon(
        self,
        repo: str,
        task: str,
        *,
        seeds: list[str] | None = None,
        pins: list[str] | None = None,
        worktree: str | None = None,
    ) -> ReconResult:
        """Task-aware context retrieval — ranked code spans."""
        sdk = await self._ensure_available()
        return await sdk.recon(repo, task, seeds=seeds, pins=pins, worktree=worktree)

    async def recon_impact(
        self,
        repo: str,
        target: str,
        justification: str,
        *,
        worktree: str | None = None,
    ) -> ImpactResult:
        """Reference/caller analysis for a symbol."""
        sdk = await self._ensure_available()
        return await sdk.recon_impact(repo, target, justification, worktree=worktree)

    async def recon_map(self, repo: str, *, worktree: str | None = None) -> MapResult:
        """Repository structure map."""
        sdk = await self._ensure_available()
        return await sdk.recon_map(repo, worktree=worktree)

    async def graph_communities(
        self, repo: str, *, worktree: str | None = None,
    ) -> CommunitiesResult:
        """Module community detection."""
        sdk = await self._ensure_available()
        return await sdk.graph_communities(repo, worktree=worktree)

    async def graph_cycles(
        self, repo: str, *, worktree: str | None = None,
    ) -> CyclesResult:
        """Circular dependency detection."""
        sdk = await self._ensure_available()
        return await sdk.graph_cycles(repo, worktree=worktree)

    async def scaffold(
        self,
        repo: str,
        *,
        path: str,
        worktree: str | None = None,
    ) -> dict[str, Any]:
        """File structural overview — imports + symbols without bodies."""
        sdk = await self._ensure_available()
        return await sdk.scaffold(repo, path=path, worktree=worktree)

    # ── Structural Feedback (§7.2) ──

    async def check_step_structural_health(
        self,
        repo: str,
        *,
        worktree: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run lightweight structural checks at step boundary.

        Returns a list of warnings (may be empty). Each warning has:
        - type: "new_cycles" | "community_drift"
        - detail: human-readable description
        - data: machine-readable payload
        """
        warnings: list[dict[str, Any]] = []

        # Check for new cycles
        try:
            worktree_cycles = await self.graph_cycles(repo, worktree=worktree)
            base_cycles = await self.graph_cycles(repo)
            base_keys = {frozenset(sorted(c.get("members", []))) for c in base_cycles.cycles}
            new_cycles = [
                c for c in worktree_cycles.cycles
                if frozenset(sorted(c.get("members", []))) not in base_keys
            ]
            if new_cycles:
                warnings.append({
                    "type": "new_cycles",
                    "detail": f"{len(new_cycles)} new dependency cycle(s) introduced",
                    "data": {"cycles": new_cycles},
                })
        except Exception:
            pass  # non-critical

        # Check community drift — if worktree touches 3+ unrelated communities
        try:
            diff = await self.semantic_diff(repo, worktree=worktree)
            touched_files = {c.get("file", "") for c in (diff.structural_changes or [])}
            if len(touched_files) >= 3:
                communities = await self.graph_communities(repo, worktree=worktree)
                # Map files to communities
                file_communities: set[str] = set()
                for comm in communities.communities:
                    comm_name = comm.get("name", "")
                    members = set(comm.get("members", []))
                    if touched_files & members:
                        file_communities.add(comm_name)
                if len(file_communities) >= 3:
                    warnings.append({
                        "type": "community_drift",
                        "detail": f"Changes span {len(file_communities)} unrelated module communities",
                        "data": {"communities": sorted(file_communities)},
                    })
        except Exception:
            pass  # non-critical

        return warnings

    # ── Session Lifecycle ──

    async def close_session(self, repo: str, worktree: str | None = None) -> None:
        """Close the daemon session for a (repo, worktree) pair.

        Called when a job completes to release session state in the daemon.
        """
        sdk = await self._ensure_available()
        await sdk.close_session(repo, worktree=worktree)
        log.info("coderecon.session_closed", repo=repo, worktree=worktree)

    # ── Agent Tool Provisioning ──

    # Tool tier definitions — which tools are included at each level.
    _TIER_MINIMAL = frozenset({"recon", "recon_map", "scaffold"})
    _TIER_STANDARD = _TIER_MINIMAL | frozenset({"checkpoint", "recon_impact"})
    _TIER_FULL: frozenset[str] | None = None  # None = all tools, no filtering

    def get_agent_tools(
        self,
        repo: str,
        *,
        worktree: str | None = None,
        tier: str = "standard",
        framework: str = "openai",
    ) -> list[dict[str, Any]]:
        """Return tool definitions for agent integration, filtered by tier.

        Tiers:
            minimal: recon + recon_map + scaffold (read-only context)
            standard: minimal + checkpoint + recon_impact (structural awareness)
            full: all 13 SDK tools (architectural work)
        """
        if self._sdk is None or self._state != DaemonState.READY:
            return []
        if framework == "langchain":
            tools = self._sdk.as_langchain_tools(repo, worktree=worktree)
        else:
            tools = self._sdk.as_openai_tools(repo, worktree=worktree)

        allowed = self._resolve_tier(tier)
        if allowed is None:
            return tools
        return [t for t in tools if self._tool_name(t, framework) in allowed]

    @staticmethod
    def _tool_name(tool: Any, framework: str) -> str | None:
        """Extract the tool name regardless of framework format."""
        if framework == "langchain":
            return getattr(tool, "name", None)
        return tool.get("function", {}).get("name")

    @classmethod
    def _resolve_tier(cls, tier: str) -> frozenset[str] | None:
        """Return allowed tool names for a tier, or None for full (no filter)."""
        if tier == "minimal":
            return cls._TIER_MINIMAL
        if tier == "standard":
            return cls._TIER_STANDARD
        return cls._TIER_FULL  # "full" or unknown → all tools

    # ── Health ──

    async def daemon_health(self) -> dict[str, Any]:
        """Return daemon health status."""
        return {
            "state": self._state.value,
            "restart_count": self._restart_count,
        }

    # ── Event Bridge ──

    async def _bridge_events(self) -> None:
        """Forward daemon index.progress events to CodePlane's event bus as SSE."""
        from backend.models.events import DomainEvent, DomainEventKind

        if self._sdk is None:
            return
        try:
            async for event in self._sdk.events("index.*"):
                if self._event_bus is None:
                    continue
                if event.type == "index.progress":
                    await self._event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=None,
                            timestamp=datetime.now(UTC),
                            kind=DomainEventKind.repo_index_progress,
                            payload={
                                "repo": event.data.get("repo", ""),
                                "indexed": event.data.get("indexed", 0),
                                "total": event.data.get("total", 0),
                                "phase": event.data.get("phase", "indexing"),
                            },
                        )
                    )
                elif event.type == "index.complete":
                    await self._event_bus.publish(
                        DomainEvent(
                            event_id=DomainEvent.make_event_id(),
                            job_id=None,
                            timestamp=datetime.now(UTC),
                            kind=DomainEventKind.repo_index_complete,
                            payload={
                                "repo": event.data.get("repo", ""),
                            },
                        )
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            log.warning("coderecon.event_bridge_crashed", exc_info=True)
            if not self._shutting_down:
                # Daemon likely crashed — trigger recovery
                self._sdk = None
                self._state = DaemonState.STARTING
                await self._handle_crash()


class CodeReconUnavailableError(Exception):
    """Raised when the CodeRecon daemon is not available."""

    def __init__(self) -> None:
        super().__init__("CodeRecon daemon is not available")
