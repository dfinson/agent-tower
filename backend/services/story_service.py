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
    "over coffee — candid, specific, occasionally wry. Every paragraph "
    "should teach the reader something they didn't know before reading it. "
    "Humor comes from noticing genuine absurdity and stating it as fact — "
    "never manufacture jokes, never be cute, never self-congratulate. "
    "If nothing is genuinely absurd, don't reach for wit.\n\n"
    #
    # Hook and structure — transformation arc
    "STRUCTURE: Open with a hook — the most surprising outcome, the hardest "
    "problem encountered, or what was at stake. Do NOT open with 'I was "
    "asked to...' or 'The task was...'. Pull the reader in with the most "
    "interesting thing that happened, then rewind to set context. Frame the "
    "session as a transformation: what was the state of the codebase before, "
    "what complications arose during the work, and what state it reached "
    "after. Walk through the body chronologically, but the opening should "
    "front-load why the reader should care. Close with the outcome — what "
    "changed in the system, what risks remain, what the next reader should "
    "watch for.\n\n"
    #
    # Curiosity gaps — forward references that create tension
    "FORWARD REFERENCES: Plant questions in the reader's mind that get "
    "answered later. When you know the narrative will reveal something "
    "surprising — a wrong assumption, an unexpected dependency, a hidden "
    "bug — hint at it early and pay it off later. 'The migration looked "
    "straightforward — three tables, a few foreign keys. The foreign keys "
    "turned out to be the problem.' This creates cognitive tension that "
    "holds attention across paragraphs. Use sparingly — one or two per "
    "story, only when the trail data contains a genuine surprise.\n\n"
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
    "BEATS: The AGENT JOURNEY beats are the skeleton of your story — decisions, "
    "backtracks, insights, and verifications. Each beat type demands a "
    "specific narrative shape:\n"
    "  {{DECIDE}} — Frame the fork: what alternatives existed, what "
    "tradeoffs mattered, and why this path won. The reader should understand "
    "the choice even if they would have chosen differently.\n"
    "  {{BACKTRACK}} — This is the complication in your story arc. Set up the "
    "original reasoning so it sounds right, then show the moment it broke. "
    "What was the signal — an error, a test failure, a realization? Then "
    "show the pivot. Backtracks are the most compelling part of any "
    "technical narrative because they reveal how the problem actually works.\n"
    "  {{INSIGHT}} — The discovery moment. What was the state of "
    "understanding before, what changed it, and what does the reader now "
    "know that they didn't.\n"
    "  {{VERIFY}} — Ground the reader: what was tested, what passed, what "
    "the result proves about the changes above.\n"
    "A beat marker goes on its own line, followed by one or more prose "
    "paragraphs about that turning point. Not every beat needs a marker — "
    "minor decisions can be woven into regular prose. Use markers for "
    "moments the reader should notice.\n\n"
    #
    # Pacing
    "PACING: Alternate between dense technical detail and brief orienting "
    "observations. After explaining a multi-line change, step back — why "
    "does it matter, what does the system look like now, what comes next. "
    "After a backtrack or complication, give the reader a beat of relief "
    "before diving into the fix. Monotone density loses readers; monotone "
    "simplicity bores them.\n\n"
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
    '("This was complex"), no hedging ("I thought maybe"). Name specific '
    "consequences — 'without this check, expired tokens pass through to "
    "the database layer' grounds the reader in stakes better than 'this "
    "was an important fix'. When something is genuinely absurd — a function "
    "named `handleEverything()`, a config file longer than the service it "
    "configures — state it as fact and move on. Never mean, never sarcastic "
    "about other people's code.\n\n"
    #
    # Connective prose
    "TRANSITIONS: Every transition should pull the reader forward. 'Having "
    "fixed the auth handler, the real problem became visible' beats 'Next, "
    "I looked at the auth handler.' Connect each section to the next by "
    "showing what the previous change revealed, required, or unblocked. "
    "The reader should never wonder 'why are we here now?'\n\n"
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
    "natural chapter transitions. When shifting between activities, bridge "
    "the gap — show the connection or contrast between the two concerns "
    "so the reader follows the thread.\n\n"
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


