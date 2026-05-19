"""Native tool wrappers for CodeRecon — agent tool provisioning (§8).

Builds in-process tool definitions for both the Claude Code SDK and
Copilot SDK.  Each tool handler delegates to ``CodeReconService``
methods.  RuntimeService calls ``build_coderecon_tools()`` at job start
and attaches the result to ``SessionConfig`` so each adapter can inject
the tools natively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.services.coderecon.coderecon_service import CodeReconService

log = structlog.get_logger(__name__)

# ── System prompt fragment (§8.5) ──

_TOOL_GUIDANCE_STANDARD = """\
## Structural Tools

You have structural analysis tools for this repository. Use them.

### When to use what

- **recon_impact** — Before modifying a function/class. Shows all callers
  and dependents. Call this before any signature change.
- **checkpoint** — After completing a logical unit of work. Pass the list
  of changed file paths. This runs lint + tests + structural diff.
- **blast_radius** — After identifying changed files. Shows which tests
  cover those files and where coverage gaps exist.

### Rules

1. Always call recon_impact before changing a function signature.
2. If checkpoint fails, read its output. Fix the issue. Call checkpoint
   again.
3. Use blast_radius to verify test coverage before marking work complete.
"""

_TOOL_GUIDANCE_FULL = (
    _TOOL_GUIDANCE_STANDARD
    + """\

### Additional tools (full tier)

- **graph_communities** — When working across modules. Shows which files
  cluster together.
- **graph_cycles** — After adding new imports. Detects circular deps.
- **recon_scout** — Full codebase narrative briefing.
- **semantic_diff** — Structural change summary between two states.
"""
)


# ── Tool schemas (JSON Schema for each tool) ──

_TOOL_DEFS: dict[str, dict[str, Any]] = {
    "recon_impact": {
        "description": "Reference/caller analysis for a symbol. Call before changing any function signature.",
        "schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Symbol or file path to analyse."},
                "justification": {"type": "string", "description": "Why you need this analysis."},
            },
            "required": ["target", "justification"],
        },
    },
    "recon_scout": {
        "description": (
            "Full codebase narrative briefing \u2014 structure, PageRank, communities."
            " Use scope to zoom into a specific module/directory."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": (
                        "Optional directory or module path (relative to repo root)"
                        " to zoom into, e.g. 'backend/services'."
                    ),
                },
            },
        },
    },
    "checkpoint": {
        "description": (
            "Lint + test + structural diff pipeline for changed files. "
            "Pass changed_files to verify structural integrity."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths (relative to repo root) of changed files.",
                },
                "diff": {"type": "boolean", "description": "Include semantic diff phase (default: true)."},
                "lint": {"type": "boolean", "description": "Run linting (default: true)."},
                "tests": {"type": "boolean", "description": "Run affected tests (default: true)."},
            },
            "required": ["changed_files"],
        },
    },
    "graph_communities": {
        "description": "Module community detection (Louvain). Shows which files cluster together.",
        "schema": {"type": "object", "properties": {}},
    },
    "graph_cycles": {
        "description": "Circular dependency detection (Tarjan). Detects cycles you may have introduced.",
        "schema": {"type": "object", "properties": {}},
    },
    "semantic_diff": {
        "description": "Structural change summary between two states.",
        "schema": {
            "type": "object",
            "properties": {
                "base": {"type": "string", "description": "Base ref (default: HEAD)."},
                "target": {"type": "string", "description": "Target ref (default: working tree)."},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit diff to these paths.",
                },
            },
        },
    },
    "blast_radius": {
        "description": (
            "Coverage-aware blast radius analysis. Given changed files, returns "
            "affected test candidates ranked by confidence, plus coverage gaps "
            "(files with no test coverage)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths (relative to repo root) of changed files.",
                },
                "max_hops": {
                    "type": "integer",
                    "description": "Maximum graph hops for reachability (default: 2).",
                },
            },
            "required": ["changed_files"],
        },
    },
}


@dataclass
class CodeReconToolKit:
    """Container for provisioned tools + system prompt fragment."""

    # Claude SDK: in-process MCP server config (McpSdkServerConfig)
    claude_mcp_server: Any | None = None

    # Copilot SDK: list of Tool objects
    copilot_tools: list[Any] = field(default_factory=list)

    # System prompt fragment to inject
    system_prompt: str = ""

    # Tool names that should be auto-allowed (no permission prompt)
    allowed_tool_names: list[str] = field(default_factory=list)


def _serialize_result(obj: Any) -> str:
    """Best-effort JSON serialization of SDK result objects."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return json.dumps(obj, default=str, indent=2)
    if isinstance(obj, list):
        return json.dumps([_item_to_dict(x) for x in obj], default=str, indent=2)
    # SDK result objects typically have __dict__ or dataclass fields
    if hasattr(obj, "__dict__"):
        return json.dumps(obj.__dict__, default=str, indent=2)
    return str(obj)


