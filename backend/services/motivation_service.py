"""Background motivation summarization service.

Processes telemetry spans that have preceding_context (captured at
tool-call time for mutative actions) but no motivation_summary yet.
Calls a cheap LLM (gpt-4o-mini via the configured utility model) to
generate a concise explanation of *why* the change was made.

Two-pass pipeline:
1. File-level: preceding_context → motivation_summary (title + why per span)
2. Edit-level: tool_args → edit_motivations (title + why per edit, with edit_key)

Runs as a periodic drain loop during the application lifespan.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.naming_service import Completable

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You explain why a code change was made. Write in abstract third person — no \"I\", "
    "no \"the agent\", no \"this edit\", no \"this change\".\n\n"
    "Output exactly two lines of plain text (no markdown, no headers, no bullets):\n"
    "LINE 1: Title — ≤10 words. Name the file and what changed. No filler words.\n"
    "LINE 2: WHY — 1-2 sentences. Only explain what isn't obvious from the diff. "
    "Reference the specific prior finding, bug, or upstream change that caused this. "
    "Cite concrete file paths, function names, finding IDs, or todo IDs from the context. "
    "Never restate what the diff already shows. Never say \"aligns with\", \"ensures consistency\", "
    "\"improves maintainability\", or similar filler.\n\n"
    "Never fabricate references. Only cite what appears in the provided context."
)

_EDIT_SYSTEM_PROMPT = (
    "You explain why a specific code edit was made. Write in abstract third person — no \"I\", "
    "no \"the agent\", no \"this edit\", no \"this change\".\n\n"
    "Output exactly two lines of plain text (no markdown, no headers, no bullets):\n"
    "LINE 1: Title — ≤10 words. Name the specific change. No filler words.\n"
    "LINE 2: WHY — 1-2 sentences. Only explain what isn't obvious from the diff. "
    "Reference the specific prior finding, bug, or upstream change that caused this. "
    "Cite concrete file paths, function names, finding IDs, or todo IDs from the context. "
    "Never restate what the diff already shows. Never say \"aligns with\", \"ensures consistency\", "
    "\"improves maintainability\", or similar filler.\n\n"
    "Never fabricate references. Only cite what appears in the provided context."
)

# Batch size for each drain cycle
_BATCH_SIZE = 20

# Pause between drain cycles (seconds)
_DRAIN_INTERVAL = 10.0

# Max chars for old_str/new_str in the mini-diff display
_DIFF_DISPLAY_MAX = 600


def _build_user_prompt(
    tool_name: str,
    tool_args_json: str | None,
    preceding_context: str,
    job_description: str | None = None,
) -> str:
    """Assemble the user prompt from span data and preceding context."""
    parts: list[str] = []
    if job_description:
        parts.append(f"JOB DESCRIPTION:\n{job_description}\n")
    parts.append(f"PRECEDING CONTEXT (most recent transcript):\n{preceding_context}\n")
    parts.append(f"TOOL CALLED: {tool_name}")
    if tool_args_json:
        # Truncate very large args
        args_display = tool_args_json[:2000]
        parts.append(f"TOOL ARGS:\n{args_display}")
    return "\n".join(parts)


class MotivationService:
    """Generates motivation summaries for mutative tool spans."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        completer: Completable,
    ) -> None:
        self._session_factory = session_factory
        self._completer = completer

    async def drain_unsummarized(self) -> int:
        """Process a batch of unsummarized spans. Returns count processed."""
        from backend.persistence.job_repo import JobRepository
        from backend.persistence.telemetry_spans_repo import TelemetrySpansRepo

        async with self._session_factory() as session:
            repo = TelemetrySpansRepo(session)
            spans = await repo.unsummarized_spans(limit=_BATCH_SIZE)

            if not spans:
                return 0

            # Pre-fetch job descriptions for the batch
            job_ids = {s["job_id"] for s in spans}
            job_descriptions: dict[str, str | None] = {}
            job_repo = JobRepository(session)
            for jid in job_ids:
                job_row = await job_repo.get(jid)
                if job_row:
                    desc = getattr(job_row, "description", None) or getattr(job_row, "prompt", None)
                    job_descriptions[jid] = str(desc)[:500] if desc else None
                else:
                    job_descriptions[jid] = None

            processed = 0
            for span in spans:
                try:
                    prompt = _build_user_prompt(
                        tool_name=span["name"],
                        tool_args_json=span.get("tool_args_json"),
                        preceding_context=span["preceding_context"],
                        job_description=job_descriptions.get(span["job_id"]),
                    )
                    full_prompt = f"SYSTEM:\n{_SYSTEM_PROMPT}\n\nUSER:\n{prompt}"
                    result = await self._completer.complete(full_prompt)
                    summary_text = result if isinstance(result, str) else getattr(result, "text", str(result))
                    summary_text = summary_text.strip()

                    if summary_text:
                        await repo.set_motivation_summary(span["id"], summary_text)
                        processed += 1
                except Exception:
                    log.debug(
                        "motivation_summarize_failed",
                        span_id=span["id"],
                        exc_info=True,
                    )

            await session.commit()
            return processed

    async def drain_loop(self) -> None:
        """Run forever, periodically processing unsummarized spans."""
        while True:
            try:
                count = await self.drain_unsummarized()
                if count:
                    log.info("motivation_batch_processed", count=count)
            except Exception:
                log.debug("motivation_drain_error", exc_info=True)
            await asyncio.sleep(_DRAIN_INTERVAL)
