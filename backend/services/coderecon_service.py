"""CodeRecon integration — structural analysis via the CodeRecon daemon.

Wraps the CodeRecon SDK. Manages daemon lifecycle and provides structural
diff, reference analysis, and repository health queries for the review
dashboard and agent tool provisioning.
"""

from __future__ import annotations

import asyncio
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
        ImpactResult,
        MapResult,
        ReconResult,
        StatusResult,
    )

log = structlog.get_logger(__name__)


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

    @property
    def state(self) -> DaemonState:
        return self._state

    @property
    def available(self) -> bool:
        return self._state == DaemonState.READY

    # ── Lifecycle ──

    async def start(self) -> None:
        """Spawn the daemon. Blocks until ready."""
        from coderecon.sdk.client import CodeRecon

        self._state = DaemonState.STARTING
        try:
            self._sdk = CodeRecon(binary=self._binary, home=self._home)
            await self._sdk.start()
            self._state = DaemonState.READY
            self._restart_count = 0
            log.info("coderecon.daemon_started")
        except Exception:
            self._state = DaemonState.DEGRADED
            log.warning("coderecon.start_failed", exc_info=True)

    async def stop(self) -> None:
        """Graceful shutdown of the daemon."""
        if self._sdk is not None:
            try:
                await self._sdk.stop()
            except Exception:
                log.debug("coderecon.stop_error", exc_info=True)
            self._sdk = None
        self._state = DaemonState.STOPPED
        log.info("coderecon.daemon_stopped")

    async def _ensure_available(self) -> CodeRecon:
        """Return the SDK handle or raise if unavailable."""
        if self._sdk is None or self._state != DaemonState.READY:
            raise CodeReconUnavailableError
        return self._sdk

    # ── Repository Management ──

    async def register_repo(self, path: str | Path) -> dict[str, Any]:
        """Register a repository for structural indexing."""
        sdk = await self._ensure_available()
        result = await sdk.register(str(path))
        log.info("coderecon.repo_registered", repo=result.repo)
        return {"repo": result.repo}

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

    # ── Agent Tool Provisioning ──

    def get_agent_tools(
        self,
        repo: str,
        *,
        worktree: str | None = None,
        framework: str = "openai",
    ) -> list[dict[str, Any]]:
        """Return tool definitions for agent integration.

        Args:
            repo: Repository name.
            worktree: Optional worktree scope.
            framework: 'openai' or 'langchain'.
        """
        if self._sdk is None or self._state != DaemonState.READY:
            return []
        if framework == "langchain":
            return self._sdk.as_langchain_tools(repo, worktree=worktree)
        return self._sdk.as_openai_tools(repo, worktree=worktree)

    # ── Health ──

    async def daemon_health(self) -> dict[str, Any]:
        """Return daemon health status."""
        return {
            "state": self._state.value,
            "restart_count": self._restart_count,
        }


class CodeReconUnavailableError(Exception):
    """Raised when the CodeRecon daemon is not available."""

    def __init__(self) -> None:
        super().__init__("CodeRecon daemon is not available")
