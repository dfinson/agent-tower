"""Memory extractor session — extracts reusable knowledge from completed jobs.

Post-job: given key decisions from a job's trail, extracts 0-3 entries that
would help future jobs on the same repository. Uses the adapter's ``complete()``
(same session mechanism as all other utility sessions).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.agent_adapter import AgentAdapterInterface

log = structlog.get_logger()

_EXTRACTOR_SYSTEM_PROMPT = """\
You are a workspace memory extractor for a coding agent control plane.
A coding agent just finished a job. Based on its key decisions, extract 0-3
entries that would help FUTURE jobs on this same repository.

Rules:
- Only include things a future job would otherwise have to re-discover or re-decide.
- Skip routine/obvious decisions (e.g. "ran tests", "committed code").
- Focus on: architectural choices, naming conventions, gotchas, environment quirks,
  integration patterns, tool configurations.
- Format each entry as:
  ### YYYY-MM-DD: Short Title
  Brief explanation.
- If nothing is worth remembering, return NONE.
"""


class MemoryExtractor:
    """Dedicated session for extracting reusable knowledge after a job completes."""

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter

    async def extract(self, decisions_text: str, timeout: float = 15.0) -> str | None:
        """Extract memory entries from job decisions.

        Returns extracted entries as markdown text, or None if nothing
        worth remembering. Raises on failure (caller handles).
        """
        prompt = (
            f"{_EXTRACTOR_SYSTEM_PROMPT}\n\n"
            f"## Key Decisions from Job\n{decisions_text}"
        )
        t0 = time.monotonic()
        result = await asyncio.wait_for(
            self._adapter.complete(prompt),
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "memory_extractor.completed",
            elapsed_ms=round(elapsed_ms, 1),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        text = (result.text or "").strip()
        if not text or text.upper() == "NONE":
            return None
        return text
