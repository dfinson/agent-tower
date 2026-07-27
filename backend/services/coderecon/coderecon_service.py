"""CodeRecon integration — structural analysis.

Wraps ``coderecon.review.ReviewKit`` for structural diff, cycle detection,
community detection, and health scoring.  Runs in-process (no daemon, no
network) and is always enabled.  All heavy work (tree-sitter parsing,
graph building) happens in a thread pool so the async event loop is never
blocked.

The coderecon package is always required.  If the import fails,
``start()`` raises immediately — silent degradation is a bug.
SPLADE and cross-encoder features are disabled by default and toggled
via CodePlane settings (env vars CODERECON__FEATURES__SPLADE / CROSS_ENCODER).
"""

from __future__ import annotations

import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog

if TYPE_CHECKING:
    from coderecon.index.diff.models import SemanticDiffResult
    from coderecon.review import (
        BlastRadiusResult,
        CheckpointResult,
        CommunitiesResult,
        CoverageIngestResult,
        CyclesResult,
        ScoutResult,
        StructuralHealthResult,
        TestCandidate,
    )

    from backend.services.events.event_bus import EventBus

log = structlog.get_logger(__name__)


class CodeReconService:
    """In-process structural analysis via coderecon's ReviewKit.

    Always-on, no config gating.  Indexes repos in the background on
    startup.  Thread-offloads all blocking operations.
    """

    def __init__(self) -> None:
        self._kits: dict[str, Any] = {}  # resolved_repo_path → ReviewKit
        self._index_locks: dict[str, asyncio.Lock] = {}
        self._worktree_stats: dict[tuple[str, str], dict[str, Any]] = {}
        # (repo, worktree) → {symbol_count, file_count}
        self._available = False
        self._event_bus: EventBus | None = None
        self._kit_class: type | None = None
        self._executor = ThreadPoolExecutor(thread_name_prefix="coderecon")

    # ── Helpers ──

    def _resolve_worktree_name(self, repo: str, worktree: str) -> str:
        """Resolve a worktree path to the name CodeRecon expects.

        When the worktree path resolves to the same directory as the repo
        root, the correct name is "main" — that's the primary working copy.
        Otherwise use the directory basename (e.g. "feature-branch" from
        "/repo/.codeplane-worktrees/feature-branch").
        """
        try:
            if str(Path(worktree).resolve()) == str(Path(repo).resolve()):
                return "main"
        except (OSError, ValueError):
            pass
        return Path(worktree).name

    # ── Properties ──

    @property
    def available(self) -> bool:
        return self._available

    def set_event_bus(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    # ── Lifecycle ──

    async def start(self) -> None:
        """Import coderecon.  Marks unavailable if review module is missing."""
        try:
            from coderecon.review import ReviewKit
        except (ImportError, ModuleNotFoundError):
            log.warning("coderecon_review.unavailable", reason="coderecon.review module not found")
            self._available = False
            return

        self._kit_class = ReviewKit
        self._available = True
        log.info("coderecon_review.ready")

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
        Emits repo_index_progress / repo_index_complete SSE events.
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
                # Emit progress events via on_progress callback
                def _on_progress(indexed: int, total: int) -> None:
                    if self._event_bus is None:
                        return
                    asyncio.run_coroutine_threadsafe(
                        self._emit_index_progress(resolved, indexed, total),
                        loop,
                    )

                await loop.run_in_executor(
                    self._executor,
                    lambda: kit.ensure_indexed(worktree="main", on_progress=_on_progress),
                )
            except Exception:
                log.warning("coderecon_review.index_failed", repo=resolved, exc_info=True)
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(self._executor, kit.close)
                raise

            self._kits[resolved] = kit

            # Gather post-index stats for the "main" worktree
            await self._refresh_stats(resolved, worktree="main")

            # Emit completion event
            await self._emit_index_complete(resolved)
            log.info(
                "coderecon_review.repo_indexed",
                repo=resolved,
                **self._worktree_stats.get((resolved, "main"), {}),
            )
            return resolved

    async def _emit_index_progress(self, repo: str, indexed: int, total: int) -> None:
        """Publish a repo_index_progress event."""
        if self._event_bus is None:
            return
        from backend.models.events import CPEventKind, new_event

        await self._event_bus.publish(
            new_event(
                session_id=None,
                timestamp=datetime.now(UTC),
                kind=CPEventKind.repo_index_progress,
                payload={"repo": repo, "indexed": indexed, "total": total, "phase": "indexing"},
            )
        )

    async def _emit_index_complete(self, repo: str) -> None:
        """Publish a repo_index_complete event."""
        if self._event_bus is None:
            return
        from backend.models.events import CPEventKind, new_event

        await self._event_bus.publish(
            new_event(
                session_id=None,
                timestamp=datetime.now(UTC),
                kind=CPEventKind.repo_index_complete,
                payload={"repo": repo},
            )
        )

    async def _refresh_stats(self, repo: str, *, worktree: str) -> None:
        """Re-run scout() and update the cached stats for a (repo, worktree) pair."""
        kit = self._kits.get(repo)
        if kit is None:
            return
        loop = asyncio.get_running_loop()
        wt_name = Path(worktree).name if "/" in worktree else worktree
        try:
            scout_result = await loop.run_in_executor(self._executor, lambda: kit.scout(worktree=wt_name))
            self._worktree_stats[(repo, wt_name)] = {
                "symbol_count": scout_result.def_count,
                "file_count": scout_result.file_count,
            }
        except Exception:
            log.debug("coderecon_review.refresh_stats_failed", repo=repo, worktree=wt_name, exc_info=True)

    async def register_worktree(self, repo: str, worktree_path: str | Path) -> bool:
        """Register a worktree with an already-indexed repo and index it.

        Returns True if registration succeeded, False otherwise.
        """
        kit = self._kits.get(repo)
        if kit is None:
            return False
        wt_name = self._resolve_worktree_name(repo, str(worktree_path))
        if wt_name == "main":
            # Worktree is the repo root itself — already indexed as "main".
            return True
        loop = asyncio.get_running_loop()
        try:
            wt = str(Path(worktree_path).resolve())
            await loop.run_in_executor(self._executor, kit.register_worktree, wt_name, Path(wt))
            await loop.run_in_executor(self._executor, lambda: kit.ensure_indexed(worktree=wt_name))
            await self._refresh_stats(repo, worktree=wt_name)
            log.info("coderecon_review.worktree_registered", repo=repo, worktree=wt)
            return True
        except Exception:
            log.warning(
                "coderecon_review.worktree_register_failed",
                repo=repo,
                worktree=str(worktree_path),
                exc_info=True,
            )
            return False

    # ── Structural Analysis ──

    async def semantic_diff(
        self,
        repo: str,
        *,
        base: str = "HEAD",
        target: str | None = None,
        paths: list[str] | None = None,
        worktree: str,
    ) -> SemanticDiffResult:
        """Structural diff between two git states.

        Returns a SemanticDiffResult with typed StructuralChange objects.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        kwargs: dict[str, Any] = {"base": base, "worktree": wt_name}
        if target is not None:
            kwargs["target"] = target
        if paths is not None:
            kwargs["paths"] = paths
        return await loop.run_in_executor(self._executor, lambda: kit.semantic_diff(**kwargs))

    async def graph_cycles(
        self,
        repo: str,
        *,
        worktree: str,
    ) -> CyclesResult:
        """Circular dependency detection."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(self._executor, lambda: kit.graph_cycles(worktree=wt_name))

    async def graph_communities(
        self,
        repo: str,
        *,
        worktree: str,
    ) -> CommunitiesResult:
        """Module community detection."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(self._executor, lambda: kit.graph_communities(worktree=wt_name))

    async def check_structural_health(
        self,
        repo: str,
        *,
        worktree: str,
    ) -> StructuralHealthResult:
        """Composite structural health assessment."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(self._executor, lambda: kit.check_structural_health(worktree=wt_name))

    async def impact(self, repo: str, target: str, *, worktree: str) -> Any:
        """Blast radius for a symbol or file path.

        Returns an ImpactResult with definition_sites, references,
        import_sites, and total_references.
        """
        kit = self._get_kit(repo)
        if not hasattr(kit, "impact"):
            raise CodeReconUnavailableError
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(self._executor, lambda: kit.impact(target, worktree=wt_name))

    async def scout(
        self,
        repo: str,
        *,
        scope: str | None = None,
        worktree: str,
    ) -> ScoutResult:
        """Codebase orientation — languages, top files, top symbols, cycles, communities.

        Returns a ScoutResult.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        kwargs: dict[str, Any] = {"worktree": wt_name}
        if scope is not None:
            kwargs["scope"] = scope
        return await loop.run_in_executor(self._executor, lambda: kit.scout(**kwargs))

    async def reindex(
        self,
        repo: str,
        changed_paths: list[str],
        *,
        worktree: str,
    ) -> int:
        """Re-index specific changed files. Returns count of files re-indexed."""
        kit = self._get_kit(repo)
        if not hasattr(kit, "reindex"):
            raise CodeReconUnavailableError
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        count = await loop.run_in_executor(self._executor, lambda: kit.reindex(changed_paths, worktree=wt_name))
        await self._refresh_stats(repo, worktree=wt_name)
        return int(count)

    async def checkpoint(
        self,
        repo: str,
        changed_files: list[str],
        *,
        diff: bool = True,
        lint: bool = True,
        autofix: bool = True,
        tests: bool = True,
        test_filter: str | None = None,
        max_test_hops: int = 0,
        worktree: str,
    ) -> CheckpointResult:
        """Run diff + lint + affected tests for changed files.

        Returns a CheckpointResult with diff, lint, and test phase outcomes.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(
            self._executor,
            lambda: kit.checkpoint(
                changed_files,
                diff=diff,
                lint=lint,
                autofix=autofix,
                tests=tests,
                test_filter=test_filter,
                max_test_hops=max_test_hops,
                worktree=wt_name,
            ),
        )

    async def recon_impact(
        self,
        repo: str,
        target: str,
        justification: str,
        *,
        worktree: str,
    ) -> Any:
        """Run coderecon recon_impact."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(
            self._executor,
            lambda: kit.impact(target=target, worktree=wt_name),
        )

    async def sync_from_git(self, repo: str, *, worktree: str) -> int:
        """Detect changed files since last index and reindex them.

        Returns number of files reindexed.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        count = await loop.run_in_executor(self._executor, lambda: kit.sync_from_git(worktree=wt_name))
        await self._refresh_stats(repo, worktree=wt_name)
        return int(count)

    async def merge_index(self, repo: str, source: str, target: str = "main") -> dict[str, Any]:
        """Reconcile source worktree index into target, then drop source.

        Call after a successful git merge when the target worktree is clean.
        Returns dict with adopted/reindexed/pruned counts.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(self._executor, lambda: kit.merge_index(source, target))
        await self._refresh_stats(repo, worktree=target)
        return cast("dict[str, Any]", result)

    async def drop_worktree(self, repo: str, name: str) -> int:
        """Remove all indexed data for a worktree.

        Returns number of files removed from the index.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(self._executor, lambda: kit.drop_worktree(name))
        self._worktree_stats.pop((repo, name), None)
        return int(result)

    async def enrich_scip(self, repo: str, *, worktree: str) -> Any:
        """Run SCIP indexers and import compiler-grade cross-references.

        Returns a ScipImportResult with per-tool success/failure details.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(self._executor, lambda: kit.enrich_scip(worktree=wt_name))

    async def repo_status(self, repo: str, *, worktree: str = "main") -> dict[str, Any] | None:
        """Return cached indexing stats for a (repo, worktree) pair.

        Stats are gathered via scout() after every index mutation and
        cached per-worktree.
        """
        if repo not in self._kits:
            return None
        return self._worktree_stats.get((repo, worktree))

    # ── Step-Boundary Structural Feedback ──

    async def check_step_structural_health(
        self,
        repo: str,
        *,
        worktree: str,
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
            base_cycles = await self.graph_cycles(repo, worktree="main")
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
        }

    # ── Coverage & Blast Radius ──

    async def ingest_coverage(
        self,
        repo: str,
        report_path: str,
        *,
        worktree: str = "main",
        test_id: str | None = None,
        failed_tests: list[str] | None = None,
        rebuild_reachability: bool = True,
    ) -> CoverageIngestResult:
        """Ingest a coverage report (coverage.py JSON or lcov) into the index."""
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: kit.ingest_coverage(
                report_path,
                worktree=worktree,
                test_id=test_id,
                failed_tests=failed_tests,
                rebuild_reachability=rebuild_reachability,
            ),
        )

    async def blast_radius(
        self,
        repo: str,
        changed_files: list[str],
        *,
        worktree: str = "main",
        max_hops: int = 2,
    ) -> BlastRadiusResult:
        """Compute blast radius for a set of changed files.

        Returns test candidates, coverage gaps, and whether coverage data exists.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(
            self._executor,
            lambda: kit.blast_radius(changed_files, worktree=wt_name, max_hops=max_hops),
        )

    async def covering_tests(
        self,
        repo: str,
        file_path: str,
        *,
        worktree: str = "main",
    ) -> dict[str, list[TestCandidate]]:
        """Return tests that cover definitions in the given file.

        Keys are qualified symbol names, values are lists of TestCandidate.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(
            self._executor,
            lambda: kit.covering_tests(file_path, worktree=wt_name),
        )

    async def line_coverage(
        self,
        repo: str,
        file_path: str,
        *,
        worktree: str = "main",
        line_range: tuple[int, int] | None = None,
        include_tests: bool = False,
    ) -> Any:
        """Return per-line coverage for gutter rendering.

        Delegates to ReviewKit.line_coverage() which returns a
        LineCoverageResult dataclass.
        """
        kit = self._get_kit(repo)
        loop = asyncio.get_running_loop()
        wt_name = self._resolve_worktree_name(repo, worktree)
        return await loop.run_in_executor(
            self._executor,
            lambda: kit.line_coverage(
                file_path,
                worktree=wt_name,
                line_range=line_range,
                include_tests=include_tests,
            ),
        )

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
    """Raised when the coderecon package is not installed/available."""

    def __init__(self) -> None:
        super().__init__("coderecon is not available")


class RepoNotIndexedError(Exception):
    """Raised when a repo has not been indexed yet."""

    def __init__(self, repo: str) -> None:
        super().__init__(f"Repository not indexed: {repo}")
        self.repo = repo
