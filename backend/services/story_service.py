"""Story generation service — assembles a structured code-review narrative
from trail data: validated change references interleaved with LLM-
generated connective prose, enriched with agent decision beats.

The key design principle: *references are never LLM-generated*.  They are
built from trail ``write`` sub-nodes (§13.1), ordered chronologically.
The LLM generates the prose that connects them, weaving in trail beats
(decisions, backtracks, insights, verifications) as inline narrative
turning points.

Stories are generated on demand and cached as JSON on the ``jobs.story_text``
column.  When trail enrichment is still pending, stories are returned
uncached — enabling live rolling generation as the agent works.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any, TypedDict, cast

import httpx
import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.coderecon_service import CodeReconService
    from backend.services.naming_service import Completable

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Internal typed dicts for story data shapes
# ---------------------------------------------------------------------------


class StoryReference(TypedDict, total=False):
    spanId: str
    file: str
    why: str
    stepNumber: int | None
    stepTitle: str
    turnId: str
    editCount: int
    snippet: str
    editDetails: list[dict[str, str]]
    isRetry: bool
    errorKind: str
    phase: str
    stepIntent: str
    activityLabel: str


class _JobContext(TypedDict, total=False):
    id: str
    title: str | None
    description: str | None
    prompt: str
    state: str
    model: str | None


class _TelemetryContext(TypedDict, total=False):
    duration_ms: int | None
    total_cost_usd: float | None
    tool_call_count: int
    tool_failure_count: int
    retry_count: int


class _ApprovalContext(TypedDict, total=False):
    description: str
    resolution: str | None
    requires_explicit_approval: bool
    proposed_action: str


class StoryContext(TypedDict, total=False):
    job: _JobContext
    telemetry: _TelemetryContext
    approvals: list[_ApprovalContext]
    trail_beats: list[TrailBeat]


class StoryBlock(TypedDict, total=False):
    type: str
    text: str
    beatKind: str
    spanId: str
    file: str
    why: str
    stepNumber: int | None
    stepTitle: str
    turnId: str
    editCount: int
    snippet: str
    editDetails: list[dict[str, str]]
    isRetry: bool
    errorKind: str
    phase: str
    stepIntent: str
    activityLabel: str


class TrailBeat(TypedDict, total=False):
    kind: str
    intent: str
    rationale: str
    outcome: str
    supersedes: str | None
    files: list[str]
    seq: int
    activity_label: str | None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_STORY_SYSTEM = (
    "You write compelling technical narratives about coding sessions. You "
    "receive code changes with snippets, the agent's cognitive trail "
    "(decisions, backtracks, insights, verifications), and session context. "
    "Write a first-person narrative that a human reviewer can follow like "
    "a blog post — one that earns their attention and holds it.\n\n"
    #
    # Narrative voice
    "VOICE: Write like a senior engineer explaining their work to a colleague "
    "over coffee — candid, specific, occasionally wry. Set the scene: what "
    "was the task, what system does it touch, why does it matter, what was "
    "at stake. Then walk through the work chronologically. Every paragraph "
    "should teach the reader something they didn't know before reading it. "
    "Dry wit is welcome — self-deprecating observations about the code or "
    "the journey keep the reader engaged. Never be corny, never force humor, "
    "never self-congratulate.\n\n"
    #
    # Rendering context — markers become embedded diff blocks
    "RENDERING: Each [[N]] marker is rendered as a full embedded diff block "
    "showing the filename, line counts, and actual code changes. The reader "
    "sees your prose interrupted by a bordered code card — like a figure in "
    "an article. Your text must set up each diff so it reads naturally:\n"
    '  GOOD: "I added the validation middleware: [[3]]"\n'
    '  GOOD: "The auth handler needed a null check, so I updated it: [[5]]"\n'
    '  BAD:  "I updated the auth module [[3]] and then fixed tests [[4]]" '
    "(markers dropped mid-sentence become visual noise)\n"
    '  BAD:  "[[3]] was the next change" (leading with a diff block is disorienting)\n'
    "Place each [[N]] at a sentence boundary where the reader expects to see "
    "code. The reader should always know what they are about to see BEFORE "
    "the diff appears.\n\n"
    #
    # Beat markers — cognitive turning points
    "BEATS: You receive AGENT JOURNEY beats — decisions, backtracks, insights, "
    "and verifications. These are the skeleton of the story. Weave them into "
    "the chronological flow using beat markers:\n"
    "  {{DECIDE}} — before prose about a deliberate choice between alternatives\n"
    "  {{BACKTRACK}} — before prose about the agent reversing course\n"
    "  {{INSIGHT}} — before prose about a non-obvious discovery\n"
    "  {{VERIFY}} — before prose about testing or validation\n"
    "A beat marker goes on its own line, followed by one or more prose "
    "paragraphs about that turning point. Not every beat needs a marker — "
    "minor decisions can be woven into regular prose. Use markers for "
    "moments the reader should notice. Backtracks are the most engaging "
    "parts of a technical narrative — lean into the problem-solving arc.\n\n"
    #
    # Structure
    "STRUCTURE: Open with a paragraph that sets context — what is this system, "
    "what was the task, why does it matter to the project. Then walk through "
    "changes and decisions chronologically. Close with the outcome and any "
    "remaining risks.\n\n"
    #
    # Length
    "LENGTH: Write enough to actually tell the story. Scale length to "
    "the number and complexity of changes — a session with two small "
    "fixes needs far less prose than one with a multi-file refactor. "
    "If a change involves a design decision, explain the alternatives "
    "considered and why this path won. Do NOT compress the narrative into "
    "terse bullet-point-like sentences. Each paragraph should flow into "
    "the next.\n\n"
    #
    # Investigative milestones
    "INVESTIGATIVE TASKS: When there are no file changes but the agent "
    "explored, analyzed, or investigated — this is an insight story. "
    "The trail beats ARE the story. Chronicle what was examined, what "
    "was discovered, what hypotheses were tested and discarded. The "
    "reader should feel like they walked through the investigation "
    "with the agent. Use {{INSIGHT}} and {{DECIDE}} markers liberally. "
    "Even without code changes, these narratives should be vivid and "
    "specific — name the files examined, the patterns found, the "
    "conclusions reached.\n\n"
    #
    # Inline code
    "INLINE CODE: Weave code into your narrative — quote key lines, name "
    "specific functions, variables, and expressions using `backticks`. "
    "The reader should encounter real code in your prose before they see "
    "the full diff card.\n\n"
    #
    # Objectivity with personality
    "TONE: State what you did and why. No self-assessment of difficulty "
    '("This was complex"), no hedging ("I thought maybe"). Let facts speak. '
    "But you can observe the absurd — a function named `handleEverything()`, "
    "a config file with more lines than the service it configures, a test "
    "that tests nothing. Brief, factual observations that make the reader "
    "nod. Never mean, never sarcastic about other people's code — just "
    "honest.\n\n"
    #
    # Connective prose
    "TRANSITIONS: Between [[N]] markers and {{BEAT}} markers, write motivation, "
    "context, and discoveries — why you moved to the next change, what you "
    "found when you looked at the existing code, what constraint or insight "
    "shaped the approach.\n\n"
    #
    # Contextual recall
    "RECALL: When you reference a symbol introduced earlier, add a brief "
    "contextual tag on later mentions — 'the approval entry point "
    "`create_request()`' rather than bare '`create_request()`'. "
    "First mention: full introduction. Mentions within 1-2 paragraphs: "
    "bare name is fine. Later mentions: brief role tag.\n\n"
    #
    # Retry arcs
    "RETRY ARCS: When a change is marked [RETRY], the original attempt "
    "failed. Tell the reader what happened — what error occurred, what the "
    "agent tried first, and why the second attempt succeeded. Use a "
    "{{BACKTRACK}} marker for these.\n\n"
    #
    # Activity groups
    "ACTIVITIES: Changes may be grouped under activity labels. Use these as "
    "natural chapter transitions — the reader should sense when the work "
    "shifts from one concern to another.\n\n"
    #
    # Format constraints
    "FORMAT: Plain prose paragraphs only. No markdown headers, bullets, or "
    "code blocks — output renders inline. Backtick-wrapped `symbols` are "
    "allowed and encouraged. First person ('I started by…'). "
    "Contractions fine. No emoji or exclamation marks. "
    "Every change MUST be referenced by its [[N]] marker at least once. "
    "Beat markers ({{DECIDE}}, {{BACKTRACK}}, {{INSIGHT}}, {{VERIFY}}) go "
    "on their own line before the relevant prose."
)


_STORY_VERBOSITY_SUFFIX = {
    "summary": (
        "\n\nVERBOSITY=summary: Write a short executive summary — a few "
        "sentences that name the key symbols and decisions. Reference each "
        "change by [[N]]. Even in summary mode, set minimal context — what "
        "system was involved, what changed, what risk remains."
    ),
    "standard": "",
    "detailed": (
        "\n\nVERBOSITY=detailed: Write a thorough technical narrative — the "
        "kind of thing you'd post on an engineering blog. For each change, "
        "explain what the existing code looked like before, what problem that "
        "created, what the new code does (quote key lines from the snippets), "
        "what alternatives you considered, and what tradeoffs you made. "
        "The reader should understand not just what changed but the full "
        "technical context — the shape of the codebase before the change, "
        "the constraint that made the change necessary, and exactly what "
        "the new code looks like. This is a technical document for "
        "reviewers, not a summary for managers."
    ),
}


def _truncate(s: str | None, max_len: int) -> str:
    if not s:
        return ""
    return s[:max_len] + ("…" if len(s) > max_len else "")




# ---------------------------------------------------------------------------
# Reference extraction — reads from trail write sub-nodes (§13.1)
# ---------------------------------------------------------------------------

async def _build_references(
    session: "AsyncSession", job_id: str,
) -> list[StoryReference]:
    """Build validated reference dicts from trail nodes, chronologically.

    Prefers write nodes (file-level changes with snippets).  When no write
    nodes exist — e.g. investigative or audit tasks — falls back to all
    enriched trail nodes so the story still has anchors.
    """
    from sqlalchemy import select, text

    from backend.models.db import TrailNodeRow

    # Try write nodes first — they're the strongest story anchors
    stmt = (
        select(TrailNodeRow)
        .where(TrailNodeRow.job_id == job_id)
        .where(TrailNodeRow.kind == "write")
        .order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
    )
    result = await session.execute(stmt)
    nodes = list(result.scalars().all())

    # Fallback: use all enriched trail nodes when no writes exist
    if not nodes:
        stmt = (
            select(TrailNodeRow)
            .where(TrailNodeRow.job_id == job_id)
            .where(TrailNodeRow.enrichment == "complete")
            .order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
        )
        result = await session.execute(stmt)
        nodes = list(result.scalars().all())

    if not nodes:
        return []

    # Fetch step metadata (step_number, title, intent) keyed by turn_id
    step_rows = await session.execute(
        text("""
            SELECT turn_id, step_number, title, intent
            FROM steps
            WHERE job_id = :jid
        """),
        {"jid": job_id},
    )
    step_map: dict[str, dict[str, Any]] = {}
    for r in step_rows.mappings():
        if r["turn_id"]:
            step_map[r["turn_id"]] = dict(r)

    # Deduplicate — by file+step for writes, by kind+seq for others
    seen: dict[str, StoryReference] = {}
    for node in nodes:
        file_val = ""
        if node.files:
            files_list = json.loads(node.files)
            file_val = files_list[0] if files_list else ""

        step_info = step_map.get(node.turn_id or "")
        step_number = step_info["step_number"] if step_info else None

        is_write = node.kind == "write"

        if is_write:
            if not file_val or step_number is None:
                key = f"__node_{node.id}"
            else:
                key = f"{file_val}|{step_number}"
        else:
            # Non-write nodes: one entry per kind+seq
            key = f"__{node.kind}_{node.seq}"

        ref: StoryReference = {
            "spanId": node.id,
            "file": file_val,
            "why": node.write_summary or node.intent or node.rationale or "",
            "stepNumber": step_number,
            "stepTitle": _truncate(step_info.get("title") if step_info else None, 60),
            "turnId": node.turn_id or "",
        }
        if node.snippet:
            ref["snippet"] = node.snippet
        if node.is_retry:
            ref["isRetry"] = True
        if node.error_kind:
            ref["errorKind"] = node.error_kind
        if node.phase:
            ref["phase"] = node.phase
        if step_info and step_info.get("intent"):
            ref["stepIntent"] = step_info["intent"]
        # Merge per-edit details if available (write nodes only)
        if is_write and node.edit_motivations:
            try:
                edits = json.loads(node.edit_motivations)
                if isinstance(edits, list) and edits:
                    ref["editCount"] = len(edits)
                    ref["editDetails"] = [
                        {"title": e.get("title", ""), "why": e.get("why", "")}
                        for e in edits
                        if e.get("why")
                    ]
            except (json.JSONDecodeError, TypeError):
                pass

        # Activity label from the node itself
        if node.activity_label:
            ref["activityLabel"] = node.activity_label

        seen[key] = ref

    return list(seen.values())


# ---------------------------------------------------------------------------
# Trail beats extraction (semantic turning points)
# ---------------------------------------------------------------------------

async def _build_trail_beats(
    session: "AsyncSession", job_id: str,
) -> list[TrailBeat]:
    """Fetch enriched semantic trail nodes — decisions, backtracks, insights."""
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

    beats: list[TrailBeat] = []
    for node in nodes:
        files_list: list[str] = []
        if node.files:
            try:
                files_list = json.loads(node.files)
            except (json.JSONDecodeError, TypeError):
                files_list = []
        beat: TrailBeat = {
            "kind": node.kind,
            "seq": node.seq,
        }
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


# ---------------------------------------------------------------------------
# Context collection (non-reference metadata for the prompt)
# ---------------------------------------------------------------------------

async def _collect_context(session: "AsyncSession", job_id: str) -> StoryContext:
    """Gather lightweight context metadata (no file_write spans — those are
    handled by ``_build_references``)."""
    from sqlalchemy import text

    ctx: StoryContext = {}

    # Job metadata
    row = await session.execute(
        text("SELECT id, title, description, prompt, state, model FROM jobs WHERE id = :jid"),
        {"jid": job_id},
    )
    job = row.mappings().first()
    if not job:
        return {}
    ctx["job"] = cast("_JobContext", dict(job))

    # Telemetry summary
    row = await session.execute(
        text("""
            SELECT duration_ms, total_cost_usd, tool_call_count,
                   tool_failure_count, retry_count
            FROM job_telemetry_summary WHERE job_id = :jid
        """),
        {"jid": job_id},
    )
    summary = row.mappings().first()
    if summary:
        ctx["telemetry"] = cast("_TelemetryContext", dict(summary))

    # Approvals
    rows = await session.execute(
        text("""
            SELECT description, resolution, requires_explicit_approval,
                   proposed_action
            FROM approvals WHERE job_id = :jid ORDER BY requested_at ASC
        """),
        {"jid": job_id},
    )
    approvals = [dict(r) for r in rows.mappings()]
    if approvals:
        ctx["approvals"] = cast("list[_ApprovalContext]", approvals)

    # Trail beats — semantic turning points from enriched trail nodes
    beats = await _build_trail_beats(session, job_id)
    if beats:
        ctx["trail_beats"] = beats

    return ctx


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    refs: list[StoryReference], ctx: StoryContext,
) -> str:
    """Build the user prompt listing numbered changes + context."""
    parts: list[str] = []

    job = ctx.get("job", {})
    parts.append("## SESSION CONTEXT")
    parts.append(f"Title: {job.get('title', 'Untitled')}")
    parts.append(f"Task: {_truncate(job.get('prompt') or job.get('description', ''), 400)}")
    telem = ctx.get("telemetry", {})
    if telem:
        dur = round((telem.get("duration_ms") or 0) / 60000, 1)
        parts.append(f"Duration: {dur} min, {telem.get('tool_call_count', 0)} tool calls")
        fails = telem.get("tool_failure_count", 0) or 0
        retries = telem.get("retry_count", 0) or 0
        if fails or retries:
            parts.append(f"Issues: {fails} failures, {retries} retries")

    # Trail beats — narrative turning points
    beats = ctx.get("trail_beats", [])
    if beats:
        parts.append("\n## AGENT JOURNEY (key moments, chronological)")
        for b in beats:
            kind = b.get("kind", "")
            intent = b.get("intent", "")
            line = f"  [{kind.upper()}] {intent}"
            if b.get("rationale"):
                line += f"\n    Rationale: {b['rationale']}"
            if b.get("outcome"):
                line += f"\n    Outcome: {b['outcome']}"
            if kind == "backtrack" and b.get("supersedes"):
                line += " (reverses earlier approach)"
            parts.append(line)

    # Approval decisions with proposed actions
    approvals = ctx.get("approvals", [])
    if approvals:
        parts.append("\n## DECISION POINTS")
        for a in approvals:
            line = f"  - {a.get('description', '')} → {a.get('resolution', 'pending')}"
            if a.get("proposed_action"):
                line += f"\n    Proposed: {a['proposed_action']}"
            parts.append(line)

    # Entries — grouped by activity when available
    has_files = any(ref.get("file") for ref in refs)
    section_label = "CHANGES" if has_files else "SESSION EVENTS"
    parts.append(f"\n## {section_label} ({len(refs)} total, chronological)")

    activities: dict[str, list[tuple[int, StoryReference]]] = {}
    ungrouped: list[tuple[int, StoryReference]] = []
    for i, ref in enumerate(refs, 1):
        label = ref.get("activityLabel", "")
        if label:
            activities.setdefault(label, []).append((i, ref))
        else:
            ungrouped.append((i, ref))

    def _fmt_ref(idx: int, ref: StoryReference) -> list[str]:
        lines: list[str] = []
        anchor = ref.get("file") or ref.get("stepTitle") or ref.get("why") or f"event {idx}"
        line = f"{idx}. **{anchor}**"
        if ref.get("file") and ref.get("stepTitle"):
            line = f"{idx}. **{ref['file']}** (step {ref.get('stepNumber', '?')}: {ref['stepTitle']})"
        if ref.get("isRetry"):
            line += " [RETRY]"
        if ref.get("errorKind"):
            line += f" [error: {ref['errorKind']}]"
        if ref.get("why") and ref.get("why") != anchor:
            line += f" — {ref['why']}"
        if ref.get("editCount") and ref["editCount"] > 1:
            line += f" [{ref['editCount']} edits]"
        lines.append(line)
        if ref.get("stepIntent"):
            lines.append(f"   Intent: {ref['stepIntent']}")
        if ref.get("editDetails"):
            for ed in ref["editDetails"]:
                if ed.get("why"):
                    lines.append(f"   • {ed.get('title', 'edit')}: {ed['why']}")
        if ref.get("snippet"):
            lines.append("```")
            lines.append(ref["snippet"])
            lines.append("```")
        return lines

    if activities:
        for label, group in activities.items():
            parts.append(f"\n### Activity: {label}")
            for i, ref in group:
                parts.extend(_fmt_ref(i, ref))
        if ungrouped:
            parts.append("\n### Other changes")
            for i, ref in ungrouped:
                parts.extend(_fmt_ref(i, ref))
    else:
        for i, ref in ungrouped:
            parts.extend(_fmt_ref(i, ref))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parser: LLM output → structured blocks
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(r"\[\[(\d+)\]\]")
_BEAT_RE = re.compile(r"\{\{(DECIDE|BACKTRACK|INSIGHT|VERIFY)\}\}")
_SPLIT_RE = re.compile(r"(\[\[\d+\]\]|\{\{(?:DECIDE|BACKTRACK|INSIGHT|VERIFY)\}\})")


def _parse_blocks(
    raw: str, refs: list[StoryReference],
) -> list[StoryBlock]:
    """Split LLM output on ``[[N]]`` reference markers and ``{{BEAT}}``
    beat markers into narrative, reference, and beat blocks."""
    blocks: list[StoryBlock] = []
    referenced: set[int] = set()

    segments = _SPLIT_RE.split(raw)

    pending_beat: str | None = None

    for seg in segments:
        # Check if this segment is a beat marker
        beat_match = _BEAT_RE.fullmatch(seg)
        if beat_match:
            pending_beat = beat_match.group(1).lower()
            continue

        # Check if this segment is a reference marker
        ref_match = _MARKER_RE.fullmatch(seg)
        if ref_match:
            raw_idx = int(ref_match.group(1))
            idx = raw_idx - 1  # 1-based → 0-based
            if 0 <= idx < len(refs):
                blocks.append(cast("StoryBlock", {"type": "reference", **refs[idx]}))
                referenced.add(idx)
            else:
                log.warning(
                    "story_marker_out_of_range",
                    marker=raw_idx,
                    ref_count=len(refs),
                )
            continue

        # Plain text segment — narrative or beat prose
        text = seg.strip()
        if not text:
            continue

        if pending_beat:
            blocks.append({
                "type": "beat",
                "text": text,
                "beatKind": pending_beat,
            })
            pending_beat = None
        else:
            blocks.append({"type": "narrative", "text": text})

    # If a beat marker was dangling at the end with no text after it
    if pending_beat:
        blocks.append({
            "type": "beat",
            "text": "",
            "beatKind": pending_beat,
        })

    # Append any unreferenced changes at the end
    for i, ref in enumerate(refs):
        if i not in referenced:
            blocks.append(cast("StoryBlock", {"type": "reference", **ref}))

    return blocks


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class StoryService:
    """Generates and caches structured code-review stories for jobs."""

    _gen_locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        completer: "Completable",
        coderecon: "CodeReconService | None" = None,
    ) -> None:
        self._completer = completer
        self._coderecon = coderecon

    async def get_or_generate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        """Return cached story blocks, or generate and cache them."""
        from sqlalchemy import text

        # Check cache
        col = "story_text" if verbosity == "standard" else f"story_text_{verbosity}"
        row = await session.execute(
            text(f"SELECT {col} FROM jobs WHERE id = :jid"),  # noqa: S608
            {"jid": job_id},
        )
        cached = row.scalar_one_or_none()
        if cached:
            try:
                return cast("dict[str, Any]", json.loads(cached))
            except (json.JSONDecodeError, TypeError):
                log.debug("story_cache_decode_failed", job_id=job_id)  # stale plain-text → regenerate

        # Serialize generation per job to avoid duplicate LLM calls.
        lock = self._gen_locks.setdefault(f"{job_id}:{verbosity}", asyncio.Lock())
        async with lock:
            # Re-check cache — another coroutine may have populated it.
            row = await session.execute(
                text(f"SELECT {col} FROM jobs WHERE id = :jid"),  # noqa: S608
                {"jid": job_id},
            )
            cached = row.scalar_one_or_none()
            if cached:
                try:
                    return cast("dict[str, Any]", json.loads(cached))
                except (json.JSONDecodeError, TypeError):
                    log.debug("story_cache_parse_failed", job_id=job_id)
                    pass
            try:
                return await self._generate(session, job_id, verbosity=verbosity)
            finally:
                self._gen_locks.pop(f"{job_id}:{verbosity}", None)

    async def regenerate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        """Force regeneration, ignoring cache."""
        from sqlalchemy import text

        col = "story_text" if verbosity == "standard" else f"story_text_{verbosity}"
        await session.execute(
            text(f"UPDATE jobs SET {col} = NULL WHERE id = :jid"),  # noqa: S608
            {"jid": job_id},
        )
        await session.commit()
        return await self._generate(session, job_id, verbosity=verbosity)

    async def _fetch_structural_section(
        self, session: "AsyncSession", job_id: str,
    ) -> str | None:
        """Fetch structural diff from CodeRecon and format as prompt section."""
        if not self._coderecon or not self._coderecon.available:
            return None

        from sqlalchemy import text

        row = await session.execute(
            text("SELECT repo, worktree_path, base_ref FROM jobs WHERE id = :jid"),
            {"jid": job_id},
        )
        job_row = row.mappings().first()
        if not job_row or not job_row["repo"] or not job_row["worktree_path"]:
            return None

        try:
            # Look up repo name without triggering registration/indexing
            from pathlib import Path as _Path
            catalog = await self._coderecon.catalog()
            resolved = _Path(job_row["repo"]).resolve()
            repo_name = next(
                (e["name"] for e in catalog
                 if _Path(e.get("git_dir", "")).resolve() in (resolved / ".git", resolved)),
                None,
            )
            if not repo_name:
                return None
            diff_result = await self._coderecon.semantic_diff(
                repo_name,
                base=job_row["base_ref"] or "HEAD",
                worktree=job_row["worktree_path"],
            )
        except Exception:
            log.debug("story_structural_diff_failed", job_id=job_id, exc_info=True)
            return None

        changes = diff_result.structural_changes or []
        if not changes:
            return None

        lines = ["## STRUCTURAL ANALYSIS (semantic diff)"]
        for ch in changes:
            kind = ch.get("kind", "unknown")
            symbol = ch.get("symbol")
            file = ch.get("file", "")
            summary = ch.get("summary", "")
            ref_count = ch.get("ref_count", 0)
            ref_tiers = ch.get("ref_tiers", {})
            sig_changed = ch.get("signature_changed", False)

            # Determine category inline (mirrors endpoint logic)
            if kind == "removed":
                category = "BREAKING" if ref_count > 0 else "non-structural"
            elif kind == "modified":
                category = "BREAKING" if sig_changed else "body"
            elif kind == "added":
                category = "additive"
            else:
                category = "body" if kind == "moved" else "non-structural"

            entry = f"  [{category.upper()}] {file}"
            if symbol:
                entry += f" :: {symbol}"
            if ref_count > 0:
                entry += f" ({ref_count} callers"
                unknown = ref_tiers.get("UNKNOWN", 0)
                if unknown:
                    entry += f", {unknown} UNVERIFIED"
                entry += ")"
            if summary:
                entry += f" — {summary}"
            lines.append(entry)
        return "\n".join(lines)

    async def _generate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        from sqlalchemy import text

        refs = await _build_references(session, job_id)

        ctx = await _collect_context(session, job_id)
        if not ctx:
            return None

        # Need at least some trail data or context to generate a story
        beats = ctx.get("trail_beats", [])
        if not refs and not beats:
            return None  # no trail data at all

        # Guard against write-summary staleness — if there are write sub-nodes
        # still missing their write_summary, skip caching so the next
        # request can pick up the complete data.
        unsummarized = await session.execute(
            text(
                "SELECT COUNT(*) FROM trail_nodes "
                "WHERE job_id = :jid AND kind = 'write' "
                "AND write_summary IS NULL"
            ),
            {"jid": job_id},
        )
        pending_motivations = unsummarized.scalar() or 0

        # Guard against trail enrichment staleness — trail beats need
        # enrichment to be complete before the narrative is meaningful.
        unenriched = await session.execute(
            text(
                "SELECT COUNT(*) FROM trail_nodes "
                "WHERE job_id = :jid AND enrichment = 'pending'"
            ),
            {"jid": job_id},
        )
        pending_enrichment = unenriched.scalar() or 0

        user_prompt = _build_prompt(refs, ctx)

        # Structural analysis enrichment from CodeRecon
        structural_section = await self._fetch_structural_section(session, job_id)
        if structural_section:
            user_prompt += "\n\n" + structural_section

        system = _STORY_SYSTEM + _STORY_VERBOSITY_SUFFIX.get(verbosity, "")
        full_prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user_prompt}"

        try:
            result = await self._completer.complete(full_prompt)
            raw = result.strip() if isinstance(result, str) else str(result).strip()
        except (httpx.HTTPError, OSError, ValueError):
            log.warning("story_generation_llm_failed", job_id=job_id, exc_info=True)
            return None

        if not raw:
            return None

        blocks = _parse_blocks(raw, refs)
        has_decisions = any(b.get("kind") == "decide" for b in beats)
        has_backtracks = any(b.get("kind") == "backtrack" for b in beats)
        payload: dict[str, Any] = {
            "blocks": blocks,
            "beat_count": len(beats),
            "has_decisions": has_decisions,
            "has_backtracks": has_backtracks,
        }

        # Only cache when all enrichment is ready — otherwise the next
        # request will regenerate with richer trail and motivation data.
        if pending_motivations == 0 and pending_enrichment == 0:
            col = "story_text" if verbosity == "standard" else f"story_text_{verbosity}"
            await session.execute(
                text(f"UPDATE jobs SET {col} = :story WHERE id = :jid"),  # noqa: S608
                {"jid": job_id, "story": json.dumps(payload)},
            )
            await session.commit()
        else:
            log.info(
                "story_skip_cache",
                job_id=job_id,
                pending_motivations=pending_motivations,
                pending_enrichment=pending_enrichment,
            )

        return payload
