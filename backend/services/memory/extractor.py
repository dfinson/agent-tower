"""Memory extractor session — extracts reusable knowledge from completed jobs.

Post-job: given key decisions from a job's trail, extracts 0-3 entries that
would help future jobs on the same repository. Uses the adapter's ``complete()``
(same session mechanism as all other utility sessions).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.adapters.agent_adapter import AgentAdapterInterface

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

# Chunk boundary for decisions text: ~16K chars per chunk.
# Derived from typical model context window minus system prompt overhead.
# A 128K-token model at ~4 chars/token = 512K chars usable; we chunk
# conservatively to leave room for the system prompt and output.
_EXTRACTOR_CHUNK_CHARS = 16_000


class MemoryExtractor:
    """Dedicated session for extracting reusable knowledge after a job completes."""

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter

    async def extract(self, decisions_text: str) -> str | None:
        """Extract memory entries from job decisions.

        If the decisions text is too large for a single prompt, splits into
        chunks and calls the LLM on each, then combines results.

        Returns extracted entries as markdown text, or None if nothing
        worth remembering. Raises on failure (caller handles).
        """
        chunks = _split_decisions(decisions_text)
        all_entries: list[str] = []

        for chunk in chunks:
            result_text = await self._extract_chunk(chunk)
            if result_text:
                all_entries.append(result_text)

        if not all_entries:
            return None
        return "\n\n".join(all_entries)

    async def _extract_chunk(self, chunk: str) -> str | None:
        """Extract from a single chunk of decisions text."""
        prompt = f"{_EXTRACTOR_SYSTEM_PROMPT}\n\n## Key Decisions from Job\n{chunk}"
        t0 = time.monotonic()
        result = await self._adapter.complete(prompt)
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


def _split_decisions(text: str) -> list[str]:
    """Split decisions text into chunks that fit in a single LLM call.

    Splits on line boundaries to avoid cutting mid-decision.
    """
    if len(text) <= _EXTRACTOR_CHUNK_CHARS:
        return [text]

    chunks: list[str] = []
    lines = text.split("\n")
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for the newline
        if current_len + line_len > _EXTRACTOR_CHUNK_CHARS and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks
