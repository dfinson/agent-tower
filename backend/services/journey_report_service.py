"""Cognitive journey report service — reconstruction of an agent's
decision path from telemetry spans.

The journey report has two layers:

1. **Deterministic foundation**: phases, pivots, dead ends, and fragile
   areas assembled directly from telemetry data.  The factual backbone —
   never hallucinated.

2. **LLM synthesis layer**: the deterministic data is fed to a cheap LLM
   to produce a causal narrative — connecting the dots between phases,
   explaining *why* a dead end led to a pivot, and prioritizing what
   matters most.  Used for both handoff prompts and artifact export.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from backend.models.api_schemas import ArtifactType, ExecutionPhase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.naming_service import Completable

log = structlog.get_logger()

# Retry count thresholds for confidence scoring
_HIGH_CONFIDENCE_MAX_RETRIES = 0
_MEDIUM_CONFIDENCE_MAX_RETRIES = 2

# Artifacts base directory (same as artifact_service)
_ARTIFACTS_BASE = Path.home() / ".codeplane" / "artifacts"


async def build_journey_phases(
    session: AsyncSession,
    job_id: str,
) -> list[dict[str, Any]]:
    """Build journey phases from telemetry spans, grouped by step (turn_id).

    Each phase represents a logical unit of work the agent performed,
    enriched with retry/failure data and confidence scoring.
    """
    from sqlalchemy import text

    # Fetch all spans (not just file_write) — we need reads for
    # reconnaissance and tool failures for dead-end detection.
    rows = await session.execute(
        text("""
            SELECT s.id AS span_id,
                   s.tool_category,
                   s.tool_target,
                   s.motivation_summary,
                   s.edit_motivations,
                   s.turn_id,
                   s.started_at,
                   s.duration_ms,
                   s.is_retry,
                   s.retries_span_id,
                   s.error_kind,
                   s.name AS tool_name,
                   st.step_number,
                   st.title AS step_title
            FROM job_telemetry_spans s
            LEFT JOIN steps st
              ON st.job_id = s.job_id AND st.turn_id = s.turn_id
            WHERE s.job_id = :jid
            ORDER BY s.started_at ASC
        """),
        {"jid": job_id},
    )

    # Group spans by step (turn_id). Spans without a turn_id are
    # grouped into a synthetic "ungrouped" bucket.
    steps: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for r in rows.mappings():
        steps[r["turn_id"]].append(dict(r))

    phases: list[dict[str, Any]] = []
    for turn_id, spans in steps.items():
        if not spans:
            continue

        files_written: list[str] = []
        files_read: list[str] = []
        retry_count = 0
        failure_count = 0
        total_duration = 0.0
        motivation = None
        step_number = None
        step_title = None

        seen_write_files: set[str] = set()
        seen_read_files: set[str] = set()

        for span in spans:
            dur = _safe_float(span.get("duration_ms"))
            total_duration += dur

            cat = span.get("tool_category") or ""
            target = span.get("tool_target") or ""

            if cat == "file_write" and target and target not in seen_write_files:
                files_written.append(target)
                seen_write_files.add(target)
            elif cat == "file_read" and target and target not in seen_read_files:
                files_read.append(target)
                seen_read_files.add(target)

            if span.get("is_retry"):
                retry_count += 1
            if span.get("error_kind"):
                failure_count += 1

            # Use the first available motivation
            if not motivation and span.get("motivation_summary"):
                motivation = span["motivation_summary"]

            if step_number is None and span.get("step_number") is not None:
                step_number = span["step_number"]
            if step_title is None and span.get("step_title"):
                step_title = span["step_title"]

        # Confidence scoring based on retries and failures
        if retry_count <= _HIGH_CONFIDENCE_MAX_RETRIES and failure_count == 0:
            confidence = "high"
        elif retry_count <= _MEDIUM_CONFIDENCE_MAX_RETRIES:
            confidence = "medium"
        else:
            confidence = "low"

        # Skip phases with no meaningful activity
        if not files_written and not files_read and not motivation:
            continue

        phases.append({
            "step_number": step_number,
            "step_title": step_title,
            "files_written": files_written,
            "files_read": files_read,
            "motivation": motivation,
            "pivots": _detect_pivots(spans),
            "confidence": confidence,
            "retry_count": retry_count,
            "failure_count": failure_count,
            "duration_ms": round(total_duration, 1),
        })

    return phases


def _detect_pivots(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect strategy pivots from retry chains within a step."""
    pivots: list[dict[str, Any]] = []
    retry_spans = [s for s in spans if s.get("is_retry") and s.get("retries_span_id")]

    # Build a map of original span_id → span for lookups
    span_by_id = {s["span_id"]: s for s in spans}

    for retry in retry_spans:
        original_id = retry.get("retries_span_id")
        original = span_by_id.get(original_id)
        if original is None:
            continue

        from_approach = original.get("tool_name") or original.get("tool_target") or "previous approach"
        to_approach = retry.get("tool_name") or retry.get("tool_target") or "new approach"
        reason = retry.get("error_kind") or "retry after failure"

        # Only record pivot if there's actually a change in approach
        if from_approach != to_approach or retry.get("error_kind"):
            pivots.append({
                "from_approach": str(from_approach),
                "to_approach": str(to_approach),
                "reason": str(reason),
                "span_id": retry["span_id"],
            })

    return pivots


