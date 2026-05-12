"""CodeRecon Review integration — lightweight structural analysis.

Wraps ``coderecon.review.ReviewKit`` for structural diff, cycle detection,
community detection, and health scoring.  Runs in-process (no daemon, no
network) and is always enabled.  All heavy work (tree-sitter parsing,
graph building) happens in a thread pool so the async event loop is never
blocked.

Degrades gracefully: if the coderecon-review package is not installed, if
tree-sitter grammars are missing, or if a repo fails to index, the
``available`` property returns ``False`` and every public method returns a
safe fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.services.event_bus import EventBus

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses — lightweight stand-ins for the SDK types that callers
# access via attribute/dict access.
# ---------------------------------------------------------------------------


@dataclass
class DiffResult:
    summary: str = ""
    structural_changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CyclesResult:
    cycles: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CommunitiesResult:
    communities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class HealthResult:
    score: float = 0.0
    cycle_count: int = 0
    community_count: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


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
        self._kit_class: type | None = None  # cached ReviewKit class ref
        self._init_error: str | None = None

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
            from coderecon.review import ReviewKit  # type: ignore[import-untyped]
            self._kit_class = ReviewKit
            self._available = True
            log.info("coderecon_review.ready")
        except ImportError as exc:
            self._init_error = str(exc)
            self._available = False
            log.warning("coderecon_review.import_failed", error=str(exc))

    async def stop(self) -> None:
        """Close all ReviewKit instances."""
        for repo_path, kit in list(self._kits.items()):
            try:
                await asyncio.to_thread(kit.close)
            except Exception:
                log.debug("coderecon_review.close_error", repo=repo_path, exc_info=True)
        self._kits.clear()
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

        if resolved not in self._index_locks:
            self._index_locks[resolved] = asyncio.Lock()

        async with self._index_locks[resolved]:
            if resolved in self._kits:
                return resolved

            kit = self._kit_class(Path(resolved))
            try:
                await asyncio.to_thread(kit.ensure_indexed)
            except Exception:
                log.warning("coderecon_review.index_failed", repo=resolved, exc_info=True)
                try:
                    await asyncio.to_thread(kit.close)
                except Exception:
                    pass
                raise

            self._kits[resolved] = kit
            log.info("coderecon_review.repo_indexed", repo=resolved)
            return resolved

    async def register_worktree(self, repo: str, worktree_path: str | Path) -> None:
        """Register a worktree with an already-indexed repo."""
        kit = self._kits.get(repo)
        if kit is None:
            return
        try:
            wt = str(Path(worktree_path).resolve())
            await asyncio.to_thread(kit.register_worktree, "worktree", Path(wt))
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
    ) -> DiffResult:
        """Structural diff between two git states."""
        kit = self._get_kit(repo)
        try:
            kwargs: dict[str, Any] = {"base": base}
            if target is not None:
                kwargs["target"] = target
            raw = await asyncio.to_thread(kit.semantic_diff, **kwargs)
            return DiffResult(
                summary=getattr(raw, "summary", ""),
                structural_changes=getattr(raw, "changes", []) or [],
            )
        except Exception:
            log.debug("coderecon_review.semantic_diff_failed", repo=repo, exc_info=True)
            return DiffResult()

    async def graph_cycles(
        self, repo: str, *, worktree: str | None = None,
    ) -> CyclesResult:
        """Circular dependency detection."""
        kit = self._get_kit(repo)
        try:
            raw = await asyncio.to_thread(kit.graph_cycles)
            return CyclesResult(
                cycles=getattr(raw, "cycles", []) or [],
            )
        except Exception:
            log.debug("coderecon_review.graph_cycles_failed", repo=repo, exc_info=True)
            return CyclesResult()

    async def graph_communities(
        self, repo: str, *, worktree: str | None = None,
    ) -> CommunitiesResult:
        """Module community detection."""
        kit = self._get_kit(repo)
        try:
            raw = await asyncio.to_thread(kit.graph_communities)
            return CommunitiesResult(
                communities=getattr(raw, "communities", []) or [],
            )
        except Exception:
            log.debug("coderecon_review.graph_communities_failed", repo=repo, exc_info=True)
            return CommunitiesResult()

    async def check_structural_health(
        self, repo: str, *, worktree: str | None = None,
    ) -> HealthResult:
        """Composite structural health score."""
        kit = self._get_kit(repo)
        try:
            raw = await asyncio.to_thread(kit.check_structural_health)
            return HealthResult(
                score=getattr(raw, "score", 0.0),
                cycle_count=getattr(raw, "cycle_count", 0),
                community_count=getattr(raw, "community_count", 0),
            )
        except Exception:
            log.debug("coderecon_review.health_check_failed", repo=repo, exc_info=True)
            return HealthResult()

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
            touched_files = {c.get("file", "") for c in diff.structural_changes}
            if len(touched_files) >= 3:
                communities = await self.graph_communities(repo, worktree=worktree)
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
        kit = self._kits.get(repo)
        if kit is None:
            raise CodeReconUnavailableError
        return kit


class CodeReconUnavailableError(Exception):
    """Raised when coderecon-review is not available."""

    def __init__(self) -> None:
        super().__init__("coderecon-review is not available")
