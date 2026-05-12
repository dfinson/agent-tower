"""Memory compacter session — dedicated session for workspace memory compaction.

A single-purpose session that uses the agent adapter's ``complete()`` method
(same underlying mechanism as sister sessions) but with a system prompt
tailored for distilling accumulated workspace memory.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.agent_adapter import AgentAdapterInterface

log = structlog.get_logger()

_COMPACTION_SYSTEM_PROMPT = """\
You are a workspace memory compacter for a coding agent control plane.
Your job is to distill accumulated decisions and knowledge into a concise,
non-redundant summary that future jobs in the same repository will need.

Rules:
- Remove anything obvious, outdated, superseded, or duplicated.
- Preserve concrete, actionable knowledge: architectural decisions, naming
  conventions, gotchas, environment details, integration patterns.
- Keep the same markdown format (### headings with dates and bodies).
- Merge entries about the same topic into one.
- Return ONLY the condensed memory. No preamble, no commentary.
"""


class MemoryCompacter:
    """Dedicated session for workspace memory compaction.

    Uses the adapter's ``complete()`` — same session mechanism as
    SisterSession — but with a compaction-specific system prompt.
    """

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter

    async def compact(self, memory_content: str, timeout: float = 60.0) -> str:
        """Summarize *memory_content* into a condensed version.

        Returns the summarized text. Raises on failure (caller handles).
        """
        prompt = (
            f"{_COMPACTION_SYSTEM_PROMPT}\n\n"
            f"## Current Memory ({len(memory_content)} bytes)\n\n"
            f"{memory_content}"
        )
        t0 = time.monotonic()
        result = await asyncio.wait_for(
            self._adapter.complete(prompt),
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "memory_compacter.completed",
            elapsed_ms=round(elapsed_ms, 1),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result.text or ""