async def build_dead_ends(
    session: AsyncSession,
    job_id: str,
) -> list[dict[str, Any]]:
    """Identify dead ends — clusters of failed spans that didn't lead to
    successful file writes."""
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT id AS span_id,
                   name AS tool_name,
                   tool_target,
                   error_kind,
                   motivation_summary,
                   duration_ms,
                   turn_id
            FROM job_telemetry_spans
            WHERE job_id = :jid
              AND error_kind IS NOT NULL
            ORDER BY started_at ASC
        """),
        {"jid": job_id},
    )

    # Group consecutive failures by turn_id
    failure_groups: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for r in rows.mappings():
        failure_groups[r["turn_id"]].append(dict(r))

    # Check which turns also produced successful file writes
    success_rows = await session.execute(
        text("""
            SELECT DISTINCT turn_id
            FROM job_telemetry_spans
            WHERE job_id = :jid
              AND tool_category = 'file_write'
              AND error_kind IS NULL
        """),
        {"jid": job_id},
    )
    successful_turns = {r[0] for r in success_rows.fetchall()}

    dead_ends: list[dict[str, Any]] = []
    for turn_id, failures in failure_groups.items():
        # Only flag as dead end if the turn didn't also produce successful writes
        if turn_id in successful_turns:
            continue
        if not failures:
            continue

        total_dur = sum(_safe_float(f.get("duration_ms")) for f in failures)
        what = failures[0].get("motivation_summary") or failures[0].get("tool_name") or "unknown approach"
        reasons = {f.get("error_kind", "") for f in failures if f.get("error_kind")}
        why = ", ".join(sorted(reasons)) if reasons else "failed"

        dead_ends.append({
            "what": str(what),
            "why_abandoned": str(why),
            "span_ids": [f["span_id"] for f in failures],
            "duration_ms": round(total_dur, 1),
        })

    return dead_ends


async def build_decisions(
    session: AsyncSession,
    job_id: str,
) -> list[dict[str, Any]]:
    """Extract approval decisions for the journey report."""
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT description, resolution, requires_explicit_approval
            FROM approvals
            WHERE job_id = :jid
            ORDER BY requested_at ASC
        """),
        {"jid": job_id},
    )

    decisions: list[dict[str, Any]] = []
    for r in rows.mappings():
        decisions.append({
            "description": r["description"] or "",
            "resolution": r["resolution"] or "pending",
            "is_approval": True,
        })

    return decisions


async def build_fragile_areas(
    session: AsyncSession,
    job_id: str,
) -> list[str]:
    """Identify files with high retry counts — areas a resuming agent
    should approach carefully."""
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT tool_target,
                   SUM(CASE WHEN is_retry THEN 1 ELSE 0 END) AS retries,
                   SUM(CASE WHEN error_kind IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM job_telemetry_spans
            WHERE job_id = :jid
              AND tool_category = 'file_write'
              AND tool_target IS NOT NULL
            GROUP BY tool_target
            HAVING retries > 1 OR errors > 0
            ORDER BY retries DESC, errors DESC
        """),
        {"jid": job_id},
    )

    return [str(r["tool_target"]) for r in rows.mappings()]


async def build_journey_report(
    session: AsyncSession,
    job_id: str,
) -> dict[str, Any] | None:
    """Build the full cognitive journey report for a job.

    Returns None if there's insufficient telemetry data.
    Entirely deterministic — no LLM calls.
    """
    from sqlalchemy import text

    # Job metadata
    row = await session.execute(
        text("SELECT id, title, prompt, model FROM jobs WHERE id = :jid"),
        {"jid": job_id},
    )
    job = row.mappings().first()
    if not job:
        return None

    # Telemetry summary
    summary_row = await session.execute(
        text("""
            SELECT duration_ms, total_cost_usd, tool_call_count
            FROM job_telemetry_summary WHERE job_id = :jid
        """),
        {"jid": job_id},
    )
    summary = summary_row.mappings().first()

    phases = await build_journey_phases(session, job_id)
    dead_ends = await build_dead_ends(session, job_id)
    decisions = await build_decisions(session, job_id)
    fragile = await build_fragile_areas(session, job_id)

    if not phases:
        return None

    return {
        "job_id": job_id,
        "title": job["title"] or "",
        "original_task": job["prompt"] or "",
        "phases": phases,
        "dead_ends": dead_ends,
        "decisions": decisions,
        "fragile_areas": fragile,
        "total_duration_ms": _safe_float(summary["duration_ms"]) if summary else 0.0,
        "total_tool_calls": (summary["tool_call_count"] or 0) if summary else 0,
        "total_cost_usd": (summary["total_cost_usd"] or 0.0) if summary else 0.0,
    }


# ---------------------------------------------------------------------------
# LLM synthesis prompts
# ---------------------------------------------------------------------------

_HANDOFF_SYNTHESIS_PROMPT = """\
You are writing a handoff analysis for a coding agent that is about to resume \
work on this task. Another agent did the work below — your job is to add \
causal analysis the raw data cannot convey on its own.

The VERIFIED TELEMETRY section that follows your analysis is the ground truth. \
Your analysis supplements it — it does NOT replace it.

RULES:
- Connect causes: "X failed because Y, so the agent switched to Z" — the \
  telemetry shows WHAT happened; you explain WHY and how events connect.
- Prioritise: what matters most for the NEXT agent? Lead with that.
- Call out non-obvious risks: patterns across phases, cascading effects, \
  implications the raw data doesn't surface.
- Be direct and concrete. No filler, no self-assessment, no hedging.
- Target 100-200 words. Shorter if the journey is simple.
- Do NOT repeat file lists, retry counts, or other facts already in the \
  telemetry section. Reference them ("the 3 retries in step 2 suggest…") \
  but don't restate them.

JOURNEY DATA:
{journey_data}
"""


_ARTIFACT_NARRATIVE_PROMPT = """\
You are writing an analysis section for a session journey report that a human \
reviewer will read alongside the verified telemetry data. Your job is to make \
the journey comprehensible — connecting the dots that raw data cannot.

The VERIFIED TELEMETRY section in the report is the ground truth. Your \
analysis supplements it — it does NOT replace it.

RULES:
- Write in third person past tense ("The agent started by…").
- Lead with a one-sentence summary of the overall outcome.
- Connect phases causally ("After the JWT approach failed, the agent \
  switched to…") — the telemetry shows the events, you explain the thread.
- Call out non-obvious risks and implications.
- Note operator decisions and their downstream impact.
- Do NOT repeat facts already in the telemetry section. Reference them \
  ("the retries on auth.ts suggest…") but don't restate them.
- No filler, no assessment of quality ("elegantly", "struggled with"). \
  Let the facts speak.
- Target 150-400 words depending on journey complexity.

JOURNEY DATA:
{journey_data}
"""


# ---------------------------------------------------------------------------
# Handoff context builder
# ---------------------------------------------------------------------------

async def build_journey_handoff_context(
    session: "AsyncSession",
    job_id: str,
    completer: "Completable",
) -> str | None:
    """Build a two-layer handoff context from the cognitive journey.

    Returns both layers clearly delineated:
    - **LLM analysis**: causal connections, priorities, non-obvious risks
    - **Verified telemetry**: deterministic facts from spans (ground truth)

    The resuming agent sees both and always knows which is which.
    """
    report = await build_journey_report(session, job_id)
    if report is None:
        return None

    deterministic = _format_deterministic_record(report)

    prompt = _HANDOFF_SYNTHESIS_PROMPT.format(journey_data=deterministic)
    raw = await completer.complete(prompt)
    analysis = raw.strip() if isinstance(raw, str) else str(raw).strip()
    log.info("journey_handoff_synthesized", job_id=job_id, length=len(analysis))

    # Two clearly separated layers — analysis first (actionable), then ground truth
    return (
        "## Journey analysis (LLM-synthesized — interpret with judgment)\n\n"
        f"{analysis}\n\n"
        "## Verified telemetry (deterministic — ground truth from spans)\n\n"
        f"{deterministic}"
    )


def _format_deterministic_record(report: dict[str, Any]) -> str:
    """Format the journey report as structured text from verified telemetry."""
    parts: list[str] = []

    for phase in report["phases"]:
        header = "### Step"
        if phase.get("step_number") is not None:
            header += f" {phase['step_number']}"
        if phase.get("step_title"):
            header += f": {phase['step_title']}"
        parts.append(header)

        if phase.get("motivation"):
            parts.append(f"Approach: {phase['motivation']}")

        if phase.get("files_written"):
            parts.append(f"Files written: {', '.join(phase['files_written'])}")
        if phase.get("files_read"):
            parts.append(f"Files read: {', '.join(phase['files_read'][:10])}")

        conf = phase.get("confidence", "high")
        retries = phase.get("retry_count", 0)
        failures = phase.get("failure_count", 0)
        parts.append(f"Confidence: {conf.upper()} — {retries} retries, {failures} failures")

        for pivot in phase.get("pivots", []):
            parts.append(
                f"  PIVOT: {pivot['from_approach']} → {pivot['to_approach']} "
                f"(reason: {pivot['reason']})"
            )

        dur = round(phase.get("duration_ms", 0) / 1000, 1)
        parts.append(f"Duration: {dur}s")
        parts.append("")

    if report["dead_ends"]:
        parts.append("### Dead ends")
        for de in report["dead_ends"]:
            dur_de = round(de.get("duration_ms", 0) / 1000, 1)
            parts.append(f"- {de['what']}: {de['why_abandoned']} ({dur_de}s)")
        parts.append("")

    if report["fragile_areas"]:
        parts.append("### Fragile areas")
        for f in report["fragile_areas"]:
            parts.append(f"- {f}")
        parts.append("")

    if report["decisions"]:
        parts.append("### Decisions (operator-approved)")
        for d in report["decisions"]:
            parts.append(f"- {d['description']} → {d['resolution']}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Artifact export
# ---------------------------------------------------------------------------

async def store_journey_report_artifact(
    session: "AsyncSession",
    job_id: str,
    completer: "Completable",
    *,
    slug: str = "",
) -> Any | None:
    """Generate and store the journey report as a downloadable artifact.

    The artifact contains both the raw deterministic JSON (machine-readable)
    and an LLM-synthesized narrative (human-readable Markdown).

    Returns the created Artifact, or None if insufficient telemetry.
    """
    import re as _re

    from backend.models.domain import Artifact
    from backend.persistence.artifact_repo import ArtifactRepository

    report = await build_journey_report(session, job_id)
    if report is None:
        return None

    artifact_repo = ArtifactRepository(session)

    # Check for existing journey report to upsert
    existing_artifacts = await artifact_repo.list_for_job(job_id)
    existing_journey = next(
        (a for a in existing_artifacts if a.type == ArtifactType.journey_report),
        None,
    )

    tag = _re.sub(r"[^a-z0-9]+", "-", (slug or "").lower()).strip("-")[:40]
    if not tag:
        tag = job_id[:12]

    # Deterministic data for the prompt
    deterministic = _format_deterministic_handoff(report)

    # Synthesize the human-readable narrative via LLM
    prompt = _ARTIFACT_NARRATIVE_PROMPT.format(journey_data=deterministic)
    raw_narrative = await completer.complete(prompt)
    narrative = raw_narrative.strip() if isinstance(raw_narrative, str) else str(raw_narrative).strip()
    log.info("journey_artifact_narrative_synthesized", job_id=job_id, length=len(narrative))

    # Build combined artifact: structured JSON + synthesized Markdown
    md_header = _render_journey_markdown_header(report)
    md_content = md_header + "\n" + narrative

    combined = {"json": report, "markdown": md_content}
    content = json.dumps(combined, indent=2)

    if existing_journey is not None:
        disk_path = Path(existing_journey.disk_path)
        disk_path.write_text(content, encoding="utf-8")
        await artifact_repo.update_size_bytes(existing_journey.id, disk_path.stat().st_size)
        log.info("journey_report_updated", job_id=job_id)
        return existing_journey

    artifact_id = f"art-{uuid.uuid4().hex[:12]}"
    name = f"{tag}-journey-report.json"

    disk_dir = _ARTIFACTS_BASE / job_id
    disk_dir.mkdir(parents=True, exist_ok=True)
    disk_path = disk_dir / f"{artifact_id}-{name}"
    disk_path.write_text(content, encoding="utf-8")

    artifact = Artifact(
        id=artifact_id,
        job_id=job_id,
        name=name,
        type=ArtifactType.journey_report,
        mime_type="application/json",
        size_bytes=disk_path.stat().st_size,
        disk_path=str(disk_path),
        phase=ExecutionPhase.post_completion,
        created_at=datetime.now(UTC),
    )
    created = await artifact_repo.create(artifact)
    log.info("journey_report_created", job_id=job_id, phases=len(report["phases"]))
    return created


def _render_journey_markdown_header(report: dict[str, Any]) -> str:
    """Render the metadata header for the journey report Markdown."""
    lines: list[str] = []

    title = report.get("title") or report["job_id"][:12]
    lines.append(f"# Session Journey Report — {title}\n")

    task = report.get("original_task", "")
    if task:
        lines.append(f"**Task:** {task[:200]}\n")

    dur_min = round(report.get("total_duration_ms", 0) / 60_000, 1)
    tool_calls = report.get("total_tool_calls", 0)
    cost = report.get("total_cost_usd", 0.0)
    lines.append(f"**Duration:** {dur_min} min · {tool_calls} tool calls · ${cost:.2f}\n")
    lines.append("---\n")

    return "\n".join(lines)


def _safe_float(v: Any) -> float:
    """Safely convert a value to float (telemetry stores floats as text)."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0
