"""Preflight context curator — agent session that selects relevant context for a job.

Runs as a proper agent session with read-only CodeRecon tools.  The curator
agent can call ``recon_understand`` (with optional ``scope``), ``recon``,
``recon_map``, ``recon_impact``, and ``scaffold`` to explore the repository
structure, then produces a curated brief for the main agent's system prompt.

Workspace memory is injected as context in the prompt — the agent decides
which entries are relevant to the task and preserves them verbatim.

SDK-agnostic: uses ``create_session()`` + ``stream_events()`` through the
adapter interface, so the same flow works with any underlying SDK.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from backend.models.domain import SessionConfig, SessionEventKind

if TYPE_CHECKING:
    from backend.services.agent_adapter import AgentAdapterInterface
    from backend.services.coderecon_service import CodeReconService

log = structlog.get_logger()

# Preflight sessions are short — cap turns and wall-clock time.
_MAX_TURNS = 15
_SESSION_TIMEOUT_S = 120  # 2 minutes

# Built-in Claude Code / Copilot tools the curator must NOT use.
# We block filesystem, shell, and web tools so the session is read-only
# via CodeRecon MCP tools only.  Even without this list the policy router
# would deny them (no job_id → deny), but disallowing them explicitly
# tells the SDK to hide them, saving tokens and avoiding noisy error logs.
_DISALLOWED_BUILTIN_TOOLS = [
    "Bash",
    "Edit",
    "MultiEdit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "TodoRead",
    "TodoWrite",
]

_PREFLIGHT_SYSTEM_PROMPT = """\
You are a preflight context curator for a coding agent control plane.
Your job: produce a focused brief that will help a coding agent start working
immediately without wasting time exploring.

## Tools

You have read-only structural analysis tools for this repository.  Use them
to understand the codebase before writing your brief.

- **recon_understand** — Codebase overview: languages, top files by PageRank,
  key symbols, dependency cycles, module communities.  Call with no arguments
  for the broad view, or pass ``scope`` (e.g. ``"backend/services"``) to zoom
  into a specific module or directory.
- **recon** — Task-aware context retrieval.  Pass your task description to get
  ranked code spans.
- **recon_map** — Repository structure map with entry points.
- **recon_impact** — Reference/caller analysis for a specific symbol.
- **scaffold** — File structural overview (imports + symbol hierarchy).

Start with ``recon_understand`` for the broad view.  If the task targets a
specific subsystem, zoom in with ``recon_understand(scope="path/to/module")``.
Use ``recon``, ``scaffold``, and ``recon_impact`` for deeper detail on
specific files or symbols you identify as task-relevant.

## Workspace memory

If workspace memory entries are provided in the prompt below, select ONLY
entries relevant to the task and include them VERBATIM with their ### heading
format preserved.

## Output rules

- Err on the side of INCLUSION.  A few thousand extra tokens here saves tens
  of thousands in wasted exploration during the session.  When in doubt, keep it.
- For memory entries, preserve them verbatim with their ### heading format.
- For structural data, summarize freely but keep specifics: file paths, symbol
  names, module relationships, cycle members.  The agent needs concrete handles,
  not vague descriptions.
- You may omit things that are clearly irrelevant to the task, but do not
  aggressively filter.  Tangentially related context is better than missing context.
- If nothing is relevant, return an empty response.
- Your final message must be ONLY the curated brief — no preamble, no
  explanation of what you did, just the brief itself.
"""


class PreflightCurator:
    """Agent session for pre-job context curation.

    Runs a full agent session with read-only CodeRecon tools so the
    curator can explore the repository structure autonomously — calling
    ``recon_understand`` (with scope), ``recon``, ``scaffold``, etc. as
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
        memory: str | None = None,
        repo: str,
        worktree: str,
        job_id: str = "",
    ) -> str:
        """Run the preflight curator agent and return its curated brief.

        The agent is given the task description, optional workspace memory,
        and CodeRecon tools.  It explores the repo structure and produces
        a brief for the main agent's system prompt.

        Returns the curated brief (may be empty if nothing is relevant).
        Raises on failure (caller handles).
        """
        from backend.services.coderecon_tools import build_coderecon_tools

        # Build read-only toolkit (preflight tier — no checkpoint/refactor)
        toolkit = build_coderecon_tools(
            self._coderecon,
            repo,
            worktree,
            tier="preflight",
        )

        # Assemble the prompt
        sections = [f"## Task\n\n{task}"]
        if memory:
            sections.append(f"## Workspace Memory\n\n{memory}")

        prompt = "\n\n".join(sections)

        # Build session config — SDK-agnostic
        config = SessionConfig(
            workspace_path=repo,
            prompt=prompt,
            job_id=job_id,
            coderecon_tools=toolkit,
            memory_context=_PREFLIGHT_SYSTEM_PROMPT,
            max_turns=_MAX_TURNS,
            disallowed_tools=_DISALLOWED_BUILTIN_TOOLS,
            session_kind="preflight",
        )

        # Run the agent session and collect its output
        return await self._run_session(config)

    async def _run_session(self, config: SessionConfig) -> str:
        """Execute the curator session and extract the final brief."""
        t0 = time.monotonic()

        session_id = await self._adapter.create_session(config)
        agent_chunks: list[str] = []
        result_text = ""

        try:
            async with asyncio.timeout(_SESSION_TIMEOUT_S):
                async for event in self._adapter.stream_events(session_id):
                    if event.kind == SessionEventKind.transcript:
                        payload = event.payload
                        if isinstance(payload, dict) and payload.get("role") == "agent":
                            content = payload.get("content", "")
                            if content and content.strip():
                                agent_chunks.append(content)

                    elif event.kind == SessionEventKind.done:
                        # ResultMessage carries the complete final text
                        if isinstance(event.payload, dict):
                            r = event.payload.get("result", "")
                            if r and r.strip():
                                result_text = r
                        break

                    elif event.kind == SessionEventKind.error:
                        msg = ""
                        if isinstance(event.payload, dict):
                            msg = event.payload.get("message", "")
                        log.warning("preflight_curator.session_error", error=msg)
                        break
        except TimeoutError:
            log.warning(
                "preflight_curator.session_timeout",
                timeout_s=_SESSION_TIMEOUT_S,
            )
            try:
                await self._adapter.abort_session(session_id)
            except Exception:
                pass
            # Return whatever the agent produced so far
        except Exception:
            log.warning("preflight_curator.stream_failed", exc_info=True)
            try:
                await self._adapter.abort_session(session_id)
            except Exception:
                pass
            raise

        elapsed_ms = (time.monotonic() - t0) * 1000
        # Prefer the done-event result (complete text); fall back to
        # the last agent transcript chunk (most likely the final brief).
        brief = result_text or (agent_chunks[-1] if agent_chunks else "")
        log.debug(
            "preflight_curator.session_completed",
            elapsed_ms=round(elapsed_ms, 1),
            result_len=len(brief),
        )

        return brief.strip()
