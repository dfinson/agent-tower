"""Memory curator session — selects relevant workspace memory for a job.

Pre-job: given the task prompt and full workspace memory, returns only the
entries relevant to this specific task. Uses the adapter's ``complete()``
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

_CURATOR_SYSTEM_PROMPT = """\
You are a workspace memory curator for a coding agent control plane.
You receive a task description and the full workspace memory for the repository.
Your job is to select ONLY the entries from workspace memory that are directly
relevant to the given task.

Rules:
- Return relevant entries VERBATIM, preserving their ### heading format.
- Omit anything unrelated to the specific task.
- If nothing is relevant, return an empty response.
- Do NOT add commentary, explanations, or modify the entries.
- Be selective — only include entries that would genuinely help with THIS task.
"""


class MemoryCurator:
    """Dedicated session for curating workspace memory before a job starts."""

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter
        self._primed = False

    def _build_prompt(self, task: str, memory: str) -> str:
        """Construct the curation prompt."""
        user_part = (
            f"Given this task:\n{task}\n\n"
            f"## Workspace Memory\n\n{memory}"
        )
        if not self._primed:
            self._primed = True
            return f"{_CURATOR_SYSTEM_PROMPT}\n\n{user_part}"
        return user_part

    async def curate(self, task: str, memory: str, timeout: float = 15.0) -> str:
        """Select relevant memory entries for *task*.

        Returns the curated subset (may be empty if nothing is relevant).
        Raises on failure (caller handles).
        """
        prompt = self._build_prompt(task, memory)
        t0 = time.monotonic()
        result = await asyncio.wait_for(
            self._adapter.complete(prompt),
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "memory_curator.completed",
            elapsed_ms=round(elapsed_ms, 1),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result.text or ""
