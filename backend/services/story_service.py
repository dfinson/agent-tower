"""Story generation service — assembles a structured code-review narrative
from telemetry data: validated change references interleaved with LLM-
generated connective prose.

The key design principle: *references are never LLM-generated*.  They are
built directly from ``job_telemetry_spans`` rows (``tool_category='file_write'``),
ordered chronologically.  The LLM only generates the prose that connects them.

Stories are generated on demand and cached as JSON on the ``jobs.story_text``
column.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any, TypedDict

import httpx
import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
    spanId: str
    file: str
    why: str
    stepNumber: int | None
    stepTitle: str
    turnId: str
    editCount: int


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
    "You write technical narratives about coding sessions. You receive a "
    "numbered list of code changes with snippets, motivation summaries, and "
    "session context. Write a first-person narrative that a human reviewer "
    "can follow like a blog post — not a terse summary, not a commit log, "
    "but an actual story of what happened and why.\n\n"
    #
    # Narrative voice
    "VOICE: Write like a senior engineer explaining their work to a colleague "
    "over coffee. Set the scene: what was the task, what system does it touch, "
    "why does it matter, what was at stake. Before diving into code changes, "
    "the reader needs to understand the landscape — what existed before, what "
    "problem needed solving, and why the existing code wasn't sufficient. "
    "Then walk through the work chronologically: what you explored, what you "
    "discovered, what decisions you made and why, what surprised you, and "
    "what the code looks like now. Every paragraph should teach the reader "
    "something they didn't know before reading it.\n\n"
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
    # Structure
    "STRUCTURE: Open with a paragraph that sets context — what is this system, "
    "what was the task, why does it matter to the project. Then walk through "
    "changes chronologically. Close with the outcome and any remaining risks.\n\n"
    #
    # Length — these are REAL narratives, not summaries
    "LENGTH: Write enough to actually tell the story. Target 400-600 words "
    "for ≤5 changes, 600-1000 for 6+. If a change involves a design "
    "decision, explain the alternatives you considered and why you chose "
    "this path. If there was a surprise or discovery during the work, "
    "describe what you found and what it meant. Do NOT compress the "
    "narrative into terse bullet-point-like sentences. Each paragraph "
    "should flow into the next.\n\n"
    #
    # Inline code — backticks for symbols and expressions
    "INLINE CODE: Each change includes a code snippet showing what was added "
    "or removed. Weave these into your narrative — quote the key lines, name "
    "the specific functions, variables, and expressions using `backticks`. "
    "Show the reader the actual code that matters, not just abstract "
    "descriptions. The reader should encounter real code in your prose "
    "before they see the full diff card.\n\n"
    #
    # Objectivity
    "OBJECTIVITY: State what you did and why. No self-assessment of difficulty "
    '("This was complex"), no hedging ("I thought maybe"), no flair ("elegant '
    'refactor"). Let facts speak.\n\n'
    #
    # Connective prose — why, not what
    "TRANSITIONS: Between [[N]] markers, write motivation, context, and "
    "discoveries — why you moved to the next change, what you found when you "
    "looked at the existing code, what constraint or insight shaped the "
    "approach. If you don't know why, use 'then' rather than inventing a "
    "reason.\n\n"
    #
    # Contextual recall — help the reader track symbols
    "RECALL: Function and class names drop out of working memory after a "
    "few dense paragraphs. When you reference a symbol that was introduced "
    "earlier, add a brief contextual tag on later mentions — 'the approval "
    "entry point `create_request()`' rather than bare '`create_request()`', "
    "'the resolution method `resolve()`' rather than bare '`resolve()`. "
    "Do not re-explain what the reader already knows — just a 2-4 word "
    "reminder of the symbol's role. First mention: full introduction. "
    "Mentions within 1-2 paragraphs: bare name is fine. Later mentions "
    "after intervening content: brief role tag.\n\n"
    #
    # Trail beats — semantic turning points from the agent's decision trail
    "TRAIL BEATS: You may receive an AGENT JOURNEY section listing key "
    "moments — decisions, backtracks, insights, and verifications. These "
    "are narrative turning points. When the agent chose between approaches, "
    "tell the reader why. When the agent backtracked, explain what went "
    "wrong and what changed. Insights are discoveries that shaped the rest "
    "of the work. Weave these into the chronological flow — they are the "
    "skeleton of the story, not a separate section.\n\n"
    #
    # Retry arcs — problem-solving narratives
    "RETRY ARCS: When a change is marked [RETRY], the original attempt "
    "failed. Tell the reader what happened — what error occurred, what the "
    "agent tried first, and why the second attempt succeeded. These "
    "problem-solving arcs are the most engaging parts of a technical "
    "narrative. If an error kind is given, name it.\n\n"
    #
    # Activity groups — natural chapter transitions
    "ACTIVITIES: Changes may be grouped under activity labels (e.g., "
    "'Implement auth', 'Fix test suite'). Use these as natural chapter "
    "transitions — the reader should sense when the work shifts from one "
    "concern to another. Don't announce the label mechanically; let it "
    "shape the narrative flow.\n\n"
    #
    # Format constraints
    "FORMAT: Plain prose paragraphs only. No markdown headers, bullets, or "
    "code blocks — output renders inline. Backtick-wrapped `symbols` are "
    "allowed and encouraged. First person ('I started by…'). "
    "Contractions fine. No jokes, emoji, or exclamation marks. "
    "Every change MUST be referenced by its [[N]] marker at least once."
)


_STORY_VERBOSITY_SUFFIX = {
    "summary": (
        "\n\nVERBOSITY=summary: Write a 3-5 sentence executive summary that "
        "still names the key symbols and decisions. Reference each change by "
        "[[N]]. Target 100-150 words. Even in summary mode, set minimal "
        "context — what system was involved, what changed, what risk remains."
    ),
    "standard": "",
    "detailed": (
        "\n\nVERBOSITY=detailed: Write a thorough technical narrative — the "
        "kind of thing you'd post on an engineering blog. For each change, "
        "explain what the existing code looked like before, what problem that "
        "created, what the new code does (quote key lines from the snippets), "
        "what alternatives you considered, and what tradeoffs you made. "
        "Target 800-1500 words. The reader should understand not just what "
        "changed but the full technical context — the shape of the codebase "
        "before the change, the constraint that made the change necessary, "
        "and exactly what the new code looks like. This is a technical "
        "document for reviewers, not a summary for managers."
    ),
}


def _truncate(s: str | None, max_len: int) -> str:
    if not s:
        return ""
    return s[:max_len] + ("…" if len(s) > max_len else "")


def _extract_snippet(tool_args_json: str | None, tool_name: str | None) -> str:
    """Extract a compact code snippet from tool_args_json for the story prompt.

    Returns the key lines of the change — old→new for replacements, the first
    meaningful lines for creates/inserts — so the LLM can reference actual code.
    """
    if not tool_args_json:
        return ""
    try:
        args = json.loads(tool_args_json) if isinstance(tool_args_json, str) else tool_args_json
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(args, dict):
        return ""

    max_lines = 8  # keep snippets compact

    # Replace/edit — show old → new
    old_str = str(
        args.get("old_str", "")
        or args.get("oldString", "")
        or args.get("old_string", "")
        or ""
    )
    new_str = str(
        args.get("new_str", "")
        or args.get("newString", "")
        or args.get("new_string", "")
        or ""
    )
    if old_str or new_str:
        old_lines = old_str.strip().splitlines()[:max_lines]
        new_lines = new_str.strip().splitlines()[:max_lines]
        parts: list[str] = []
        for line in old_lines:
            parts.append(f"- {line}")
        for line in new_lines:
            parts.append(f"+ {line}")
        return "\n".join(parts)

    # Create — show first meaningful lines
    content = str(args.get("file_text", "") or args.get("content", ""))
    if content:
        lines = [l for l in content.strip().splitlines() if l.strip()][:max_lines]
        return "\n".join(f"+ {l}" for l in lines)

    # Insert
    new_text = str(args.get("new_text", "") or args.get("newText", "") or "")
    if new_text:
        lines = new_text.strip().splitlines()[:max_lines]
        return "\n".join(f"+ {l}" for l in lines)

    return ""


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------

async def _build_references(
    session: "AsyncSession", job_id: str,
) -> list[StoryReference]:
    """Build validated reference dicts from file_write spans, chronologically."""
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT s.id AS span_id,
                   s.tool_target AS file,
                   s.motivation_summary AS why,
                   s.edit_motivations,
                   s.tool_args_json,
                   s.name AS tool_name,
                   s.turn_id,
                   s.started_at,
                   s.is_retry,
                   s.error_kind,
                   s.execution_phase,
                   st.step_number,
                   st.title AS step_title,
                   st.intent AS step_intent
            FROM job_telemetry_spans s
            LEFT JOIN steps st
              ON st.job_id = s.job_id AND st.turn_id = s.turn_id
            WHERE s.job_id = :jid
              AND s.tool_category = 'file_write'
            ORDER BY s.started_at ASC
        """),
        {"jid": job_id},
    )

    # Deduplicate by file+step — keep latest per group.
    # When file or step_number is NULL, fall back to span_id so that
    # unrelated NULL-keyed spans are never falsely merged.
    seen: dict[str, StoryReference] = {}
    for r in rows.mappings():
        file_val = r["file"] or ""
        step_val = r["step_number"]
        if not file_val or step_val is None:
            key = f"__span_{r['span_id']}"
        else:
            key = f"{file_val}|{step_val}"
        ref: StoryReference = {
            "spanId": r["span_id"],
            "file": r["file"] or "",
            "why": r["why"] or "",
            "stepNumber": r["step_number"],
            "stepTitle": _truncate(r["step_title"], 60),
            "turnId": r["turn_id"] or "",
        }
        # Extract code snippet from tool args
        snippet = _extract_snippet(r["tool_args_json"], r["tool_name"])
        if snippet:
            ref["snippet"] = snippet
        # Retry and error context
        if r["is_retry"]:
            ref["isRetry"] = True
        if r["error_kind"]:
            ref["errorKind"] = r["error_kind"]
        if r["execution_phase"]:
            ref["phase"] = r["execution_phase"]
        if r["step_intent"]:
            ref["stepIntent"] = r["step_intent"]
        # Merge per-edit details if available
        raw_edits = r["edit_motivations"]
        if raw_edits:
            try:
                edits = json.loads(raw_edits) if isinstance(raw_edits, str) else raw_edits
                if isinstance(edits, list) and edits:
                    ref["editCount"] = len(edits)
                    ref["editDetails"] = [
                        {"title": e.get("title", ""), "why": e.get("why", "")}
                        for e in edits
                        if e.get("why")
                    ]
            except (json.JSONDecodeError, TypeError):
                log.debug("edit_motivations_parse_failed", raw_edits=raw_edits if isinstance(raw_edits, str) else type(raw_edits).__name__)
                pass
        seen[key] = ref

    # Attach activity labels from trail nodes
    act_rows = await session.execute(
        text("""
            SELECT DISTINCT turn_id, activity_label
            FROM trail_nodes
            WHERE job_id = :jid AND activity_label IS NOT NULL
        """),
        {"jid": job_id},
    )
    activity_map = {r["turn_id"]: r["activity_label"] for r in act_rows.mappings()}
    result = list(seen.values())
    for ref in result:
        label = activity_map.get(ref.get("turnId", ""))
        if label:
            ref["activityLabel"] = label

    return result


