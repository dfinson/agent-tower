"""Lightweight policy router for agentic sidecar sessions.

Unlike the main agent's ``PolicyRouter`` this does **not** involve an LLM
monitor, human approval, or trust grants.  It enforces a pure
allowlist/blocklist: if the tool or command is not explicitly permitted by
the ``SidecarToolPolicy``, the request is denied immediately.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.sidecar.dispatcher import SidecarToolPolicy

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tool → category mapping
# ---------------------------------------------------------------------------

# Tools classified as read-only file access.
_READ_TOOLS: frozenset[str] = frozenset({
    "read_file", "read", "Read", "view", "view_image", "cat", "readFile",
    "open_file", "list_dir", "list_directory",
})

# Tools classified as search/discovery.
_SEARCH_TOOLS: frozenset[str] = frozenset({
    "grep_search", "file_search", "semantic_search", "search", "find",
    "ripgrep", "SearchFiles", "GrepTool",
})

# Tools classified as file-write operations.
_WRITE_TOOLS: frozenset[str] = frozenset({
    "create_file", "create", "edit_file", "edit", "Edit", "MultiEdit",
    "write", "Write", "write_file", "replace_string_in_file",
    "multi_replace_string_in_file", "str_replace_based_edit_tool",
    "str_replace_editor", "insert_edit_into_file", "apply_patch",
    "delete_file",
})

# Tools classified as shell execution.
_SHELL_TOOLS: frozenset[str] = frozenset({
    "Bash", "bash", "shell", "run_in_terminal", "execute_command",
    "run_command", "terminal",
})


def _classify_tool(tool_name: str) -> str:
    """Return the canonical category for a tool name."""
    if tool_name in _READ_TOOLS:
        return "read"
    if tool_name in _SEARCH_TOOLS:
        return "search"
    if tool_name in _WRITE_TOOLS:
        return "write"
    if tool_name in _SHELL_TOOLS:
        return "shell"
    # MCP tools are prefixed with the server name (e.g. "mcp_github_…").
    if tool_name.startswith("mcp_"):
        return "mcp"
    # Unknown tools default to "write" (deny-by-default for unknowns).
    log.debug("tool_classified_as_write", tool_name=tool_name)
    return "write"


def _extract_mcp_server(tool_name: str) -> str | None:
    """Extract the MCP server name from an MCP tool name like ``mcp_github_list_issues``."""
    if not tool_name.startswith("mcp_"):
        return None
    parts = tool_name.split("_", 2)
    return parts[1] if len(parts) >= 2 else None


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SidecarDecision:
    proceed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class SidecarPolicyRouter:
    """Pure allowlist/blocklist policy enforcement for agentic sidecars."""

    @staticmethod
    def evaluate(
        tool_name: str,
        tool_input: dict[str, object] | None,
        policy: SidecarToolPolicy,
        worktree_path: str | None = None,
    ) -> SidecarDecision:
        """Decide whether a sidecar tool call is allowed.

        Returns ``SidecarDecision(proceed=True)`` if allowed, or
        ``SidecarDecision(proceed=False, reason=...)`` if denied.
        """
        # 1. Explicit blocklist — always wins.
        if tool_name in policy.blocked_tools:
            return SidecarDecision(proceed=False, reason=f"tool '{tool_name}' is blocked")

        # 2. Category check.
        category = _classify_tool(tool_name)

        # Shell tools need finer-grained classification.
        if category == "shell":
            shell_category = "shell_readonly" if policy.shell_readonly else "shell_write"
            if shell_category not in policy.allowed_categories:
                return SidecarDecision(
                    proceed=False,
                    reason=f"shell access (category '{shell_category}') not allowed",
                )
            # Shell allowlist enforcement.
            if policy.shell_allowlist:
                command = str((tool_input or {}).get("command", ""))
                if not _matches_shell_allowlist(command, policy.shell_allowlist):
                    return SidecarDecision(
                        proceed=False,
                        reason=f"command not in shell allowlist",
                    )
        elif category == "mcp":
            if "mcp" not in policy.allowed_categories:
                return SidecarDecision(proceed=False, reason="MCP tool access not allowed")
            server = _extract_mcp_server(tool_name)
            if server and policy.mcp_servers and server not in policy.mcp_servers:
                return SidecarDecision(
                    proceed=False,
                    reason=f"MCP server '{server}' not in allowed servers",
                )
        else:
            if category not in policy.allowed_categories:
                return SidecarDecision(
                    proceed=False,
                    reason=f"tool category '{category}' not allowed",
                )

        # 3. Path scope check (for file operations).
        if category in ("read", "write") and worktree_path:
            path_arg = _extract_path(tool_input)
            if path_arg and not _within_scope(path_arg, worktree_path):
                return SidecarDecision(
                    proceed=False,
                    reason="path outside allowed scope",
                )

        return SidecarDecision(proceed=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches_shell_allowlist(command: str, allowlist: tuple[str, ...]) -> bool:
    """Check if *command* matches any allowed command prefix.

    Requires an exact match or the prefix followed by a space (so ``pytest``
    matches ``pytest tests/`` but not ``pytest_coverage``).
    """
    stripped = command.strip()
    for prefix in allowlist:
        if stripped == prefix or stripped.startswith(prefix + " "):
            return True
    return False


def _extract_path(tool_input: dict[str, object] | None) -> str | None:
    """Best-effort extraction of a file path from tool input."""
    if not tool_input:
        return None
    for key in ("filePath", "file_path", "path", "file", "uri"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _within_scope(path: str, worktree_path: str) -> bool:
    """Check that *path* is inside the worktree."""
    try:
        resolved = os.path.realpath(path)
        scope = os.path.realpath(worktree_path)
        return resolved.startswith(scope + os.sep) or resolved == scope
    except (ValueError, OSError):
        log.warning("path_scope_check_failed", path=path, worktree=worktree_path, exc_info=True)
        return False
