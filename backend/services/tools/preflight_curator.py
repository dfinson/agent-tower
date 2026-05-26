"""Preflight context curator — agent session that selects relevant context for a job.

Runs as a proper agent session with read-only CodeRecon tools.  The curator
agent can call ``recon_scout`` (with optional ``scope``), ``recon``,
``recon_map``, ``recon_impact``, and ``scaffold`` to explore the repository
structure, then produces a curated brief for the main agent's system prompt.

SDK-agnostic: uses ``create_session()`` + ``stream_events()`` through the
adapter interface, so the same flow works with any underlying SDK.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from backend.models.domain import SessionConfig, SessionEventKind

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from backend.services.adapters.agent_adapter import AgentAdapterInterface
    from backend.services.coderecon.coderecon_service import CodeReconService

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Structured result returned to callers
# ---------------------------------------------------------------------------

@dataclass
class PreflightToolCall:
    """A single tool invocation captured during a preflight/secondary session."""

    tool_name: str
    tool_args: str | None = None
    result_text: str = ""
    success: bool = True
    duration_ms: float | None = None


@dataclass
class PreflightReport:
    """Structured output from a preflight curator session."""

    brief: str = ""
    tool_calls: list[PreflightToolCall] = field(default_factory=list)
    elapsed_ms: float = 0.0


# Preflight sessions are short — cap turns and wall-clock time.
_MAX_TURNS = 15
_SESSION_TIMEOUT_S = 120  # 2 minutes

# Built-in tools the curator must NOT use.
# We block filesystem-write, shell, and web tools so the session explores
# via CodeRecon structural tools first.  View is allowed as a targeted
# fallback for inspecting specific lines after structural analysis.
#
# Claude Code uses PascalCase names; Copilot SDK uses snake_case.
# Both sets must be listed for SDK-agnostic enforcement.
_DISALLOWED_BUILTIN_TOOLS = [
    # Claude Code names
    "Bash",
    "Edit",
    "MultiEdit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "LS",
    "Task",
    "WebFetch",
    "WebSearch",
    "TodoRead",
    "TodoWrite",
    "NotebookRead",
    "NotebookEdit",
    # Copilot SDK names
    "bash",
    "str_replace_editor",
    "insert_edit_file",
    "create_file",
    "read_file",
    "list_dir",
    "file_search",
    "grep_search",
    "run_in_terminal",
    "semantic_search",
    "get_errors",
]

_PREFLIGHT_SYSTEM_PROMPT = """\
You are a preflight context curator for a coding agent control plane.
Your job: produce a reconnaissance brief — map the relevant code, its current
state, and risks — so the coding agent starts with full situational awareness
instead of exploring blind.

## Tools — use in this order

You have structural analysis tools for this repository.  **Always start with
these** — they give you the full picture in one call.

### Primary tools (use FIRST)

- **recon_scout** — Codebase overview: languages, top files by PageRank,
  key symbols, dependency cycles, module communities.  Call with no arguments
  for the broad view, or pass ``scope`` (e.g. ``"backend/services"``) to zoom
  into a specific module or directory.
- **recon** — Task-aware context retrieval.  Pass your task description to get
  ranked code spans.
- **recon_map** — Repository structure map with entry points.
- **recon_impact** — Reference/caller analysis for a specific symbol.
- **scaffold** — File structural overview (imports + symbol hierarchy).

### Fallback (use LAST, minimally)

- **View** — Read specific file lines.  Use ONLY after structural tools have
  identified the exact file and lines you need.  Never use View as your first
  or primary exploration tool.

## Strategy

1. Start with ``recon_scout`` for the broad structural view.
2. If the task targets a specific subsystem, zoom with
   ``recon_scout(scope="path/to/module")``.
3. Use ``recon``, ``scaffold``, and ``recon_impact`` for deeper structural
   detail on specific files or symbols.
4. Only if you need to verify exact syntax or a specific code pattern that
   structural tools cannot answer, use View on the minimal line range needed.

## Output rules

- **You are a SCOUT, not a planner.**  Your job is RECONNAISSANCE — map the
  terrain and mark hazards.  The executor decides the route.
- Do NOT include implementation steps, numbered action lists, or instructions
  telling the agent what to change, import, create, or delete.  No "the agent
  needs to do X" or "modify file Y to Z".  That is planning, not mapping.
- DO include: file locations and what they currently contain, dependency/import
  relationships, existing patterns and conventions the agent should see,
  potential breakage risks (e.g. "test X asserts on field Y which is part of
  the surface being changed"), and relevant constraints (framework, test
  runner, package manager).
- Risks are **observations**, not instructions.  Say "tests/test_api.py:15
  asserts `timestamp` is in the health response" — do NOT say "update
  tests/test_api.py to match the new response".
- Err on the side of INCLUSION for context.  A few thousand extra tokens here
  saves tens of thousands in wasted exploration during the session.
- For structural data, keep specifics: file paths, symbol names, module
  relationships, cycle members.  The agent needs concrete handles, not vague
  descriptions.
- You may omit things that are clearly irrelevant to the task, but do not
  aggressively filter.  Tangentially related context is better than missing
  context.
- If nothing is relevant, return an empty response.
- Your final message must be ONLY the curated brief — no preamble, no
  explanation of what you did, just the brief itself.
