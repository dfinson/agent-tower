"""Preflight context curator — selects relevant context for a job.

Pre-job: given the task prompt, workspace memory, and (optionally) structural
analysis from ReviewKit.understand(), produces curated context for the agent's
system prompt. Handles both concerns in one session so there's a single
pre-flight LLM call per job.

Uses the adapter's ``complete()`` (same mechanism as all other utility sessions).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.services.agent_adapter import AgentAdapterInterface

log = structlog.get_logger()

_PREFLIGHT_SYSTEM_PROMPT = """\
You are a preflight context curator for a coding agent control plane.
You receive a task description and one or more context sources about the repository.
Your job: produce a focused brief that will help a coding agent start working
immediately without wasting time exploring.

## Context sources you may receive

1. **Workspace memory** — accumulated knowledge entries from past sessions.
   Select ONLY entries relevant to the task. Return them VERBATIM with their
   ### heading format preserved.

2. **Repository structure** — structural analysis (languages, key files by
   PageRank, key symbols, dependency cycles, module communities). Summarize
   what matters for THIS task: relevant files, symbols, module boundaries,
   dependency relationships, potential pitfalls.

## Rules

- Be concise and direct — the agent reads this once at session start.
- Omit anything unrelated to the specific task.
- If a context source has nothing relevant, skip it entirely.
- Do NOT reproduce raw structural data verbatim — synthesize and prioritize.
- For memory entries, preserve them verbatim. For structural data, summarize freely.
- If nothing from any source is relevant, return an empty response.
"""


def _serialize_understand_result(result: Any) -> str:
    """Best-effort JSON serialization of an UnderstandResult."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result, default=str, indent=2)
    if hasattr(result, "__dict__"):
        return json.dumps(result.__dict__, default=str, indent=2)
    return str(result)


class PreflightCurator:
    """Dedicated session for pre-job context curation.

    Combines workspace memory selection and structural orientation into
    a single LLM call.
    """

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter

    async def curate(
        self,
        task: str,
        *,
        memory: str | None = None,
        understand_result: Any | None = None,
    ) -> str:
        """Produce curated preflight context for *task*.

        Accepts any combination of context sources. Returns the curator's
        output (may be empty if nothing is relevant).
        Raises on failure (caller handles).
        """
        sections: list[str] = []

        if memory:
            sections.append(f"## Workspace Memory\n\n{memory}")

        if understand_result is not None:
            raw_text = _serialize_understand_result(understand_result)
            sections.append(f"## Repository Structure\n```json\n{raw_text}\n```")

        if not sections:
            return ""

        context_block = "\n\n".join(sections)
        prompt = (
            f"{_PREFLIGHT_SYSTEM_PROMPT}\n\n"
            f"## Task\n{task}\n\n"
            f"{context_block}"
        )
        t0 = time.monotonic()
        result = await self._adapter.complete(prompt)
        elapsed_ms = (time.monotonic() - t0) * 1000
        log.debug(
            "preflight_curator.completed",
            elapsed_ms=round(elapsed_ms, 1),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result.text or ""
