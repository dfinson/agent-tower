"""CodeRecon Review integration — lightweight structural analysis.

Wraps ``coderecon.review.ReviewKit`` for structural diff, cycle detection,
community detection, and health scoring.  Runs in-process (no daemon, no
network) and is always enabled.  All heavy work (tree-sitter parsing,
graph building) happens in a thread pool so the async event loop is never
blocked.

Degrades gracefully: if the coderecon-review package is not installed or
if a repo fails to index, the ``available`` property returns ``False``
and every public method returns a safe fallback.
"""

from __future__ import annotations

import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from coderecon.index.diff.models import SemanticDiffResult
    from coderecon.review import (
        CommunitiesResult,
        CyclesResult,
        StructuralHealthResult,
    )

    from backend.services.event_bus import EventBus

log = structlog.get_logger(__name__)


class CodeReconService:
    """In-process structural analysis via coderecon-review's ReviewKit.

    Always-on, no config gating.  Indexes repos in the background on
    startup.  Thread-offloads all blocking operations.
    """

    def __init__(self) -> None:
        self._kits: dict[str, Any] = {}  # resolved_repo_path → ReviewKit
        self._index_locks: dict[str, asyncio.Lock] = {}
        self._available = False
        self._event_bus: EventBus | None = None
        self._kit_class: type | None = None
        self._init_error: str | None = None
        self._executor = ThreadPoolExecutor(thread_name_prefix="coderecon")

    # ── Properties ──

    @property
    def available(self) -> bool:
        return self._available

    def set_event_bus(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    # ── Lifecycle ──

    async def start(self) -> None:
        """Validate that the coderecon-review package is importable."""
        try:
            from coderecon.review import ReviewKit

            self._kit_class = ReviewKit
            self._available = True
            log.info("coderecon_review.ready")
        except ImportError as exc:
            self._init_error = str(exc)
            self._available = False
            log.warning("coderecon_review.import_failed", error=str(exc))

    async def stop(self) -> None:
        """Close all ReviewKit instances and release resources."""
        loop = asyncio.get_running_loop()
        for repo_path, kit in list(self._kits.items()):
            try:
                await loop.run_in_executor(self._executor, kit.close)
            except Exception:
                log.debug("coderecon_review.close_error", repo=repo_path, exc_info=True)
        self._kits.clear()
        self._index_locks.clear()
        self._executor.shutdown(wait=False)
        self._available = False
        log.info("coderecon_review.stopped")

    # ── Repository Management ──

    async def ensure_repo_indexed(self, path: str | Path) -> str:
        """Index a repo if not already indexed.  Returns the resolved path string.

        Uses per-path locking so concurrent callers don't duplicate work.
        The indexing (tree-sitter parse) is offloaded to a thread.
        """
        if not self._available or self._kit_class is None:
            raise CodeReconUnavailableError

        resolved = str(Path(path).resolve())
        loop = asyncio.get_running_loop()

        if resolved not in self._index_locks:
            self._index_locks[resolved] = asyncio.Lock()

        async with self._index_locks[resolved]:
            if resolved in self._kits:
                return resolved

            kit = self._kit_class(Path(resolved))
            try:
                await loop.run_in_executor(self._executor, kit.ensure_indexed)
            except Exception:
                log.warning("coderecon_review.index_failed", repo=resolved, exc_info=True)
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(self._executor, kit.close)
                raise

            self._kits[resolved] = kit
            log.info("coderecon_review.repo_indexed", repo=resolved)
            return resolved

    async def register_worktree(self, repo: str, worktree_path: str | Path) -> None:
        """Register a worktree with an already-indexed repo."""
        kit = self._kits.get(repo)
        if kit is None:
            return
        loop = asyncio.get_running_loop()
        try:
            wt_name = Path(worktree_path).name
            wt = str(Path(worktree_path).resolve())
            await loop.run_in_executor(self._executor, kit.register_worktree, wt_name, Path(wt))
            log.info("coderecon_review.worktree_registered", repo=repo, worktree=wt)
        except Exception:
            log.debug("coderecon_review.worktree_register_failed", repo=repo, exc_info=True)

    # ── Structural Analysis ──

    async def semantic_diff(
        self,
        repo: str,
        *,
        base: str = "HEAD",
        target: str | None = None,
        worktree: str | None = None,
        **_kwargs: Any,
    ) -> SemanticDiffResult:
        """Structural diff between two git states.

        Returns a SemanticDiffResult with typed StructuralChange objects.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"base": base}
        if target is not None:
            kwargs["target"] = target
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.semantic_diff(**kwargs))

    async def graph_cycles(
        self,
        repo: str,
        *,
        worktree: str | None = None,
    ) -> CyclesResult:
        """Circular dependency detection."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.graph_cycles(**kwargs))

    async def graph_communities(
        self,
        repo: str,
        *,
        worktree: str | None = None,
    ) -> CommunitiesResult:
        """Module community detection."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.graph_communities(**kwargs))

    async def check_structural_health(
        self,
        repo: str,
        *,
        worktree: str | None = None,
    ) -> StructuralHealthResult:
        """Composite structural health assessment."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.check_structural_health(**kwargs))

    async def impact(self, repo: str, target: str, *, worktree: str | None = None) -> Any:
        """Blast radius for a symbol or file path.

        Returns an ImpactResult with definition_sites, references,
        import_sites, and total_references.
        """
        kit = self._get_kit(repo)
        if not hasattr(kit, "impact"):
            raise CodeReconUnavailableError
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.impact(target, **kwargs))

    async def understand(
        self,
        repo: str,
        *,
        scope: str | None = None,
        worktree: str | None = None,
    ) -> Any:
        """Codebase orientation — languages, top files, top symbols, cycles, communities.

        Returns an UnderstandResult.
        """
        kit = self._get_kit(repo)
        if not hasattr(kit, "understand"):
            raise CodeReconUnavailableError
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {}
        if scope is not None:
            kwargs["scope"] = scope
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.understand(**kwargs))

    async def reindex(
        self,
        repo: str,
        changed_paths: list[str],
        *,
        worktree: str | None = None,
    ) -> int:
        """Re-index specific changed files. Returns count of files re-indexed."""
        kit = self._get_kit(repo)
        if not hasattr(kit, "reindex"):
            raise CodeReconUnavailableError
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"changed_paths": changed_paths}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.reindex(**kwargs))

    async def recon(
        self,
        repo: str,
        task: str,
        *,
        seeds: Any = None,
        pins: Any = None,
        worktree: str | None = None,
    ) -> Any:
        """Run coderecon recon analysis."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"task": task}
        if seeds is not None:
            kwargs["seeds"] = seeds
        if pins is not None:
            kwargs["pins"] = pins
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.recon(**kwargs))

    async def recon_map(self, repo: str, *, worktree: str | None = None) -> Any:
        """Run coderecon recon_map."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.recon_map(**kwargs))

    async def recon_impact(
        self,
        repo: str,
        target: str,
        justification: str,
        *,
        worktree: str | None = None,
    ) -> Any:
        """Run coderecon recon_impact."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"target": target, "justification": justification}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.recon_impact(**kwargs))

    async def scaffold(self, repo: str, *, path: str = "", worktree: str | None = None) -> Any:
        """Run coderecon scaffold."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"path": path}
        if worktree is not None:
            kwargs["worktree"] = Path(worktree).name
        return await loop.run_in_executor(self._executor, lambda: kit.scaffold(**kwargs))

    async def get_sdk(self) -> Any:
        """Return the raw coderecon SDK for direct access."""
        if not self._available or self._kit_class is None:
            raise CodeReconUnavailableError
        return self._kit_class()

    async def repo_status(self, repo: str) -> dict[str, Any] | None:
        """Return indexing status for a repo."""
        kit = self._kits.get(repo)
        if kit is None:
            return None
        loop = asyncio.get_running_loop()
        if hasattr(kit, "status"):
            return await loop.run_in_executor(self._executor, kit.status)
        return None

    # ── Step-Boundary Structural Feedback ──

    async def check_step_structural_health(
        self,
        repo: str,
        *,
        worktree: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run lightweight structural checks at step boundary.

        Returns a list of warnings (may be empty).  Each warning has:
        - type: "new_cycles" | "community_drift"
        - detail: human-readable description
        - data: machine-readable payload
        """
        warnings: list[dict[str, Any]] = []

        # Check for new cycles
        try:
            worktree_cycles = await self.graph_cycles(repo, worktree=worktree)
            base_cycles = await self.graph_cycles(repo)
            base_keys = {c.nodes for c in base_cycles.cycles}
            new_cycles = [c for c in worktree_cycles.cycles if c.nodes not in base_keys]
            if new_cycles:
                warnings.append(
                    {
                        "type": "new_cycles",
                        "detail": f"{len(new_cycles)} new dependency cycle(s) introduced",
                        "data": {"cycles": [sorted(c.nodes) for c in new_cycles]},
                    }
                )
        except Exception:
            pass  # non-critical

        # Check community drift — if worktree touches 3+ unrelated communities
        try:
            diff = await self.semantic_diff(repo, worktree=worktree)
            touched_files = {c.path for c in diff.structural_changes}
            if len(touched_files) >= 3:
                communities = await self.graph_communities(repo, worktree=worktree)
                file_communities: set[int] = set()
                for comm in communities.communities:
                    if touched_files & set(comm.members):
                        file_communities.add(comm.community_id)
                if len(file_communities) >= 3:
                    warnings.append(
                        {
                            "type": "community_drift",
                            "detail": f"Changes span {len(file_communities)} unrelated module communities",
                            "data": {"communities": sorted(file_communities)},
                        }
                    )
        except Exception:
            pass  # non-critical

        return warnings

    # ── Background Indexing ──

    async def index_repos(self, repo_paths: list[str]) -> None:
        """Index a list of repos in the background.

        Errors are logged and swallowed — a failing repo doesn't block others.
        """
        if not self._available:
            return
        for repo_path in repo_paths:
            try:
                await self.ensure_repo_indexed(repo_path)
            except Exception:
                log.warning(
                    "coderecon_review.startup_index_failed",
                    repo=repo_path,
                    exc_info=True,
                )

    # ── Health ──

    async def daemon_health(self) -> dict[str, Any]:
        """Return service health status."""
        return {
            "state": "ready" if self._available else "unavailable",
            "indexed_repos": len(self._kits),
            "init_error": self._init_error,
        }

    # ── Internal ──

    def _get_kit(self, repo: str) -> Any:
        """Return the ReviewKit for a repo or raise."""
        if not self._available:
            raise CodeReconUnavailableError
        kit = self._kits.get(repo)
        if kit is None:
            raise RepoNotIndexedError(repo)
        return kit


class CodeReconUnavailableError(Exception):
    """Raised when the coderecon-review package is not installed/available."""

    def __init__(self) -> None:
        super().__init__("coderecon-review is not available")


class RepoNotIndexedError(Exception):
    """Raised when a repo has not been indexed yet."""

    def __init__(self, repo: str) -> None:
        super().__init__(f"Repository not indexed: {repo}")
        self.repo = repo