# ---------------------------------------------------------------------------
# Verbosity → column mapping (whitelist — prevents SQL injection)
# ---------------------------------------------------------------------------

_VERBOSITY_COLUMNS: dict[str, str] = {
    "summary": "story_text_summary",
    "standard": "story_text",
    "detailed": "story_text_detailed",
}


def _col_for_verbosity(verbosity: str) -> str:
    """Return the DB column name for a verbosity level, or raise."""
    col = _VERBOSITY_COLUMNS.get(verbosity)
    if col is None:
        raise ValueError(f"Invalid verbosity: {verbosity!r}")
    return col


# ---------------------------------------------------------------------------
# Token estimation and model-context lookup
# ---------------------------------------------------------------------------

_PRICING_PATH = (
    __import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "model_pricing.json"
)


def _get_model_max_input_tokens(model: str) -> int | None:
    """Look up a model's max input tokens from the pricing dataset.

    Returns ``None`` when the model isn't found — callers should fall back
    to single-pass generation in that case (never truncate).
    """
    try:
        data = json.loads(_PRICING_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    # Exact match first, then normalized
    entry = data.get(model)
    if not entry:
        normalized = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", model.lower())).strip("-")
        entry = data.get(normalized)
    if entry and isinstance(entry.get("max_input_tokens"), (int, float)):
        return int(entry["max_input_tokens"])
    return None


def _estimate_tokens(text: str) -> int:
    """Rough token count estimate.

    OpenAI and Anthropic tokenisers average ~4 characters per token for
    mixed English/code text.  This is a *standard approximation*, not a
    tuning knob — the real safety margin comes from the 75% headroom
    factor applied by the caller.
    """
    _CHARS_PER_TOKEN = 4  # industry-standard estimate (OpenAI tokenizer docs)
    return len(text) // _CHARS_PER_TOKEN


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
        .where(TrailNodeRow.enrichment == "complete")
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
            try:
                parsed = json.loads(node.files)
                files_list = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                files_list = []
            file_val = str(files_list[0]) if files_list else ""

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

        if key in seen and not ref.get("isRetry"):
            log.warning("story_duplicate_ref_key", key=key, span_id=node.id)
            key = f"{key}|{node.id}"  # disambiguate — both refs appear
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
                parsed = json.loads(node.files)
                files_list = [str(f) for f in parsed] if isinstance(parsed, list) else []
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

async def _collect_context(
    session: "AsyncSession", job_id: str,
    *, job_row: dict[str, Any] | None = None,
) -> StoryContext:
    """Gather lightweight context metadata (no file_write spans — those are
    handled by ``_build_references``)."""
    from sqlalchemy import text

    ctx: StoryContext = {}

    # Job metadata — reuse caller-provided row when available (#8)
    if job_row is None:
        result = await session.execute(
            text("SELECT id, title, description, prompt, state, model FROM jobs WHERE id = :jid"),
            {"jid": job_id},
        )
        mapping = result.mappings().first()
        if not mapping:
            return {}
        job_row = dict(mapping)
    ctx["job"] = cast("_JobContext", job_row)

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

    # Entries — render in chronological order with activity headers at transitions (#13)
    has_files = any(ref.get("file") for ref in refs)
    section_label = "CHANGES" if has_files else "SESSION EVENTS"
    parts.append(f"\n## {section_label} ({len(refs)} total, chronological)")

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

    current_activity: str | None = None
    for i, ref in enumerate(refs, 1):
        label = ref.get("activityLabel", "") or ""
        if label != (current_activity or ""):
            if label:
                parts.append(f"\n### Activity: {label}")
            elif current_activity:
                parts.append("\n### Other changes")
            current_activity = label or None
        parts.extend(_fmt_ref(i, ref))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parser: LLM output → structured blocks
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(r"\[\[(\d+)\]\]")
_BEAT_RE = re.compile(r"\{\{(DECIDE|BACKTRACK|INSIGHT|VERIFY)\}\}", re.IGNORECASE)
_SPLIT_RE = re.compile(
    r"(\[\[\d+\]\]|\{\{(?:DECIDE|BACKTRACK|INSIGHT|VERIFY)\}\})", re.IGNORECASE,
)


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
            # Flush any pending beat before the reference (#6)
            if pending_beat:
                blocks.append({
                    "type": "beat",
                    "text": "",
                    "beatKind": pending_beat,
                })
                pending_beat = None
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

    # Discard any dangling beat marker with no trailing prose (#10)
    if pending_beat:
        log.debug("story_dangling_beat_marker", beat_kind=pending_beat)

    # Append any unreferenced changes at the end
    for i, ref in enumerate(refs):
        if i not in referenced:
            blocks.append(cast("StoryBlock", {"type": "reference", **ref}))

    # Filter out any empty beat blocks that slipped through (#10)
    blocks = [
        b for b in blocks
        if not (b.get("type") == "beat" and not b.get("text"))
    ]

    return blocks


# ---------------------------------------------------------------------------
# Multi-pass generation — splits large ref sets across LLM calls (#7)
# ---------------------------------------------------------------------------

_CONTINUATION_SYSTEM = (
    "\n\nCONTINUATION: This is part {pass_num} of {total_passes} of a larger "
    "narrative. The previous part ended with changes up to [[{prev_last}]]. "
    "You are now covering changes [[{first}]] through [[{last}]]. "
    "Continue the narrative naturally from where the previous section left "
    "off — no need to restate context or re-introduce the session. "
    "Open with a brief transitional sentence, then proceed with the "
    "remaining changes. Maintain the same voice and style."
)


def _split_refs_into_chunks(
    refs: list[StoryReference],
    ctx: StoryContext,
    system: str,
    *,
    max_input_tokens: int,
) -> list[list[tuple[int, StoryReference]]]:
    """Split refs into chunks that each fit within the model's context window.

    Each chunk is a list of (global_1based_index, ref) pairs.  The context
    (job metadata, beats, approvals) is repeated in every chunk — only the
    CHANGES section varies.

    We use 75% of max_input_tokens as the budget to leave headroom for the
    model's internal overhead, output generation, and estimation error.
    """
    # Build the fixed portion of the prompt (everything except refs)
    fixed_prompt = _build_prompt([], ctx)
    # Add the continuation suffix size (worst-case)
    continuation_overhead = len(_CONTINUATION_SYSTEM) + 100  # format placeholders
    fixed_tokens = _estimate_tokens(system + fixed_prompt) + _estimate_tokens(
        " " * continuation_overhead
    )

    # 75% of the model's max input tokens, minus the fixed overhead
    budget = int(max_input_tokens * 0.75) - fixed_tokens
    if budget <= 0:
        # Context section alone is enormous — can't split usefully,
        # just return all refs in one chunk and let the LLM do its best.
        return [[(i + 1, r) for i, r in enumerate(refs)]]

    # Greedily pack refs into chunks
    chunks: list[list[tuple[int, StoryReference]]] = []
    current_chunk: list[tuple[int, StoryReference]] = []
    current_tokens = 0

    for i, ref in enumerate(refs):
        # Estimate this ref's contribution using _fmt_ref-like formatting
        ref_text = _estimate_ref_text(i + 1, ref)
        ref_tokens = _estimate_tokens(ref_text)

        if current_chunk and (current_tokens + ref_tokens) > budget:
            # Start a new chunk
            chunks.append(current_chunk)
            current_chunk = [(i + 1, ref)]
            current_tokens = ref_tokens
        else:
            current_chunk.append((i + 1, ref))
            current_tokens += ref_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _estimate_ref_text(idx: int, ref: StoryReference) -> str:
    """Approximate the prompt text a single ref contributes."""
    parts: list[str] = []
    anchor = ref.get("file") or ref.get("stepTitle") or ref.get("why") or f"event {idx}"
    parts.append(f"{idx}. **{anchor}**")
    if ref.get("why"):
        parts.append(f" — {ref['why']}")
    if ref.get("stepIntent"):
        parts.append(f"   Intent: {ref['stepIntent']}")
    if ref.get("editDetails"):
        for ed in ref["editDetails"]:
            if ed.get("why"):
                parts.append(f"   • {ed.get('title', 'edit')}: {ed['why']}")
    if ref.get("snippet"):
        parts.append("```")
        parts.append(ref["snippet"])
        parts.append("```")
    return "\n".join(parts)


def _build_prompt_for_chunk(
    chunk: list[tuple[int, StoryReference]],
    ctx: StoryContext,
    *,
    total_refs: int,
) -> str:
    """Build a prompt for a subset of refs, keeping their global indices.

    The LLM sees ``[[N]]`` with the *original* numbering so parsed blocks
    map back to the global refs list without re-indexing.
    """
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

    # Trail beats — same for every chunk
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

    approvals = ctx.get("approvals", [])
    if approvals:
        parts.append("\n## DECISION POINTS")
        for a in approvals:
            line = f"  - {a.get('description', '')} → {a.get('resolution', 'pending')}"
            if a.get("proposed_action"):
                line += f"\n    Proposed: {a['proposed_action']}"
            parts.append(line)

    # Subset of changes — use global indices
    first_idx = chunk[0][0]
    last_idx = chunk[-1][0]
    has_files = any(ref.get("file") for _, ref in chunk)
    section_label = "CHANGES" if has_files else "SESSION EVENTS"
    parts.append(
        f"\n## {section_label} ({len(chunk)} of {total_refs}, "
        f"items {first_idx}-{last_idx}, chronological)"
    )

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

    current_activity: str | None = None
    for global_idx, ref in chunk:
        label = ref.get("activityLabel", "") or ""
        if label != (current_activity or ""):
            if label:
                parts.append(f"\n### Activity: {label}")
            elif current_activity:
                parts.append("\n### Other changes")
            current_activity = label or None
        parts.extend(_fmt_ref(global_idx, ref))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class StoryService:
    """Generates and caches structured code-review stories for jobs."""

    def __init__(
        self,
        completer: "Completable",
        coderecon: "CodeReconService | None" = None,
        session_factory: Any | None = None,
    ) -> None:
        self._completer = completer
        self._coderecon = coderecon
        self._session_factory = session_factory
        self._gen_locks: dict[str, asyncio.Lock] = {}

    async def get_or_generate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        """Return cached story blocks, or generate and cache them."""
        from sqlalchemy import text

        col = _col_for_verbosity(verbosity)

        # Check cache
        row = await session.execute(
            text(f"SELECT {col} FROM jobs WHERE id = :jid"),  # noqa: S608
            {"jid": job_id},
        )
        cached = row.scalar_one_or_none()
        if cached:
            try:
                result = cast("dict[str, Any]", json.loads(cached))
                result["_from_cache"] = True
                return result
            except (json.JSONDecodeError, TypeError):
                log.debug("story_cache_decode_failed", job_id=job_id)  # stale plain-text → regenerate

        # Serialize generation per job to avoid duplicate LLM calls.
        lock_key = f"{job_id}:{verbosity}"
        lock = self._gen_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            # Re-check cache — another coroutine may have populated it.
            row = await session.execute(
                text(f"SELECT {col} FROM jobs WHERE id = :jid"),  # noqa: S608
                {"jid": job_id},
            )
            cached = row.scalar_one_or_none()
            if cached:
                try:
                    result = cast("dict[str, Any]", json.loads(cached))
                    result["_from_cache"] = True
                    return result
                except (json.JSONDecodeError, TypeError):
                    log.debug("story_cache_parse_failed", job_id=job_id)
                    pass
            try:
                return await self._generate(session, job_id, verbosity=verbosity)
            finally:
                self._gen_locks.pop(lock_key, None)

    async def regenerate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        """Force regeneration, ignoring cache."""
        from sqlalchemy import text

        col = _col_for_verbosity(verbosity)

        # Acquire the same lock as get_or_generate to prevent races (#3)
        lock_key = f"{job_id}:{verbosity}"
        lock = self._gen_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            await session.execute(
                text(f"UPDATE jobs SET {col} = NULL WHERE id = :jid"),  # noqa: S608
                {"jid": job_id},
            )
            # Don't commit the NULL separately — _generate will commit
            # with the new value, or we commit below on failure (#14)
            try:
                return await self._generate(session, job_id, verbosity=verbosity)
            except Exception:
                await session.commit()  # persist the NULL on failure
                raise
            finally:
                self._gen_locks.pop(lock_key, None)

    async def _fetch_structural_section(
        self, session: "AsyncSession", job_id: str,
        *, job_row: dict[str, Any] | None = None,
    ) -> str | None:
        """Fetch structural diff from CodeRecon and format as prompt section."""
        if not self._coderecon or not self._coderecon.available:
            return None

        from sqlalchemy import text

        if job_row is None:
            row = await session.execute(
                text("SELECT repo, worktree_path, base_ref FROM jobs WHERE id = :jid"),
                {"jid": job_id},
            )
            job_row = row.mappings().first()  # type: ignore[assignment]
        if not job_row or not job_row.get("repo") or not job_row.get("worktree_path"):
            return None

        try:
            repo_name = await self._coderecon.ensure_repo_indexed(job_row["repo"])
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
            kind = ch.change
            symbol = ch.qualified_name or ch.name
            file = ch.path
            preview = ch.change_preview or ""
            impact = ch.impact
            ref_count = impact.reference_count if impact and impact.reference_count else 0
            sig_changed = (
                ch.old_sig is not None and ch.new_sig is not None and ch.old_sig != ch.new_sig
            )

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
                unknown = impact.ref_tiers.unknown if impact and impact.ref_tiers else 0
                if unknown:
                    entry += f", {unknown} UNVERIFIED"
                entry += ")"
            if preview:
                entry += f" — {preview}"
            lines.append(entry)
        return "\n".join(lines)

    async def _generate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        from sqlalchemy import text

        # Validate verbosity early (#1)
        if verbosity not in _STORY_VERBOSITY_SUFFIX:
            raise ValueError(f"Unknown story verbosity {verbosity!r}")

        # Fetch job row once and share with sub-queries (#8)
        job_result = await session.execute(
            text(
                "SELECT id, title, description, prompt, state, model, "
                "repo, worktree_path, base_ref "
                "FROM jobs WHERE id = :jid"
            ),
            {"jid": job_id},
        )
        job_mapping = job_result.mappings().first()
        if not job_mapping:
            return None
        job_row = dict(job_mapping)

        refs = await _build_references(session, job_id)

        ctx = await _collect_context(session, job_id, job_row=job_row)
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

        # Structural analysis enrichment from CodeRecon
        structural_section = await self._fetch_structural_section(
            session, job_id, job_row=job_row,
        )

        system = _STORY_SYSTEM + _STORY_VERBOSITY_SUFFIX.get(verbosity, "")

        # Determine whether multi-pass is needed (#7)
        # Look up the model's context window from pricing data.
        model_name = getattr(self._completer, "model", None) or ""
        max_input_tokens = _get_model_max_input_tokens(model_name) if model_name else None

        blocks = await self._generate_passes(
            refs=refs,
            ctx=ctx,
            system=system,
            structural_section=structural_section,
            max_input_tokens=max_input_tokens,
            job_id=job_id,
        )

        if not blocks:
            return None

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
            col = _col_for_verbosity(verbosity)
            await session.execute(
                text(f"UPDATE jobs SET {col} = :story WHERE id = :jid"),  # noqa: S608
                {"jid": job_id, "story": json.dumps(payload)},
            )
            await session.commit()

            # Pre-generate other verbosity levels in the background so
            # switching verbosity in the UI is instant (no spinner).
            self._prefetch_other_verbosities(job_id, verbosity)
        else:
            log.info(
                "story_skip_cache",
                job_id=job_id,
                pending_motivations=pending_motivations,
                pending_enrichment=pending_enrichment,
            )

        return payload

    def _prefetch_other_verbosities(self, job_id: str, completed_verbosity: str) -> None:
        """Fire-and-forget generation of the other two verbosity levels."""
        if not self._session_factory:
            return
        all_levels = ["summary", "standard", "detailed"]
        remaining = [v for v in all_levels if v != completed_verbosity]

        for v in remaining:
            asyncio.ensure_future(self._prefetch_one(job_id, v))

    async def _prefetch_one(self, job_id: str, verbosity: str) -> None:
        """Background task: generate and cache one verbosity level if not already cached."""
        try:
            async with self._session_factory() as session:
                await self.get_or_generate(session, job_id, verbosity=verbosity)
        except Exception:
            log.debug("story_prefetch_failed", job_id=job_id, verbosity=verbosity, exc_info=True)

    async def _generate_passes(
        self,
        *,
        refs: list[StoryReference],
        ctx: StoryContext,
        system: str,
        structural_section: str | None,
        max_input_tokens: int | None,
        job_id: str,
    ) -> list[StoryBlock]:
        """Generate story blocks, splitting into multiple LLM passes if the
        prompt would exceed the model's context window.

        Never truncates any information — every ref is included in exactly
        one pass.  When the model's context window is unknown, falls back to
        single-pass (optimistic).
        """
        # Try single-pass first — check if it fits
        user_prompt = _build_prompt(refs, ctx)
        if structural_section:
            user_prompt += "\n\n" + structural_section

        full_prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user_prompt}"
        estimated_tokens = _estimate_tokens(full_prompt)

        # If we don't know the model's limit, or it fits within 75% of the
        # context window, use a single pass.
        needs_multipass = (
            max_input_tokens is not None
            and estimated_tokens > int(max_input_tokens * 0.75)
            and len(refs) > 1  # can't split a single ref
        )

        if not needs_multipass:
            return await self._single_pass(full_prompt, refs, job_id=job_id)

        assert max_input_tokens is not None  # narrowed above
        log.info(
            "story_multipass_triggered",
            job_id=job_id,
            estimated_tokens=estimated_tokens,
            max_input_tokens=max_input_tokens,
            ref_count=len(refs),
        )

        chunks = _split_refs_into_chunks(
            refs, ctx, system, max_input_tokens=max_input_tokens,
        )

        all_blocks: list[StoryBlock] = []
        for pass_num, chunk in enumerate(chunks, 1):
            chunk_prompt = _build_prompt_for_chunk(chunk, ctx, total_refs=len(refs))
            if structural_section and pass_num == 1:
                chunk_prompt += "\n\n" + structural_section

            chunk_system = system
            if pass_num > 1:
                prev_chunk = chunks[pass_num - 2]
                chunk_system += _CONTINUATION_SYSTEM.format(
                    pass_num=pass_num,
                    total_passes=len(chunks),
                    prev_last=prev_chunk[-1][0],
                    first=chunk[0][0],
                    last=chunk[-1][0],
                )

            pass_prompt = f"SYSTEM:\n{chunk_system}\n\nUSER:\n{chunk_prompt}"
            pass_blocks = await self._single_pass(pass_prompt, refs, job_id=job_id)
            all_blocks.extend(pass_blocks)

        return all_blocks

    async def _single_pass(
        self,
        full_prompt: str,
        refs: list[StoryReference],
        *,
        job_id: str,
    ) -> list[StoryBlock]:
        """Execute one LLM call and parse the result into blocks."""
        try:
            result = await self._completer.complete(full_prompt)
            raw = result.strip() if isinstance(result, str) else str(result).strip()
        except (httpx.HTTPError, OSError, ValueError):
            log.warning("story_generation_llm_failed", job_id=job_id, exc_info=True)
            return []

        if not raw:
            return []

        return _parse_blocks(raw, refs)