# ---------------------------------------------------------------------------
# Trail beats extraction (semantic turning points)
# ---------------------------------------------------------------------------

async def _build_trail_beats(
    session: "AsyncSession", job_id: str,
) -> list[TrailBeat]:
    """Fetch enriched semantic trail nodes — decisions, backtracks, insights."""
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT kind, intent, rationale, outcome, supersedes, files,
                   seq, activity_label
            FROM trail_nodes
            WHERE job_id = :jid
              AND enrichment = 'complete'
              AND kind IN ('decide', 'backtrack', 'insight', 'verify', 'plan')
            ORDER BY seq ASC
        """),
        {"jid": job_id},
    )
    beats: list[TrailBeat] = []
    for r in rows.mappings():
        files_raw = r["files"]
        if isinstance(files_raw, str):
            try:
                files_list = json.loads(files_raw)
            except (json.JSONDecodeError, TypeError):
                files_list = []
        else:
            files_list = files_raw or []
        beat: TrailBeat = {
            "kind": r["kind"],
            "seq": r["seq"],
        }
        if r["intent"]:
            beat["intent"] = r["intent"]
        if r["rationale"]:
            beat["rationale"] = r["rationale"]
        if r["outcome"]:
            beat["outcome"] = r["outcome"]
        if r["supersedes"]:
            beat["supersedes"] = r["supersedes"]
        if files_list:
            beat["files"] = files_list
        if r["activity_label"]:
            beat["activity_label"] = r["activity_label"]
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
    ctx["job"] = dict(job)

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
        ctx["telemetry"] = dict(summary)

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
        ctx["approvals"] = approvals

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

    # Changes — grouped by activity when available
    parts.append(f"\n## CHANGES ({len(refs)} total, chronological)")

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
        line = f"{idx}. **{ref['file']}**"
        if ref.get("stepTitle"):
            line += f" (step {ref.get('stepNumber', '?')}: {ref['stepTitle']})"
        if ref.get("isRetry"):
            line += " [RETRY]"
        if ref.get("errorKind"):
            line += f" [error: {ref['errorKind']}]"
        if ref.get("why"):
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


def _parse_blocks(
    raw: str, refs: list[StoryReference],
) -> list[StoryBlock]:
    """Split LLM output on ``[[N]]`` markers into narrative + reference blocks."""
    blocks: list[StoryBlock] = []
    last_end = 0
    referenced: set[int] = set()

    for m in _MARKER_RE.finditer(raw):
        raw_idx = int(m.group(1))
        idx = raw_idx - 1  # 1-based → 0-based
        # Narrative text before this marker
        text_before = raw[last_end : m.start()].strip()
        if text_before:
            blocks.append({"type": "narrative", "text": text_before})
        # Reference block (only if valid index)
        if 0 <= idx < len(refs):
            blocks.append({"type": "reference", **refs[idx]})
            referenced.add(idx)
        else:
            log.warning(
                "story_marker_out_of_range",
                marker=raw_idx,
                ref_count=len(refs),
            )
        last_end = m.end()

    # Trailing narrative
    trailing = raw[last_end:].strip()
    if trailing:
        blocks.append({"type": "narrative", "text": trailing})

    # Append any unreferenced changes at the end
    for i, ref in enumerate(refs):
        if i not in referenced:
            blocks.append({"type": "reference", **ref})

    return blocks


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class StoryService:
    """Generates and caches structured code-review stories for jobs."""

    _gen_locks: dict[str, asyncio.Lock] = {}

    def __init__(self, completer: "Completable") -> None:
        self._completer = completer

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
                return json.loads(cached)
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
                    return json.loads(cached)
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

    async def _generate(
        self, session: "AsyncSession", job_id: str, *, verbosity: str = "standard",
    ) -> dict[str, Any] | None:
        from sqlalchemy import text

        refs = await _build_references(session, job_id)
        if len(refs) < 2:
            return None  # not enough changes for a meaningful story

        # Guard against motivation staleness — if there are file_write spans
        # still missing their motivation summary, skip caching so the next
        # request can pick up the complete data.
        unsummarized = await session.execute(
            text(
                "SELECT COUNT(*) FROM job_telemetry_spans "
                "WHERE job_id = :jid AND tool_category = 'file_write' "
                "AND motivation_summary IS NULL"
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

        ctx = await _collect_context(session, job_id)
        if not ctx:
            return None

        user_prompt = _build_prompt(refs, ctx)
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
        payload = {"blocks": blocks}

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
