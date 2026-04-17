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

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.naming_service import Completable

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_STORY_SYSTEM = (
    "You narrate coding sessions. You will receive a numbered list of code "
    "changes and contextual information about the session. Write a first-person "
    "walkthrough (\"I started by…\") that references each change using [[N]] "
    "markers (e.g. [[1]], [[2]]). Every change MUST be referenced at least once. "
    "A [[N]] marker appears inline right where you describe that change — it will "
    "be rendered as a clickable card. Between markers, write concise connective "
    "prose: motivation, decisions, setbacks, or transitions. Use markdown. "
    "Target 100-400 words, scaling with complexity. Do NOT repeat file paths or "
    "details already in the change list — the marker card shows those."
)


def _truncate(s: str | None, max_len: int) -> str:
    if not s:
        return ""
    return s[:max_len] + ("…" if len(s) > max_len else "")


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------

async def _build_references(
    session: "AsyncSession", job_id: str,
) -> list[dict[str, Any]]:
    """Build validated reference dicts from file_write spans, chronologically."""
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT s.id AS span_id,
                   s.tool_target AS file,
                   s.motivation_summary AS why,
                   s.edit_motivations,
                   s.turn_id,
                   s.started_at,
                   st.step_number,
                   st.title AS step_title
            FROM job_telemetry_spans s
            LEFT JOIN steps st
              ON st.job_id = s.job_id AND st.turn_id = s.turn_id
            WHERE s.job_id = :jid
              AND s.tool_category = 'file_write'
            ORDER BY s.started_at ASC
        """),
        {"jid": job_id},
    )

    # Deduplicate by file+step — keep latest per group
    seen: dict[str, dict[str, Any]] = {}
    for r in rows.mappings():
        key = f"{r['file']}|{r['step_number']}"
        ref: dict[str, Any] = {
            "spanId": r["span_id"],
            "file": r["file"] or "",
            "why": _truncate(r["why"], 200),
            "stepNumber": r["step_number"],
            "stepTitle": _truncate(r["step_title"], 60),
            "turnId": r["turn_id"] or "",
        }
        # Merge per-edit details if available
        raw_edits = r["edit_motivations"]
        if raw_edits:
            try:
                edits = json.loads(raw_edits) if isinstance(raw_edits, str) else raw_edits
                if isinstance(edits, list) and edits:
                    ref["editCount"] = len(edits)
            except (json.JSONDecodeError, TypeError):
                pass
        seen[key] = ref

    return list(seen.values())


# ---------------------------------------------------------------------------
# Context collection (non-reference metadata for the prompt)
# ---------------------------------------------------------------------------

async def _collect_context(session: "AsyncSession", job_id: str) -> dict[str, Any]:
    """Gather lightweight context metadata (no file_write spans — those are
    handled by ``_build_references``)."""
    from sqlalchemy import text

    ctx: dict[str, Any] = {}

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
            SELECT description, resolution, requires_explicit_approval
            FROM approvals WHERE job_id = :jid ORDER BY requested_at ASC
        """),
        {"jid": job_id},
    )
    approvals = [dict(r) for r in rows.mappings()]
    if approvals:
        ctx["approvals"] = approvals

    return ctx


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    refs: list[dict[str, Any]], ctx: dict[str, Any],
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

    approvals = ctx.get("approvals", [])
    if approvals:
        parts.append("\n## DECISION POINTS")
        for a in approvals:
            parts.append(f"  - {a.get('description', '')} → {a.get('resolution', 'pending')}")

    parts.append(f"\n## CHANGES ({len(refs)} total, chronological)")
    for i, ref in enumerate(refs, 1):
        line = f"{i}. **{ref['file']}**"
        if ref.get("stepTitle"):
            line += f" (step {ref.get('stepNumber', '?')}: {ref['stepTitle']})"
        if ref.get("why"):
            line += f" — {ref['why']}"
        if ref.get("editCount") and ref["editCount"] > 1:
            line += f" [{ref['editCount']} edits]"
        parts.append(line)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parser: LLM output → structured blocks
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(r"\[\[(\d+)\]\]")


def _parse_blocks(
    raw: str, refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Split LLM output on ``[[N]]`` markers into narrative + reference blocks."""
    blocks: list[dict[str, Any]] = []
    last_end = 0
    referenced: set[int] = set()

    for m in _MARKER_RE.finditer(raw):
        idx = int(m.group(1)) - 1  # 1-based → 0-based
        # Narrative text before this marker
        text_before = raw[last_end : m.start()].strip()
        if text_before:
            blocks.append({"type": "narrative", "text": text_before})
        # Reference block (only if valid index)
        if 0 <= idx < len(refs):
            blocks.append({"type": "reference", **refs[idx]})
            referenced.add(idx)
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

    def __init__(self, completer: "Completable") -> None:
        self._completer = completer

    async def get_or_generate(
        self, session: "AsyncSession", job_id: str,
    ) -> dict[str, Any] | None:
        """Return cached story blocks, or generate and cache them."""
        from sqlalchemy import text

        # Check cache
        row = await session.execute(
            text("SELECT story_text FROM jobs WHERE id = :jid"),
            {"jid": job_id},
        )
        cached = row.scalar_one_or_none()
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                pass  # stale plain-text cache → regenerate

        return await self._generate(session, job_id)

    async def regenerate(
        self, session: "AsyncSession", job_id: str,
    ) -> dict[str, Any] | None:
        """Force regeneration, ignoring cache."""
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET story_text = NULL WHERE id = :jid"),
            {"jid": job_id},
        )
        await session.commit()
        return await self._generate(session, job_id)

    async def _generate(
        self, session: "AsyncSession", job_id: str,
    ) -> dict[str, Any] | None:
        from sqlalchemy import text

        refs = await _build_references(session, job_id)
        if len(refs) < 2:
            return None  # not enough changes for a meaningful story

        ctx = await _collect_context(session, job_id)
        if not ctx:
            return None

        user_prompt = _build_prompt(refs, ctx)
        full_prompt = f"SYSTEM:\n{_STORY_SYSTEM}\n\nUSER:\n{user_prompt}"

        try:
            result = await self._completer.complete(full_prompt)
            raw = result.strip() if isinstance(result, str) else str(result).strip()
        except Exception:
            log.debug("story_generation_failed", job_id=job_id, exc_info=True)
            return None

        if not raw:
            return None

        blocks = _parse_blocks(raw, refs)
        payload = {"blocks": blocks}

        # Cache as JSON
        await session.execute(
            text("UPDATE jobs SET story_text = :story WHERE id = :jid"),
            {"jid": job_id, "story": json.dumps(payload)},
        )
        await session.commit()

        return payload