def _item_to_dict(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def _resolve_tier(tier: str) -> set[str]:
    """Return tool names allowed for a tier."""
    minimal = {"recon_impact"}
    standard = minimal | {"checkpoint", "blast_radius"}
    # Read-only structural tools for the preflight curator agent.
    # Must match the tools listed in the preflight system prompt.
    preflight = {"recon_scout", "recon_impact", "recon", "recon_map", "scaffold"}
    if tier == "minimal":
        return minimal
    if tier == "standard":
        return standard
    if tier == "preflight":
        return preflight
    # full — all tools
    return set(_TOOL_DEFS.keys())


def build_coderecon_tools(
    service: CodeReconService,
    repo: str,
    worktree: str,
    tier: str = "standard",
) -> CodeReconToolKit:
    """Build native tool wrappers for both Claude and Copilot SDKs.

    Returns a ``CodeReconToolKit`` that RuntimeService attaches to
    ``SessionConfig``.  Each adapter then extracts the relevant objects
    and passes them to the SDK natively.
    """
    allowed_names = _resolve_tier(tier)

    # ── Build dispatch handlers ──

    async def _dispatch(tool_name: str, args: dict[str, Any]) -> str:
        """Central dispatcher — calls the appropriate CodeReconService method."""
        try:
            if tool_name == "recon_impact":
                result = await service.recon_impact(
                    repo,
                    args.get("target", ""),
                    args.get("justification", ""),
                    worktree=worktree,
                )
                return _serialize_result(result)
            if tool_name == "recon_scout":
                result = await service.scout(
                    repo,
                    scope=args.get("scope"),
                    worktree=worktree,
                )
                return _serialize_result(result)
            if tool_name == "checkpoint":
                result = await service.checkpoint(
                    repo,
                    args.get("changed_files", []),
                    diff=args.get("diff", True),
                    lint=args.get("lint", True),
                    tests=args.get("tests", True),
                    worktree=worktree,
                )
                return _serialize_result(result)
            if tool_name == "graph_communities":
                result = await service.graph_communities(repo, worktree=worktree)
                return _serialize_result(result)
            if tool_name == "graph_cycles":
                result = await service.graph_cycles(repo, worktree=worktree)
                return _serialize_result(result)
            if tool_name == "semantic_diff":
                result = await service.semantic_diff(
                    repo,
                    base=args.get("base", "HEAD"),
                    target=args.get("target"),
                    paths=args.get("paths"),
                    worktree=worktree,
                )
                return _serialize_result(result)
            if tool_name == "blast_radius":
                max_hops = min(args.get("max_hops", 2), 5)
                result = await service.blast_radius(
                    repo,
                    args.get("changed_files", []),
                    worktree=worktree,
                    max_hops=max_hops,
                )
                return _serialize_result(result)

            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as exc:
            log.warning("coderecon_tool_error", tool=tool_name, error=str(exc))
            return json.dumps({"error": str(exc)})

    # ── Build Claude SDK tools ──

    claude_server = None
    claude_allowed: list[str] = []
    try:
        from claude_code_sdk import create_sdk_mcp_server
        from claude_code_sdk import tool as claude_tool

        claude_tools = []
        for name in sorted(allowed_names & set(_TOOL_DEFS.keys())):
            defn = _TOOL_DEFS[name]

            # Create handler closure with captured tool name
            def _make_claude_handler(tool_name: str) -> Any:  # noqa: ANN202
                async def handler(args: dict[str, Any]) -> dict[str, Any]:
                    text = await _dispatch(tool_name, args)
                    return {"content": [{"type": "text", "text": text}]}

                return handler

            t = claude_tool(name, defn["description"], defn["schema"])(_make_claude_handler(name))
            claude_tools.append(t)
            claude_allowed.append(f"mcp__coderecon__{name}")

        if claude_tools:
            claude_server = create_sdk_mcp_server(
                name="coderecon",
                version="1.0.0",
                tools=claude_tools,
            )
    except ImportError:
        log.debug("claude_code_sdk not available, skipping Claude tool build")

    # ── Build Copilot SDK tools ──

    copilot_tools_list: list[Any] = []
    try:
        from copilot.session import Tool as CopilotTool  # type: ignore[attr-defined]
        from copilot.tools import ToolInvocation, ToolResult

        for name in sorted(allowed_names & set(_TOOL_DEFS.keys())):
            defn = _TOOL_DEFS[name]

            def _make_copilot_handler(tool_name: str) -> Any:  # noqa: ANN202
                async def handler(invocation: ToolInvocation) -> ToolResult:
                    args = invocation.arguments if isinstance(invocation.arguments, dict) else {}
                    text = await _dispatch(tool_name, args)
                    return ToolResult(text_result_for_llm=text)

                return handler

            copilot_tool = CopilotTool(
                name=name,
                description=defn["description"],
                handler=_make_copilot_handler(name),
                parameters=defn["schema"],
            )
            copilot_tools_list.append(copilot_tool)
    except ImportError:
        log.debug("copilot SDK not available, skipping Copilot tool build")

    # ── System prompt ──

    if tier == "preflight":
        prompt = ""  # Preflight curator has its own system prompt
    elif tier == "full":
        prompt = _TOOL_GUIDANCE_FULL
    else:
        prompt = _TOOL_GUIDANCE_STANDARD

    return CodeReconToolKit(
        claude_mcp_server=claude_server,
        copilot_tools=copilot_tools_list,
        system_prompt=prompt,
        allowed_tool_names=claude_allowed,
    )