"""


class PreflightCurator:
    """Agent session for pre-job context curation.

    Runs a full agent session with read-only CodeRecon tools so the
    curator can explore the repository structure autonomously — calling
    ``recon_scout`` (with scope), ``recon``, ``scaffold``, etc. as
    many times as it needs before producing the final brief.
    """

    def __init__(
        self,
        adapter: AgentAdapterInterface,
        *,
        coderecon: CodeReconService,
    ) -> None:
        self._adapter = adapter
        self._coderecon = coderecon

    async def curate(
        self,
        task: str,
        *,
        repo: str,
        worktree: str,
        job_id: str = "",
        on_tool_call: "Callable[[PreflightToolCall], Awaitable[None]] | None" = None,
        on_reasoning: "Callable[[str], Awaitable[None]] | None" = None,
    ) -> PreflightReport:
        """Run the preflight curator agent and return its structured report.

        The agent is given the task description and CodeRecon tools.  It
        explores the repo structure and produces a brief for the main
        agent's system prompt.

        Returns a :class:`PreflightReport` with the curated brief, captured
        tool calls, and timing information.
        Raises on failure (caller handles).
        """
        from backend.services.coderecon.coderecon_tools import build_coderecon_tools

        # Build read-only toolkit (preflight tier — no checkpoint/refactor)
        toolkit = build_coderecon_tools(
            self._coderecon,
            repo,
            worktree,
            tier="preflight",
        )

        # Assemble the prompt — reframe the task so the agent understands
        # it's producing a BRIEF, not executing the task itself.
        prompt = (
            "Analyze the following task and produce a structural brief: map the "
            "relevant files, their current state, dependencies, and risks. "
            "Do NOT plan the implementation or tell the agent what to do — "
            "only report what exists and what could break.\n\n"
            f"## Task the agent will execute\n\n{task}"
        )

        # Build session config — SDK-agnostic.
        # system_prompt_override replaces the default CODEPLANE_SYSTEM_PROMPT
        # so the curator gets its own identity (scout, not executor).
        config = SessionConfig(
            workspace_path=repo,
            prompt=prompt,
            job_id=job_id,
            coderecon_tools=toolkit,
            system_prompt_override=_PREFLIGHT_SYSTEM_PROMPT,
            max_turns=_MAX_TURNS,
            disallowed_tools=_DISALLOWED_BUILTIN_TOOLS,
            session_kind="preflight",
        )

        # Run the agent session and collect its output
        return await self._run_session(config, on_tool_call=on_tool_call, on_reasoning=on_reasoning)

    async def _run_session(
        self,
        config: SessionConfig,
        *,
        on_tool_call: "Callable[[PreflightToolCall], Awaitable[None]] | None" = None,
        on_reasoning: "Callable[[str], Awaitable[None]] | None" = None,
    ) -> PreflightReport:
        """Execute the curator session and extract the final brief with tool call data."""
        t0 = time.monotonic()

        session_id = await self._adapter.create_session(config)
        agent_chunks: list[str] = []
        tool_calls: list[PreflightToolCall] = []
        result_text = ""

        try:
            async with asyncio.timeout(_SESSION_TIMEOUT_S):
                async for event in self._adapter.stream_events(session_id):
                    if event.kind == SessionEventKind.transcript:
                        payload = event.payload
                        if isinstance(payload, dict):
                            role = payload.get("role", "")
                            if role == "agent":
                                content = str(payload.get("content", ""))
                                if content and content.strip():
                                    agent_chunks.append(content)
                                    if on_reasoning is not None:
                                        await on_reasoning(content)
                            elif role == "tool_call":
                                raw_args = payload.get("tool_args")
                                raw_result = payload.get("tool_result") or payload.get("content", "")
                                sdk_success = payload.get("tool_success", True)
                                tc = PreflightToolCall(
                                    tool_name=str(payload.get("tool_name", "")),
                                    tool_args=str(raw_args) if raw_args else None,
                                    result_text=str(raw_result) if raw_result else "",
                                    success=bool(sdk_success),
                                    duration_ms=payload.get("duration_ms"),
                                )
                                tool_calls.append(tc)
                                if on_tool_call is not None:
                                    await on_tool_call(tc)

                    elif event.kind == SessionEventKind.done:
                        # ResultMessage carries the complete final text
                        if isinstance(event.payload, dict):
                            r = str(event.payload.get("result", ""))
                            if r and r.strip():
                                result_text = r
                        break

                    elif event.kind == SessionEventKind.error:
                        msg = ""
                        if isinstance(event.payload, dict):
                            msg = str(event.payload.get("message", ""))
                        log.warning("preflight_curator.session_error", error=msg)
                        break
        except TimeoutError:
            log.warning(
                "preflight_curator.session_timeout",
                timeout_s=_SESSION_TIMEOUT_S,
            )
            with contextlib.suppress(Exception):
                await self._adapter.abort_session(session_id)
            # Return whatever the agent produced so far
        except Exception:
            log.warning("preflight_curator.stream_failed", exc_info=True)
            with contextlib.suppress(Exception):
                await self._adapter.abort_session(session_id)
            raise

        elapsed_ms = (time.monotonic() - t0) * 1000
        # Prefer the done-event result (complete text); fall back to
        # the last agent transcript chunk (most likely the final brief).
        brief = result_text or (agent_chunks[-1] if agent_chunks else "")
        log.debug(
            "preflight_curator.session_completed",
            elapsed_ms=round(elapsed_ms, 1),
            result_len=len(brief),
            tool_call_count=len(tool_calls),
        )

        return PreflightReport(
            brief=brief.strip(),
            tool_calls=tool_calls,
            elapsed_ms=round(elapsed_ms, 1),
        )
