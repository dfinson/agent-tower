"""Trail query service — read-only access to trail data for API routes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from backend.models.db import TrailNodeRow
from backend.persistence.trail_repo import TrailNodeRepository
from backend.services.trail.models import TrailNodeDict, TrailResponse, TrailSummary, _BacktrackDict, _DecisionDict

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TrailQueryService:
    """Read-only trail queries used by API endpoints."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._repo = TrailNodeRepository(session_factory)

    async def get_trail(
        self,
        job_id: str,
        *,
        kinds: list[str] | None = None,
        flat: bool = False,
        after_seq: int | None = None,
    ) -> TrailResponse:
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

        tree = _build_tree(node_dicts)
        return {
            "job_id": job_id,
            "nodes": tree,
            "total_nodes": total,
            "enriched_nodes": enriched,
            "complete": total == enriched,
        }

    async def get_summary(self, job_id: str) -> TrailSummary:
        """Build a lightweight trail summary from node data."""
        nodes = await self._repo.get_by_job(job_id)
        total, enriched = await self._repo.count_by_job(job_id)

        goals: list[str] = []
        approach_parts: list[str] = []
        key_decisions: list[dict[str, Any]] = []
        backtracks: list[dict[str, Any]] = []
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
            "key_decisions": cast("list[_DecisionDict]", key_decisions),
            "backtracks": cast("list[_BacktrackDict]", backtracks),
            "files_explored": len(explore_files),
            "files_modified": len(modify_files),
            "verifications_passed": verify_pass,
            "verifications_failed": verify_fail,
            "enrichment_complete": total == enriched,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _node_to_dict(node: TrailNodeRow) -> TrailNodeDict:
    """Convert a TrailNodeRow to a response dict."""
    return {
        "id": node.id,
        "seq": node.seq,
        "anchor_seq": node.anchor_seq,
        "parent_id": node.parent_id,
        "kind": node.kind,
        "deterministic_kind": node.deterministic_kind,
        "phase": node.phase,
        "timestamp": node.timestamp.isoformat() if node.timestamp else None,
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
        "title": node.title,
        "agent_message": node.agent_message,
        "tool_names": json.loads(node.tool_names) if node.tool_names else [],
        "tool_count": node.tool_count,
        "duration_ms": node.duration_ms,
        "plan_item_id": node.plan_item_id,
        "plan_item_label": node.plan_item_label,
        "plan_item_status": node.plan_item_status,
        "activity_id": node.activity_id,
        "activity_label": node.activity_label,
        "tier": node.tier,
        "reversible": node.reversible,
        "contained": node.contained,
        "tier_reason": node.tier_reason,
        "checkpoint_ref": node.checkpoint_ref,
        "children": [],
    }


def _build_tree(nodes: list[TrailNodeDict]) -> list[TrailNodeDict]:
    """Build a nested tree from flat node dicts using parent_id."""
    by_id: dict[str, TrailNodeDict] = {}
    roots: list[TrailNodeDict] = []

    for n in nodes:
        by_id[n["id"]] = n

    for n in nodes:
        pid = n.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(n)
        else:
            roots.append(n)

    return roots
