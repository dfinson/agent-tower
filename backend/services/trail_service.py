"""Agent audit trail service — deterministic skeleton + async LLM enrichment.

Subscribes to domain events and builds a structured intent graph (TrailNodes)
for every job. The deterministic layer fires synchronously from events using
only structured data. The enrichment layer annotates nodes asynchronously
via sister-session LLM calls.

Phase 1: Deterministic skeleton (no LLM)
Phase 2: Async enrichment (LLM annotation + semantic node emission)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select as sa_select

from backend.config import TrailConfig
from backend.models.db import JobRow, TrailNodeRow
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.trail_repo import TrailNodeRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from backend.services.naming_service import Completable

log = structlog.get_logger()

# Valid trail node kinds
_DETERMINISTIC_KINDS = frozenset({"goal", "explore", "modify", "request", "summarize", "delegate", "shell"})
_SEMANTIC_KINDS = frozenset({"plan", "insight", "decide", "backtrack", "verify"})
_ALL_KINDS = _DETERMINISTIC_KINDS | _SEMANTIC_KINDS



_ENRICH_SYSTEM_PROMPT = (
    "You annotate agent trail nodes with intent, rationale, outcome, and tags. "
    "You also detect semantic patterns (plan, insight, decide, backtrack, verify) "
    "from the agent's transcript. Be concrete: cite file names, function names, "
    "line numbers from the context. Keep fields terse — phrases not paragraphs. "
    "Do NOT invent details not present in the context."
)


def _make_node_id() -> str:
    return uuid.uuid4().hex


@dataclass
class _TrailJobState:
    """Per-job transient state for the trail builder."""

    active_goal_id: str | None = None
    active_step_id: str | None = None
    current_phase: str | None = None
    next_seq: int = 1
    pending_events: list[DomainEvent] = field(default_factory=list)


def _classify_step(payload: dict) -> str:
    """Assign node kind from structured step/event data. No LLM.

    This is best-effort classification from available signals.
    Enrichment may reclassify when the transcript contradicts.
    """
    files_written = payload.get("files_written") or []
    files_read = payload.get("files_read") or []
    start_sha = payload.get("start_sha")
    end_sha = payload.get("end_sha")

    # Signal 1: Explicit file-write tools (high confidence)
    if files_written:
        return "modify"

    # Signal 2: SHA divergence catches shell/git-mediated writes
    if start_sha and end_sha and start_sha != end_sha:
        return "modify"

    # Signal 3: Explicit file-read tools
    if files_read:
        return "explore"

    # Signal 4: No file tools at all
    return "shell"


def _build_enrichment_prompt(
    nodes: list[TrailNodeRow],
    goal_intent: str | None,
    recent_decisions: list[TrailNodeRow],
) -> str:
    """Build the enrichment prompt for a batch of nodes."""
    parts: list[str] = []
    parts.append("AGENT TRAIL — annotate these trail nodes and detect semantic patterns.\n")

    if goal_intent:
        parts.append(f"CURRENT GOAL: {goal_intent}\n")

    parts.append("NODES TO ANNOTATE:")
    for node in nodes:
        files = json.loads(node.files) if node.files else []
        kind_note = ""
        if node.kind == "shell":
            kind_note = " (kind=shell means classification was uncertain — reclassify from transcript)"
        elif node.kind == "modify" and not files:
            kind_note = " (SHA divergence detected a write but we don't know which files)"
        parts.append(
            f"  - node_id: {node.id}, kind: {node.kind}, files: {files}{kind_note}"
        )

    # Build per-node step context
    for node in nodes:
        parts.append(f"\nSTEP CONTEXT for node {node.id}:")
        # We store step context as span_ids JSON but preceding_context is
        # not on TrailNodeRow — it comes from the step. For now, we include
        # what's available from the node itself.
        if node.intent:
            parts.append(f"  Current intent: {node.intent}")
        files = json.loads(node.files) if node.files else []
        if files:
            parts.append(f"  Files: {', '.join(files)}")
        if node.start_sha and node.end_sha and node.start_sha != node.end_sha:
            parts.append(f"  SHA changed: {node.start_sha} → {node.end_sha}")

    if recent_decisions:
        parts.append("\nRECENT DECISIONS (for supersedes linking):")
        for d in recent_decisions:
            parts.append(f"  - node_id: {d.id}, intent: {d.intent or '(pending)'}")

    parts.append(
        "\nRespond with JSON only. Two arrays:\n"
        '1. "annotations": [{node_id, kind, intent, rationale, outcome, files, tags}]\n'
        '   - For kind=modify or kind=explore: do NOT change the kind\n'
        '   - For kind=shell: reclassify to modify, explore, or verify\n'
        '2. "semantic_nodes": [{kind, intent, rationale, outcome, tags, supersedes, anchor_node_id}]\n'
        '   - kind must be one of: plan, insight, decide, backtrack, verify\n'
        '   - anchor_node_id = the node_id of the deterministic node this semantic node relates to\n'
        '   - supersedes = node_id of prior decide node being reversed (for backtrack/decide only)\n'
    )
    return "\n".join(parts)


class TrailService:
    """Builds and enriches the agent audit trail.

    App-scoped singleton. Subscribes to domain events for deterministic
    skeleton building. Runs a background drain loop for async enrichment.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        completer: Completable | None = None,
        config: TrailConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._completer = completer
        self._config = config or TrailConfig()
        self._repo = TrailNodeRepository(session_factory)
        self._job_state: dict[str, _TrailJobState] = {}

    # ------------------------------------------------------------------
    # Event subscriber (deterministic skeleton)
    # ------------------------------------------------------------------

    async def handle_event(self, event: DomainEvent) -> None:
        """Domain event subscriber — builds deterministic trail nodes."""
        try:
            if event.kind == DomainEventKind.job_created:
                await self._on_job_started(event)
            elif event.kind == DomainEventKind.step_completed:
                await self._on_step_completed(event)
            elif event.kind == DomainEventKind.step_started:
                self._on_step_started(event)
            elif event.kind == DomainEventKind.execution_phase_changed:
                await self._on_phase_changed(event)
            elif event.kind == DomainEventKind.approval_requested:
                await self._on_approval_requested(event)
            elif event.kind in (
                DomainEventKind.job_completed,
                DomainEventKind.job_failed,
                DomainEventKind.job_canceled,
            ):
                await self._on_job_terminal(event)
        except Exception:
            log.debug("trail_event_error", event_kind=event.kind, job_id=event.job_id, exc_info=True)

    async def _on_job_started(self, event: DomainEvent) -> None:
        """Create the goal node for a new job."""
        job_id = event.job_id
        state = _TrailJobState()
        self._job_state[job_id] = state

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        # Fetch prompt from the job row (job_created payload is empty)
        prompt = ""
        try:
            async with self._session_factory() as session:

                result = await session.execute(
                    sa_select(JobRow).where(JobRow.id == job_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    prompt = row.prompt or ""
        except Exception:
            log.debug("trail_goal_prompt_fetch_failed", job_id=job_id, exc_info=True)

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,  # self-anchored
            parent_id=None,
            kind="goal",
            deterministic_kind="goal",
            phase=state.current_phase,
            timestamp=event.timestamp,
            enrichment="complete",  # goal intent is the prompt text — no LLM needed
            intent=prompt or None,
            step_id=None,
            span_ids=None,
            turn_id=None,
            files=None,
            start_sha=None,
            end_sha=None,
        )
        state.active_goal_id = node_id
        await self._repo.create(node)
        log.debug("trail_goal_created", job_id=job_id, node_id=node_id)

    def _on_step_started(self, event: DomainEvent) -> None:
        """Track the currently active step for approval anchoring."""
        state = self._job_state.get(event.job_id)
        if state:
            state.active_step_id = event.payload.get("step_id")

    async def _on_step_completed(self, event: DomainEvent) -> None:
        """Create a deterministic trail node from step completion data."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            # Job started before trail service was active — skip
            return

        payload = event.payload
        kind = _classify_step(payload)
        step_id = payload.get("step_id")

        files_read = payload.get("files_read") or []
        files_written = payload.get("files_written") or []
        all_files = list(dict.fromkeys(files_written + files_read))  # dedupe, writes first

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,  # deterministic nodes are self-anchored
            parent_id=state.active_goal_id,
            kind=kind,
            deterministic_kind=kind,
            phase=state.current_phase,
            timestamp=event.timestamp,
            enrichment="pending",
            step_id=step_id,
            turn_id=None,
            files=json.dumps(all_files, ensure_ascii=False) if all_files else None,
            start_sha=payload.get("start_sha"),
            end_sha=payload.get("end_sha"),
        )
        await self._repo.create(node)
        log.debug(
            "trail_step_node_created",
            job_id=job_id,
            node_id=node_id,
            kind=kind,
            step_id=step_id,
        )

        # Emit any pending events that were waiting for this step
        if state.pending_events:
            pending = state.pending_events[:]
            state.pending_events.clear()
            for pending_event in pending:
                await self._emit_pending_event(pending_event, state, anchor_seq=seq)

    async def _emit_pending_event(
        self,
        event: DomainEvent,
        state: _TrailJobState,
        anchor_seq: int,
    ) -> None:
        """Emit a deferred event (e.g. approval_requested that arrived before step_completed)."""
        job_id = event.job_id
        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=anchor_seq,
            parent_id=state.active_goal_id,
            kind="request",
            deterministic_kind="request",
            phase=state.current_phase,
            timestamp=event.timestamp,
            enrichment="complete",
            intent=event.payload.get("description"),
            step_id=state.active_step_id,
        )
        await self._repo.create(node)
        log.debug("trail_request_node_created", job_id=job_id, node_id=node_id)

    async def _on_phase_changed(self, event: DomainEvent) -> None:
        """Create a summarize node for execution phase transitions."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        phase = event.payload.get("phase", "unknown")
        state.current_phase = phase

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,  # self-anchored phase boundary
            parent_id=state.active_goal_id,
            kind="summarize",
            deterministic_kind="summarize",
            phase=phase,
            timestamp=event.timestamp,
            enrichment="complete",  # no LLM needed
            intent=f"Phase: {phase}",
        )
        await self._repo.create(node)
        log.debug("trail_summarize_created", job_id=job_id, phase=phase)

    async def _on_approval_requested(self, event: DomainEvent) -> None:
        """Create a request node or defer if step hasn't completed yet."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        # If we have an active step, we can anchor to it
        if state.active_step_id:
            # The step's node may not exist yet — defer to step_completed
            state.pending_events.append(event)
            log.debug("trail_request_deferred", job_id=job_id)
        else:
            # No active step — emit immediately as self-anchored
            node_id = _make_node_id()
            seq = state.next_seq
            state.next_seq += 1

            node = TrailNodeRow(
                id=node_id,
                job_id=job_id,
                seq=seq,
                anchor_seq=seq,
                parent_id=state.active_goal_id,
                kind="request",
                deterministic_kind="request",
                phase=state.current_phase,
                timestamp=event.timestamp,
                enrichment="complete",
                intent=event.payload.get("description"),
            )
            await self._repo.create(node)
            log.debug("trail_request_created", job_id=job_id, node_id=node_id)

    async def _on_job_terminal(self, event: DomainEvent) -> None:
        """Create a terminal summarize node and clean up per-job state."""
        job_id = event.job_id
        state = self._job_state.get(job_id)
        if not state:
            return

        node_id = _make_node_id()
        seq = state.next_seq
        state.next_seq += 1

        status = "completed" if event.kind == DomainEventKind.job_completed else "failed"
        if event.kind == DomainEventKind.job_canceled:
            status = "canceled"

        node = TrailNodeRow(
            id=node_id,
            job_id=job_id,
            seq=seq,
            anchor_seq=seq,  # self-anchored
            parent_id=state.active_goal_id,
            kind="summarize",
            deterministic_kind="summarize",
            phase="terminal",
            timestamp=event.timestamp,
            enrichment="complete",
            intent=f"Job {status}",
        )
        await self._repo.create(node)

        # Clean up per-job state
        del self._job_state[job_id]
        log.debug("trail_job_terminal", job_id=job_id, status=status)

    # ------------------------------------------------------------------
    # Enrichment drain loop (Phase 2)
    # ------------------------------------------------------------------

    async def drain_enrichment(self) -> int:
        """Process a batch of nodes needing enrichment. Returns count processed."""
        if not self._completer:
            return 0

        nodes = await self._repo.get_pending_enrichment(limit=self._config.enrich_batch_size)
        if not nodes:
            return 0

        processed = 0
        # Group by job_id for context
        by_job: dict[str, list[TrailNodeRow]] = {}
        for node in nodes:
            by_job.setdefault(node.job_id, []).append(node)

        for job_id, job_nodes in by_job.items():
            try:
                # Get goal intent for context
                goal_nodes = await self._repo.get_by_job(job_id, kinds=["goal"], limit=1)
                goal_intent = goal_nodes[0].intent if goal_nodes else None

                # Get recent decisions for supersedes linking
                recent_decisions = await self._repo.get_recent_decisions(
                    job_id, limit=self._config.enrich_decisions_context,
                )

                prompt = _build_enrichment_prompt(job_nodes, goal_intent, recent_decisions)
                full_prompt = f"SYSTEM:\n{_ENRICH_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                result = await self._completer.complete(full_prompt)
                result_text = result if isinstance(result, str) else str(result)

                enrichment_data = _parse_enrichment_response(result_text)
                if not enrichment_data:
                    # Unparseable — mark as failed for retry
                    for node in job_nodes:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    continue

                # Apply annotations to existing nodes
                node_map = {n.id: n for n in job_nodes}
                for annotation in enrichment_data.get("annotations", []):
                    nid = annotation.get("node_id")
                    if nid not in node_map:
                        continue

                    source_node = node_map[nid]
                    new_kind = annotation.get("kind")

                    # Validate kind reclassification rules
                    if new_kind and new_kind != source_node.kind:
                        if source_node.kind in ("modify", "explore"):
                            new_kind = None  # high-confidence — don't reclassify
                        elif new_kind not in _ALL_KINDS:
                            new_kind = None  # invalid kind

                    # Validate supersedes FK
                    sup = annotation.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    # Validate/normalize file paths
                    files = annotation.get("files")
                    if files and isinstance(files, list):
                        files = [_normalize_path(f) for f in files if isinstance(f, str)]
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
                    )
                    processed += 1

                # Create semantic nodes
                for semantic in enrichment_data.get("semantic_nodes", []):
                    s_kind = semantic.get("kind")
                    if s_kind not in _SEMANTIC_KINDS:
                        continue

                    anchor_nid = semantic.get("anchor_node_id")
                    anchor_node = node_map.get(anchor_nid) if anchor_nid else None

                    # Determine anchor_seq and parent
                    if anchor_node:
                        anchor_seq = anchor_node.anchor_seq
                        parent_id = anchor_node.parent_id
                    else:
                        # Fallback: use first node's anchor
                        anchor_seq = job_nodes[0].anchor_seq
                        parent_id = job_nodes[0].parent_id

                    # Get next seq (post-cleanup fallback)
                    state = self._job_state.get(job_id)
                    if state:
                        seq = state.next_seq
                        state.next_seq += 1
                    else:
                        seq = await self._repo.max_seq(job_id) + 1

                    # Validate supersedes FK
                    sup = semantic.get("supersedes")
                    if sup:
                        existing = await self._repo.get(sup)
                        if not existing:
                            sup = None

                    s_node = TrailNodeRow(
                        id=_make_node_id(),
                        job_id=job_id,
                        seq=seq,
                        anchor_seq=anchor_seq,
                        parent_id=parent_id,
                        kind=s_kind,
                        deterministic_kind=None,  # enrichment-created
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

            except Exception:
                log.debug("trail_enrichment_failed", job_id=job_id, exc_info=True)
                for node in job_nodes:
                    try:
                        await self._repo.update_enrichment(node.id, enrichment="failed")
                    except Exception:
                        pass

        return processed

    async def drain_loop(self) -> None:
        """Run forever, periodically processing nodes needing enrichment."""
        while True:
            try:
                count = await self.drain_enrichment()
                if count:
                    log.info("trail_enrichment_batch_processed", count=count)
            except Exception:
                log.debug("trail_enrichment_drain_error", exc_info=True)
            await asyncio.sleep(self._config.enrich_interval_seconds)

    # ------------------------------------------------------------------
    # Query helpers (used by API routes)
    # ------------------------------------------------------------------

    async def get_trail(
        self,
        job_id: str,
        *,
        kinds: list[str] | None = None,
        flat: bool = False,
        after_seq: int | None = None,
    ) -> dict:
        """Fetch trail for a job. Returns dict suitable for TrailResponse."""
        nodes = await self._repo.get_by_job(job_id, kinds=kinds, after_seq=after_seq)
        total, enriched = await self._repo.count_by_job(job_id)

        node_dicts = [_node_to_dict(n) for n in nodes]

        if flat:
            return {
                "job_id": job_id,
                "nodes": node_dicts,
                "total_nodes": total,
                "enriched_nodes": enriched,
                "complete": total == enriched,
            }

        # Build nested tree
        tree = _build_tree(node_dicts)
        return {
            "job_id": job_id,
            "nodes": tree,
            "total_nodes": total,
            "enriched_nodes": enriched,
            "complete": total == enriched,
        }

    async def get_summary(self, job_id: str) -> dict:
        """Build a lightweight trail summary from node data."""
        nodes = await self._repo.get_by_job(job_id)
        total, enriched = await self._repo.count_by_job(job_id)

        goals: list[str] = []
        approach_parts: list[str] = []
        key_decisions: list[dict] = []
        backtracks: list[dict] = []
        explore_files: set[str] = set()
        modify_files: set[str] = set()
        verify_pass = 0
        verify_fail = 0

        for node in nodes:
            files = json.loads(node.files) if node.files else []

            if node.kind == "goal" and node.intent:
                goals.append(node.intent)
            elif node.kind in ("plan", "modify") and node.intent:
                approach_parts.append(node.intent)
            elif node.kind == "decide" and node.intent:
                key_decisions.append({
                    "decision": node.intent,
                    "rationale": node.rationale,
                })
            elif node.kind == "backtrack" and node.intent:
                backtracks.append({
                    "original": node.supersedes or "(unknown)",
                    "replacement": node.intent,
                    "reason": node.rationale,
                })
            elif node.kind == "explore":
                explore_files.update(files)
            elif node.kind == "verify":
                # Simple heuristic: if outcome contains "fail" or "error", count as failed
                outcome = (node.outcome or "").lower()
                if "fail" in outcome or "error" in outcome:
                    verify_fail += 1
                else:
                    verify_pass += 1

            if node.kind == "modify":
                modify_files.update(files)

        approach = " → ".join(approach_parts) if approach_parts else None

        return {
            "job_id": job_id,
            "goals": goals,
            "approach": approach,
            "key_decisions": key_decisions,
            "backtracks": backtracks,
            "files_explored": len(explore_files),
            "files_modified": len(modify_files),
            "verifications_passed": verify_pass,
            "verifications_failed": verify_fail,
            "enrichment_complete": total == enriched,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_enrichment_response(text: str) -> dict | None:
    """Parse LLM enrichment response, stripping markdown fences."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        log.debug("trail_enrichment_parse_failed")
    return None


