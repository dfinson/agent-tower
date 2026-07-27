"""Trail enrichment drain — async batch enrichment + title recovery + motivation summarization."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.exc import SQLAlchemyError

from backend.config import TrailConfig
from backend.models.db import TrailNodeRow
from backend.models.events import CPEventKind, new_event
from backend.persistence.trail_repo import TrailNodeRepository
from backend.services.story.motivation import (
    _EDIT_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    _build_edit_prompt,
    _build_user_prompt,
    _compute_edit_key,
)
from backend.services.trail.models import (
    ALL_KINDS,
    SEMANTIC_KINDS,
    TrailJobState,
    make_node_id,
)
from backend.services.trail.prompts import (
    ENRICH_SYSTEM_PROMPT,
    build_enrichment_prompt,
    normalize_path,
    parse_enrichment_response,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.coderecon.coderecon_service import CodeReconService
    from backend.services.events.event_bus import EventBus
    from backend.services.sidecar.session import SidecarSessionManager

log = structlog.get_logger()


class TrailEnricher:
    """Async batch enrichment of trail nodes + title recovery drain loop."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        sidecar_sessions: SidecarSessionManager | None = None,
        config: TrailConfig | None = None,
        *,
        job_state: dict[str, TrailJobState] | None = None,
        coderecon: CodeReconService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._sidecar_sessions = sidecar_sessions
        self._config = config or TrailConfig()
        self._repo = TrailNodeRepository(session_factory)
        self._job_state = job_state if job_state is not None else {}
        self._coderecon = coderecon
        self._coverage_ingested: set[tuple[str, str, float]] = set()
        # Jobs whose trail data changed this drain iteration — story cache
        # will be invalidated at the end of each loop sweep.
        self._dirty_job_ids: set[str] = set()

    async def drain_enrichment(self) -> int:
        """Process a batch of nodes needing enrichment. Returns count processed."""
        if not self._sidecar_sessions:
            return 0

        nodes = await self._repo.get_pending_enrichment(limit=self._config.enrich_batch_size)
        if not nodes:
            return 0

        processed = 0
        by_job: dict[str, list[TrailNodeRow]] = {}
        for node in nodes:
            by_job.setdefault(node.job_id, []).append(node)

        for job_id, job_nodes in by_job.items():
            try:
                goal_nodes = await self._repo.get_by_job(job_id, kinds=["goal"], limit=1)
                goal_intent = goal_nodes[0].intent if goal_nodes else None

                recent_decisions = await self._repo.get_recent_decisions(
                    job_id,
                    limit=self._config.enrich_decisions_context,
                )

                prompt = build_enrichment_prompt(job_nodes, goal_intent, recent_decisions)
                full_prompt = f"SYSTEM:\n{ENRICH_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                result = await self._sidecar_sessions.complete(full_prompt)
                result_text = result if isinstance(result, str) else str(result)

                enrichment_data = parse_enrichment_response(result_text)
                if not enrichment_data:
                    for node in job_nodes:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    continue

                node_map = {n.id: n for n in job_nodes}
                for annotation in enrichment_data.get("annotations", []):
                    nid = annotation.get("node_id")
                    if nid not in node_map:
                        continue

                    source_node = node_map[nid]
                    new_kind = annotation.get("kind")

                    if new_kind and new_kind != source_node.kind:  # noqa: SIM102
                        if source_node.kind in ("modify", "explore") or new_kind not in ALL_KINDS:
                            new_kind = None

                    sup = annotation.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    files = annotation.get("files")
                    if files and isinstance(files, list):
                        files = [normalize_path(f) for f in files if isinstance(f, str)]
                    else:
                        files = None

                    await self._repo.update_enrichment(
                        nid,
                        kind=new_kind,
                        intent=annotation.get("intent"),
                        rationale=annotation.get("rationale"),
                        outcome=annotation.get("outcome"),
                        tags=annotation.get("tags") if isinstance(annotation.get("tags"), list) else None,
                        supersedes=sup,
                        files=files,
                        purpose=annotation.get("purpose"),
                    )
                    processed += 1

                for semantic in enrichment_data.get("semantic_nodes", []):
                    s_kind = semantic.get("kind")
                    if s_kind not in SEMANTIC_KINDS:
                        continue

                    anchor_nid = semantic.get("anchor_node_id")
                    anchor_node = node_map.get(anchor_nid) if anchor_nid else None

                    if anchor_node:
                        anchor_seq = anchor_node.anchor_seq
                        parent_id = anchor_node.parent_id
                    else:
                        anchor_seq = job_nodes[0].anchor_seq
                        parent_id = job_nodes[0].parent_id

                    state = self._job_state.get(job_id)
                    if state:
                        seq = state.next_seq
                        state.next_seq += 1
                    else:
                        seq = await self._repo.max_seq(job_id) + 1

                    sup = semantic.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    s_node = TrailNodeRow(
                        id=make_node_id(),
                        job_id=job_id,
                        seq=seq,
                        anchor_seq=anchor_seq,
                        parent_id=parent_id,
                        kind=s_kind,
                        deterministic_kind=None,
                        phase=anchor_node.phase if anchor_node else None,
                        timestamp=datetime.now(UTC),
                        enrichment="complete",
                        intent=semantic.get("intent"),
                        rationale=semantic.get("rationale"),
                        outcome=semantic.get("outcome"),
                        supersedes=sup,
                        tags=json.dumps(semantic.get("tags", []), ensure_ascii=False),
                    )
                    await self._repo.create(s_node)
                    processed += 1

                # Nodes not in the response have no further enrichment path —
                # mark complete to prevent infinite pending loop.
                annotated_ids = {a.get("node_id") for a in enrichment_data.get("annotations", [])}
                for node in job_nodes:
                    if node.id not in annotated_ids:
                        await self._repo.update_enrichment(node.id, enrichment="complete")
                        processed += 1

            except Exception:
                log.debug("trail_enrichment_failed", job_id=job_id, exc_info=True)
                for node in job_nodes:
                    try:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    except SQLAlchemyError:
                        log.debug("enrichment_status_update_failed", node_id=node.id, exc_info=True)

        if processed:
            self._dirty_job_ids.update(by_job.keys())
        return processed

    async def drain_titles(self) -> int:
        """Recover titles for trail nodes that were created but never got titles.

        Only emits a turn_summary when we can derive a meaningful title from
        actual content (files written or agent message). Nodes with no signal
        are skipped — silence is better than noise.
        """
        nodes = await self._repo.get_untitled_work_nodes(limit=20)
        if not nodes:
            return 0

        processed = 0
        for node in nodes:
            try:
                files_written: list[str] = []
                if node.files:
                    all_files = json.loads(node.files)
                    files_written = [f for f in all_files if isinstance(f, str)]

                if files_written:
                    title = f"Edited {', '.join(files_written[:3])}"
                elif node.agent_message:
                    title = node.agent_message.split("\n")[0]
                else:
                    # No meaningful signal — skip rather than emit garbage.
                    continue

                # Only persist the title to DB. Do NOT touch in-memory state
                # (state.activities) — that's the activity tracker's job.
                # Mutating it here races with the live LLM path and poisons
                # activity labels.
                activity_id = node.activity_id or ""
                activity_label = node.activity_label or ""

                async with self._session_factory() as session:
                    from sqlalchemy import update as sa_update

                    stmt = (
                        sa_update(TrailNodeRow)
                        .where(TrailNodeRow.id == node.id)
                        .values(
                            title=title,
                        )
                    )
                    await session.execute(stmt)
                    await session.commit()

                # Only emit turn_summary if the activity tracker already
                # assigned an activity (activity_id in the node). Otherwise
                # the activity tracker will handle emission when it runs.
                if activity_id:
                    await self._event_bus.publish(
                        new_event(
                            session_id=node.job_id,
                            timestamp=node.timestamp,
                            kind=CPEventKind.turn_summary,
                            payload={
                                "turn_id": node.turn_id,
                                "title": title,
                                "activity_id": activity_id,
                                "activity_label": activity_label,
                                "activity_status": "active",
                                "is_new_activity": False,
                                "plan_item_id": node.plan_item_id,
                            },
                        )
                    )
                processed += 1
            except (SQLAlchemyError, KeyError, ValueError, OSError):
                log.debug("trail_title_recovery_failed", node_id=node.id, exc_info=True)

        return processed

    # ------------------------------------------------------------------
    # §13.2: Motivation summarization (absorbed from MotivationService)
    # ------------------------------------------------------------------

    async def drain_write_summaries(self) -> int:
        """Pass 1: Generate write_summary for write sub-nodes using parent's preceding_context."""
        if not self._sidecar_sessions:
            return 0

        nodes = await self._repo.get_unsummarized_write_nodes(
            limit=self._config.enrich_batch_size,
        )
        if not nodes:
            return 0

        # Pre-fetch parent modify nodes for preceding_context
        parent_ids = {n.parent_id for n in nodes if n.parent_id}
        parents: dict[str, TrailNodeRow] = {}
        for pid in parent_ids:
            parent = await self._repo.get(pid)
            if parent:
                parents[pid] = parent

        # Pre-fetch job descriptions
        from backend.persistence.job_repo import JobRepository

        job_ids = {n.job_id for n in nodes}
        job_descs: dict[str, str | None] = {}
        async with self._session_factory() as session:
            job_repo = JobRepository(session)
            for jid in job_ids:
                job_row = await job_repo.get(jid)
                if job_row:
                    desc = getattr(job_row, "description", None) or getattr(job_row, "prompt", None)
                    job_descs[jid] = str(desc) if desc else None
                else:
                    job_descs[jid] = None

        processed = 0
        for node in nodes:
            try:
                # Prefer the write node's own preceding_context (span-level,
                # already role-compressed by the event pipeline) over the parent's
                # step-level context.
                ctx = node.preceding_context
                if not ctx:
                    parent = parents.get(node.parent_id) if node.parent_id else None
                    ctx = parent.preceding_context if parent else None
                if not ctx:
                    # No context available — mark with empty summary to avoid reprocessing
                    await self._repo.set_write_summary(node.id, "")
                    processed += 1
                    continue

                # Build file path from node.files
                file_path = ""
                if node.files:
                    files_list = json.loads(node.files)
                    file_path = files_list[0] if files_list else ""

                prompt = _build_user_prompt(
                    tool_name=node.tool_name or "unknown",
                    tool_args_json=None,  # snippet is pre-extracted
                    preceding_context=ctx,
                    job_description=job_descs.get(node.job_id),
                )
                if node.snippet:
                    prompt += f"\n\nCODE SNIPPET:\n{node.snippet}"
                if file_path:
                    prompt += f"\nFILE: {file_path}"

                full_prompt = f"SYSTEM:\n{_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                result = await self._sidecar_sessions.complete(full_prompt)
                summary = result if isinstance(result, str) else str(result)
                summary = summary.strip()

                await self._repo.set_write_summary(node.id, summary)
                processed += 1
            except (SQLAlchemyError, OSError, ValueError):
                log.debug("write_summary_failed", node_id=node.id, exc_info=True)

        if processed:
            self._dirty_job_ids.update(n.job_id for n in nodes)
        return processed

    async def drain_edit_motivations(self) -> int:
        """Pass 2: Generate per-edit motivations for write sub-nodes."""
        if not self._sidecar_sessions:
            return 0

        nodes = await self._repo.get_unenriched_edit_write_nodes(
            limit=self._config.enrich_batch_size,
        )
        if not nodes:
            return 0

        # Pre-fetch parent modify nodes for preceding_context
        parent_ids = {n.parent_id for n in nodes if n.parent_id}
        parents: dict[str, TrailNodeRow] = {}
        for pid in parent_ids:
            parent = await self._repo.get(pid)
            if parent:
                parents[pid] = parent

        processed = 0
        for node in nodes:
            try:
                # Reconstruct parsed_args from snippet for edit_key computation
                tool_name = node.tool_name or "unknown"

                # If no snippet, mark with empty edits
                if not node.snippet:
                    await self._repo.set_edit_motivations(node.id, "[]")
                    processed += 1
                    continue

                # Build a synthetic parsed_args from the snippet for edit_key
                # The snippet is pre-formatted as "- old\n+ new" or "+ content"
                snippet_lines = node.snippet.splitlines()
                old_lines = [ln[2:] for ln in snippet_lines if ln.startswith("- ")]
                new_lines = [ln[2:] for ln in snippet_lines if ln.startswith("+ ")]
                parsed_args: dict[str, str] = {}
                if old_lines or new_lines:
                    parsed_args["old_str"] = "\n".join(old_lines)
                    parsed_args["new_str"] = "\n".join(new_lines)
                elif new_lines:
                    parsed_args["file_text"] = "\n".join(new_lines)

                edit_key = _compute_edit_key(tool_name, parsed_args)

                # Build file path from node.files
                file_path = ""
                if node.files:
                    files_list = json.loads(node.files)
                    file_path = files_list[0] if files_list else ""

                # Prefer span-level context (already role-compressed)
                ctx = node.preceding_context
                if not ctx:
                    parent = parents.get(node.parent_id) if node.parent_id else None
                    ctx = parent.preceding_context if parent else None

                prompt = _build_edit_prompt(
                    tool_name=tool_name,
                    parsed_args=parsed_args,
                    file_path=file_path,
                    preceding_context=ctx,
                    file_level_summary=node.write_summary,
                )
                full_prompt = f"SYSTEM:\n{_EDIT_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                result = await self._sidecar_sessions.complete(full_prompt)
                summary = result if isinstance(result, str) else str(result)
                summary = summary.strip()

                edit_entry = {"edit_key": edit_key, "summary": summary or ""}
                await self._repo.set_edit_motivations(
                    node.id,
                    json.dumps([edit_entry], ensure_ascii=False),
                )
                processed += 1
            except (SQLAlchemyError, OSError, ValueError):
                log.debug("edit_motivation_failed", node_id=node.id, exc_info=True)

        if processed:
            self._dirty_job_ids.update(n.job_id for n in nodes)
        return processed

    # ------------------------------------------------------------------
    # §13.3: Semantic target resolution (CodeRecon structural diff)
    # ------------------------------------------------------------------

    async def drain_semantic_targets(self) -> int:
        """Resolve semantic targets for write sub-nodes using CodeRecon semantic_diff.

        For each parent modify node with start_sha != end_sha, runs semantic_diff
        to identify which symbols were affected, then distributes the results to
        child write nodes by matching file paths.
        """
        if not self._coderecon:
            log.error("semantic_targets_skipped", reason="coderecon not injected")
            return 0

        modify_nodes = await self._repo.get_modify_nodes_needing_semantic_targets(
            limit=self._config.enrich_batch_size,
        )
        if not modify_nodes:
            return 0

        # Pre-fetch job repo/worktree info
        from sqlalchemy import text

        job_info: dict[str, dict[str, str]] = {}
        async with self._session_factory() as session:
            job_ids = {n.job_id for n in modify_nodes}
            for jid in job_ids:
                row = await session.execute(
                    text("SELECT repo, worktree_path FROM jobs WHERE id = :jid"),
                    {"jid": jid},
                )
                mapping = row.mappings().first()
                if mapping and mapping.get("repo") and mapping.get("worktree_path"):
                    job_info[jid] = {
                        "repo": str(mapping["repo"]),
                        "worktree_path": str(mapping["worktree_path"]),
                    }

        processed = 0
        for modify_node in modify_nodes:
            try:
                info = job_info.get(modify_node.job_id)
                if not info:
                    log.error(
                        "semantic_targets_no_job_info",
                        modify_node_id=modify_node.id,
                        job_id=modify_node.job_id,
                    )
                    continue

                worktree_path = info["worktree_path"]

                # Ensure repo indexed and worktree registered
                repo_name = await self._coderecon.ensure_repo_indexed(info["repo"])
                await self._coderecon.register_worktree(repo_name, worktree_path)

                # Run semantic_diff between the modify node's SHAs
                if not modify_node.start_sha or not modify_node.end_sha:
                    continue
                diff_result = await self._coderecon.semantic_diff(
                    repo_name,
                    base=modify_node.start_sha,
                    target=modify_node.end_sha,
                    worktree=worktree_path,
                )

                structural_changes = diff_result.structural_changes or []

                # Build a file→changes index for distribution
                changes_by_file: dict[str, list[dict[str, Any]]] = {}
                for ch in structural_changes:
                    entry: dict[str, Any] = {
                        "symbol": ch.qualified_name or ch.name,
                        "kind": ch.kind,
                        "change": ch.change,
                        "file": ch.path,
                        "severity": ch.structural_severity,
                        "risk": ch.behavior_change_risk,
                    }
                    if ch.start_line:
                        entry["line_range"] = [ch.start_line, ch.end_line]
                    if ch.impact and ch.impact.reference_count:
                        entry["ref_count"] = ch.impact.reference_count
                    if ch.delta_tags:
                        entry["delta_tags"] = ch.delta_tags
                    if ch.change_preview:
                        entry["preview"] = ch.change_preview
                    changes_by_file.setdefault(ch.path, []).append(entry)

                # Distribute to write children
                children = await self._repo.get_write_children(modify_node.id)
                worktree_prefix = info["worktree_path"].rstrip("/") + "/"

                for child in children:
                    if child.semantic_targets is not None:
                        continue  # Already populated

                    matched: list[dict[str, Any]] = []
                    if child.files:
                        child_files = json.loads(child.files)
                        for full_path in child_files:
                            # Strip worktree prefix to get repo-relative path
                            if full_path.startswith(worktree_prefix):
                                rel_path = full_path[len(worktree_prefix) :]
                            else:
                                rel_path = full_path.rsplit("/", 1)[-1]
                            if rel_path in changes_by_file:
                                matched.extend(changes_by_file[rel_path])

                    await self._repo.set_semantic_targets(
                        child.id,
                        json.dumps(matched, ensure_ascii=False),
                    )
                    processed += 1

            except Exception:
                log.error(
                    "semantic_targets_failed",
                    modify_node_id=modify_node.id,
                    exc_info=True,
                )
                # Leave semantic_targets NULL so the node is retried next cycle.

        if processed:
            self._dirty_job_ids.update(n.job_id for n in modify_nodes)
        return processed

    # ── Coverage report scanning ──

    # Common locations where coverage tools write reports
    _COVERAGE_REPORT_CANDIDATES: tuple[str, ...] = (
        "coverage.json",
        "coverage/coverage.json",
        "coverage/lcov.info",
        "lcov.info",
        "coverage.xml",
        ".coverage/coverage.json",
        "htmlcov/coverage.json",
    )

    async def drain_coverage_scan(self) -> int:
        """Scan active job worktrees for coverage reports and ingest them.

        Runs each cycle — checks all jobs with worktree_path for freshly-written
        coverage files.  Ingests any found files that haven't been ingested yet
        (tracked by mtime in _coverage_ingested).
        """
        if not self._coderecon:
            return 0

        from sqlalchemy import text

        ingested = 0
        async with self._session_factory() as session:
            rows = await session.execute(
                text(
                    "SELECT id, repo, worktree_path FROM jobs"
                    " WHERE state IN ('running', 'paused')"
                    " AND worktree_path IS NOT NULL"
                ),
            )
            jobs = rows.mappings().all()

        for job in jobs:
            worktree_path = str(job["worktree_path"])
            repo = str(job["repo"])
            job_id = str(job["id"])

            report_path = await self._find_coverage_report(worktree_path)
            if not report_path:
                continue

            # Track ingested files by (job_id, path, mtime) to avoid re-ingestion
            mtime = report_path.stat().st_mtime
            cache_key = (job_id, str(report_path), mtime)
            if cache_key in self._coverage_ingested:
                continue

            try:
                repo_name = await self._coderecon.ensure_repo_indexed(repo)
                await self._coderecon.register_worktree(repo_name, worktree_path)

                result = await self._coderecon.ingest_coverage(
                    repo_name,
                    str(report_path),
                    worktree=worktree_path,
                )
                # Only mark as ingested if at least 1 file was covered
                if result and getattr(result, "files_covered", 0) > 0:
                    self._coverage_ingested.add(cache_key)
                    ingested += 1
                    log.info(
                        "coverage_ingested",
                        job_id=job_id,
                        report=str(report_path),
                        files_covered=getattr(result, "files_covered", 0),
                    )
            except Exception:
                log.debug("coverage_ingest_failed", job_id=job_id, report=str(report_path), exc_info=True)

        return ingested

    async def _find_coverage_report(self, worktree_path: str) -> Path | None:
        """Find the first existing coverage report in the worktree."""
        wt = Path(worktree_path)
        if not wt.is_dir():
            return None
        for candidate in self._COVERAGE_REPORT_CANDIDATES:
            p = wt / candidate
            if p.is_file() and p.stat().st_size > 0:
                return p
        return None

    async def drain_loop(self) -> None:
        """Run forever, periodically processing enrichment, titles, and motivations."""
        while True:
            try:
                count = await self.drain_enrichment()
                if count:
                    log.info("trail_enrichment_batch_processed", count=count)
                title_count = await self.drain_titles()
                if title_count:
                    log.info("trail_title_recovery_batch_processed", count=title_count)
                # §13.2: Motivation summarization
                summary_count = await self.drain_write_summaries()
                if summary_count:
                    log.info("write_summary_batch_processed", count=summary_count)
                edit_count = await self.drain_edit_motivations()
                if edit_count:
                    log.info("edit_motivation_batch_processed", count=edit_count)
                # §13.3: Semantic target resolution via CodeRecon
                semantic_count = await self.drain_semantic_targets()
                if semantic_count:
                    log.info("semantic_targets_batch_processed", count=semantic_count)
                # Coverage report auto-ingestion
                cov_count = await self.drain_coverage_scan()
                if cov_count:
                    log.info("coverage_scan_batch_ingested", count=cov_count)

                # Invalidate story cache for jobs whose trail data changed
                if self._dirty_job_ids:
                    from backend.services.story.service import invalidate_story_cache_for_jobs

                    try:
                        await invalidate_story_cache_for_jobs(self._session_factory, self._dirty_job_ids)
                    except Exception:
                        log.debug("story_cache_invalidation_failed", exc_info=True)
                    self._dirty_job_ids = set()
            except Exception:  # Safety-net: drain loop must not crash
                log.warning("trail_enrichment_drain_error", exc_info=True)
            await asyncio.sleep(self._config.enrich_interval_seconds)
