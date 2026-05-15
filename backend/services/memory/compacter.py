"""Memory compacter session — dedicated session for workspace memory compaction.

A single-purpose session that uses the agent adapter's ``complete()`` method
(same underlying mechanism as sidecar sessions) but with a system prompt
tailored for distilling accumulated workspace memory.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.adapters.agent_adapter import AgentAdapterInterface

log = structlog.get_logger()

# -- Shared content policy (referenced by all prompts) ----------------------

_CONTENT_POLICY = """\
Content policy — ENFORCED:
- ONLY facts, verified patterns, and explicit user preferences.
- NO LLM opinion, speculation, recommendations, "consider doing X", or
  commentary on code quality.
- NO entries that restate what is obvious from the code itself.
- Every entry must be something a future job would otherwise have to
  re-discover or re-decide. If it can be found by reading the code, delete it.
"""

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

""" + _CONTENT_POLICY

_NORMALIZE_SYSTEM_PROMPT = """\
You are a workspace memory normalizer for a coding agent control plane.
You receive EXISTING memory and NEW entries extracted from a completed job.

Your job:
1. DEDUPLICATE: If a new entry duplicates or overlaps an existing entry,
   merge them into one (keep the more specific/recent version).
2. SUMMARIZE: Condense verbose entries into single-paragraph facts.
3. STRIP OPINION: Remove any LLM commentary, speculation, recommendations,
   or subjective assessments. Keep only verified facts and patterns.
4. FLAG STALE: If any existing entry references files, functions, endpoints,
   or patterns that the new job's decisions contradict or supersede, remove
   the stale entry entirely.

Output the COMPLETE merged memory (existing + new, after dedup/cleanup).
Use the same ### heading format. Return ONLY the memory, no preamble.

""" + _CONTENT_POLICY


class MemoryCompacter:
    """Dedicated session for workspace memory compaction and normalization.

    Uses the adapter's ``complete()`` — same session mechanism as
    SidecarSession — but with compaction/normalization-specific prompts.
    """

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter

    async def compact(self, memory_content: str) -> str:
        """Summarize *memory_content* into a condensed version.

        Returns the summarized text. Raises on failure (caller handles).
        """
        prompt = f"{_COMPACTION_SYSTEM_PROMPT}\n\n## Current Memory ({len(memory_content)} bytes)\n\n{memory_content}"
        t0 = time.monotonic()
        result = await self._adapter.complete(prompt)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "memory_compacter.completed",
            elapsed_ms=round(elapsed_ms, 1),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result.text or ""

    async def normalize(self, existing: str, new_entries: str) -> str:
        """Deduplicate, summarize, and strip opinion from merged memory.

        Called on every inbox merge — ensures every write passes through
        the LLM gate. Returns the cleaned combined memory text.
        Raises on failure (caller handles).
        """
        prompt = (
            f"{_NORMALIZE_SYSTEM_PROMPT}\n\n"
            f"## Existing Memory\n\n{existing or '(empty)'}\n\n"
            f"## New Entries\n\n{new_entries}"
        )
        t0 = time.monotonic()
        result = await self._adapter.complete(prompt)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "memory_compacter.normalize_completed",
            elapsed_ms=round(elapsed_ms, 1),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result.text or ""