def _normalize_path(path: str) -> str:
    """Normalize a file path to repo-relative."""
    # Strip leading ./ or /
    path = path.lstrip("./")
    if path.startswith("/"):
        path = path.lstrip("/")
    return path


def _node_to_dict(node: TrailNodeRow) -> dict:
    """Convert a TrailNodeRow to a response dict."""
    return {
        "id": node.id,
        "seq": node.seq,
        "anchor_seq": node.anchor_seq,
        "parent_id": node.parent_id,
        "kind": node.kind,
        "deterministic_kind": node.deterministic_kind,
        "phase": node.phase,
        "timestamp": node.timestamp,
        "enrichment": node.enrichment,
        "intent": node.intent,
        "rationale": node.rationale,
        "outcome": node.outcome,
        "step_id": node.step_id,
        "span_ids": json.loads(node.span_ids) if node.span_ids else [],
        "turn_id": node.turn_id,
        "files": json.loads(node.files) if node.files else [],
        "start_sha": node.start_sha,
        "end_sha": node.end_sha,
        "supersedes": node.supersedes,
        "tags": json.loads(node.tags) if node.tags else [],
        "children": [],
    }


def _build_tree(nodes: list[dict]) -> list[dict]:
    """Build a nested tree from flat node dicts using parent_id."""
    by_id: dict[str, dict] = {}
    roots: list[dict] = []

    for n in nodes:
        by_id[n["id"]] = n

    for n in nodes:
        pid = n.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(n)
        else:
            roots.append(n)

    return roots
