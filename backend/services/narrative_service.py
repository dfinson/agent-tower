"""Agent Narrative service (§11A) — assembles the cognitive journey narrative.

Answers "Do I trust this agent's judgment?" by chronicling decisions,
backtracks, insights, and verification arcs from trail enrichment data.

No new data collection — the narrative is assembled entirely from existing
trail infrastructure (enriched semantic nodes, activity groups, plan steps).
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any, TypedDict

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.naming_service import Completable

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------


class NarrativeBeat(TypedDict, total=False):
    """A semantic turning point in the narrative."""

    kind: str  # decide | backtrack | insight | verify | plan
    intent: str
    rationale: str
    outcome: str
    supersedes: str | None
    files: list[str]
    seq: int
    activity_label: str | None


class NarrativeBlock(TypedDict, total=False):
    """A block in the narrative output."""

    type: str  # prose | beat | lede | outcome
    text: str
    beat_kind: str  # for type=beat
    files: list[str]  # for type=beat


class NarrativeResponse(TypedDict, total=False):
    job_id: str
    blocks: list[NarrativeBlock]
    beat_count: int
    has_decisions: bool
    has_backtracks: bool
    verbosity: str
    cached: bool


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_NARRATIVE_SYSTEM = (
    "You write first-person cognitive narratives of coding sessions. You "
    "receive the agent's trail of decisions, backtracks, insights, and "
    "verifications — the semantic turning points of its work. Write a "
    "chronological narrative that shows how the agent thought, not just "
    "what it did.\n\n"
    #
    "VOICE: Write like a senior engineer explaining their decision process. "
    "Lead with findings and insights, not actions. 'The MCP caller uses "
    "dynamic dispatch' is a finding. 'I read the MCP tool file' is an "
    "action log entry — never acceptable.\n\n"
    #
    "BEATS: Each beat (DECIDE, BACKTRACK, INSIGHT, VERIFY) is a turning "
    "point. Format each as a paragraph that names the constraint, the "
    "choice made, and why. For backtracks, explain what went wrong and "
    "what changed. For insights, explain what was discovered and how it "
    "shaped subsequent work.\n\n"
    #
    "STRUCTURE:\n"
    "- LEDE: One paragraph explaining the task and why it matters.\n"
    "- BODY: Chronological prose weaving beats into a narrative arc. "
    "Group by activity when multiple activities exist.\n"
    "- OUTCOME: What was accomplished, what remains open.\n\n"
    #
    "ANTI-PATTERNS:\n"
    "- Never narrate navigation ('I opened X, then searched for Y').\n"
    "- Never self-assess ('This was complex', 'I elegantly refactored').\n"
    "- Never fabricate reasoning not present in the trail data.\n"
    "- If there are zero decisions and zero backtracks, write only a "
    "3-sentence executive summary.\n\n"
    #
    "FORMAT: Return blocks separated by ---BLOCK--- markers.\n"
    "First block type is 'lede'. Last block type is 'outcome'. "
    "Middle blocks alternate between 'prose' (narrative transitions) and "
    "'beat' blocks. Beat blocks start with [DECIDE], [BACKTRACK], "
    "[INSIGHT], or [VERIFY] on the first line.\n"
    "Plain prose paragraphs, no markdown headers or bullets. "
    "Backtick-wrapped `symbols` encouraged. First person."
)

_VERBOSITY_SUFFIX = {
    "brief": ("\n\nVERBOSITY=brief: Executive summary only. Decisions and backtracks in single sentences."),
    "standard": "",
    "detailed": (
        "\n\nVERBOSITY=detailed: Full arc with exploration details, "
        "alternatives considered at each decision point, and expanded "
        "verification results."
    ),
}


# ---------------------------------------------------------------------------
# Narrative assembly
# ---------------------------------------------------------------------------


async def _fetch_beats(session: AsyncSession, job_id: str) -> list[NarrativeBeat]:
    """Fetch enriched semantic trail nodes for narrative beats."""
    from sqlalchemy import select

    from backend.models.db import TrailNodeRow

    semantic_kinds = ["decide", "backtrack", "insight", "verify", "plan"]
    stmt = (
        select(TrailNodeRow)
        .where(TrailNodeRow.job_id == job_id)
        .where(TrailNodeRow.enrichment == "complete")
        .where(TrailNodeRow.kind.in_(semantic_kinds))
        .order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
    )
    result = await session.execute(stmt)
    nodes = list(result.scalars().all())

    beats: list[NarrativeBeat] = []
    for node in nodes:
        files_list: list[str] = []
        if node.files:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                files_list = json.loads(node.files)
        beat: NarrativeBeat = {"kind": node.kind, "seq": node.seq}
        if node.intent:
            beat["intent"] = node.intent
        if node.rationale:
            beat["rationale"] = node.rationale
        if node.outcome:
            beat["outcome"] = node.outcome
        if node.supersedes:
            beat["supersedes"] = node.supersedes
        if files_list:
            beat["files"] = files_list
        if node.activity_label:
            beat["activity_label"] = node.activity_label
        beats.append(beat)
    return beats


async def _fetch_context(session: AsyncSession, job_id: str) -> dict[str, Any]:
    """Fetch lightweight job + activity context for the prompt."""
    from sqlalchemy import text

    ctx: dict[str, Any] = {}

    row = await session.execute(
        text("SELECT title, description, prompt FROM jobs WHERE id = :jid"),
        {"jid": job_id},
    )
    job = row.mappings().first()
    if job:
        ctx["title"] = job["title"]
        ctx["prompt"] = job["prompt"]
        ctx["description"] = job["description"]

    # Activity groups
    from sqlalchemy import func, select

    from backend.models.db import TrailNodeRow

    stmt = (
        select(
            TrailNodeRow.activity_label,
            func.count().label("count"),
        )
        .where(TrailNodeRow.job_id == job_id)
        .where(TrailNodeRow.activity_label.isnot(None))
        .group_by(TrailNodeRow.activity_label)
        .order_by(func.min(TrailNodeRow.seq))
    )
    result = await session.execute(stmt)
    activities = [{"label": r[0], "steps": r[1]} for r in result.all()]
    if activities:
        ctx["activities"] = activities

    return ctx


def _build_prompt(
    beats: list[NarrativeBeat],
    context: dict[str, Any],
    verbosity: str = "standard",
) -> str:
    """Build the LLM prompt from beats and context."""
    parts: list[str] = []

    # Job context
    title = context.get("title") or "Untitled"
    prompt = context.get("prompt") or "(no prompt)"
    parts.append(f"TASK: {title}")
    parts.append(f"PROMPT: {prompt}")

    if context.get("description"):
        parts.append(f"DESCRIPTION: {context['description']}")

    # Activities
    activities = context.get("activities", [])
    if activities:
        parts.append("\nACTIVITY GROUPS:")
        for act in activities:
            parts.append(f"  - {act['label']} ({act['steps']} steps)")

    # Beats
    parts.append(f"\nTRAIL BEATS ({len(beats)} total):")
    for beat in beats:
        kind = beat.get("kind", "unknown").upper()
        intent = beat.get("intent", "")
        rationale = beat.get("rationale", "")
        outcome = beat.get("outcome", "")
        files = beat.get("files", [])
        supersedes = beat.get("supersedes")
        activity = beat.get("activity_label", "")

        line = f"  [{kind}] {intent}"
        if rationale:
            line += f" | Rationale: {rationale}"
        if outcome:
            line += f" | Outcome: {outcome}"
        if files:
            line += f" | Files: {', '.join(files)}"
        if supersedes:
            line += f" | Supersedes: {supersedes}"
        if activity:
            line += f" | Activity: {activity}"
        parts.append(line)

    if not beats:
        parts.append("  (no semantic beats — agent had a straightforward run)")

    prompt_text = "\n".join(parts)

    suffix = _VERBOSITY_SUFFIX.get(verbosity, "")
    return f"SYSTEM:\n{_NARRATIVE_SYSTEM}{suffix}\n\nUSER:\n{prompt_text}"


def _parse_blocks(raw: str) -> list[NarrativeBlock]:
    """Parse LLM output into narrative blocks."""
    raw = raw.strip()

    # Split on ---BLOCK--- markers
    if "---BLOCK---" in raw:  # noqa: SIM108
        segments = [s.strip() for s in raw.split("---BLOCK---") if s.strip()]
    else:
        # Fallback: treat as single prose block
        segments = [raw]

    blocks: list[NarrativeBlock] = []
    for i, seg in enumerate(segments):
        if not seg:
            continue

        # Detect beat blocks by leading tag
        beat_kind = None
        for tag in ["[DECIDE]", "[BACKTRACK]", "[INSIGHT]", "[VERIFY]"]:
            if seg.startswith(tag):
                beat_kind = tag[1:-1].lower()
                seg = seg[len(tag) :].strip()
                break

        if beat_kind:
            block: NarrativeBlock = {"type": "beat", "text": seg, "beat_kind": beat_kind}
            blocks.append(block)
        elif i == 0:
            blocks.append({"type": "lede", "text": seg})
        elif i == len(segments) - 1 and len(segments) > 1:
            blocks.append({"type": "outcome", "text": seg})
        else:
            blocks.append({"type": "prose", "text": seg})

    return blocks


class NarrativeService:
    """Generates agent cognitive journey narratives from trail data."""

    def __init__(self, completer: Completable) -> None:
        self._completer = completer

    async def generate(
        self,
        session: AsyncSession,
        job_id: str,
        verbosity: str = "standard",
    ) -> NarrativeResponse:
        """Generate the agent narrative for a job."""
        beats = await _fetch_beats(session, job_id)
        context = await _fetch_context(session, job_id)

        has_decisions = any(b.get("kind") == "decide" for b in beats)
        has_backtracks = any(b.get("kind") == "backtrack" for b in beats)

        # If no interesting beats, return a minimal summary
        if not beats:
            return {
                "job_id": job_id,
                "blocks": [
                    {
                        "type": "lede",
                        "text": (
                            "The agent completed this task without notable decision "
                            "points, direction changes, or verification failures. "
                            "See the Review tab for structural analysis of the changes."
                        ),
                    }
                ],
                "beat_count": 0,
                "has_decisions": False,
                "has_backtracks": False,
                "verbosity": verbosity,
                "cached": False,
            }

        prompt = _build_prompt(beats, context, verbosity)

        try:
            raw = await self._completer.complete(prompt)
            blocks = _parse_blocks(raw)
        except Exception:
            log.warning("narrative_generation_failed", job_id=job_id, exc_info=True)
            # Fallback: render beats directly without LLM prose
            blocks = _beats_to_fallback_blocks(beats, context)

        return {
            "job_id": job_id,
            "blocks": blocks,
            "beat_count": len(beats),
            "has_decisions": has_decisions,
            "has_backtracks": has_backtracks,
            "verbosity": verbosity,
            "cached": False,
        }


def _beats_to_fallback_blocks(
    beats: list[NarrativeBeat],
    context: dict[str, Any],
) -> list[NarrativeBlock]:
    """Render beats as structured blocks without LLM generation."""
    blocks: list[NarrativeBlock] = []

    title = context.get("title") or "this task"
    blocks.append(
        {
            "type": "lede",
            "text": f"The agent worked on {title}. During execution, {len(beats)} notable moments were recorded.",
        }
    )

    for beat in beats:
        kind = beat.get("kind", "unknown")
        intent = beat.get("intent", "")
        rationale = beat.get("rationale", "")
        outcome = beat.get("outcome", "")
        text_parts = [intent]
        if rationale:
            text_parts.append(rationale)
        if outcome:
            text_parts.append(outcome)
        blocks.append(
            {
                "type": "beat",
                "text": " — ".join(p for p in text_parts if p),
                "beat_kind": kind,
                "files": beat.get("files", []),
            }
        )

    return blocks
