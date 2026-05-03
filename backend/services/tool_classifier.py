"""Tool classification for cost analytics.

Maps tool names (as reported by Copilot/Claude SDKs) to normalized
categories and extracts the primary target (file path, command name)
from tool arguments.
"""

from __future__ import annotations

import re

from backend.services.parsing_utils import ensure_dict

TOOL_CATEGORIES: dict[str, str] = {
    # file_read — reading file contents
    "read_file": "file_read",
    "view": "file_read",
    "cat": "file_read",
    "Read": "file_read",
    "readFile": "file_read",
    "open_file": "file_read",
    "get_file_contents": "file_read",
    "TodoRead": "file_read",
    "NotebookRead": "file_read",
    "view_image": "file_read",
    # file_write — creating or editing files
    "edit_file": "file_write",
    "edit": "file_write",
    "create_file": "file_write",
    "write_file": "file_write",
    "write": "file_write",
    "Write": "file_write",
    "Edit": "file_write",
    "MultiEdit": "file_write",
    "editFile": "file_write",
    "create": "file_write",
    "replace_string_in_file": "file_write",
    "multi_replace_string_in_file": "file_write",
    "str_replace_based_edit_tool": "file_write",
    "str_replace_editor": "file_write",
    "insert_edit_into_file": "file_write",
    "apply_patch": "file_write",
    "create_or_update_file": "file_write",
    "delete_file": "file_write",
    "create_directory": "file_write",
    "TodoWrite": "file_write",
    "NotebookEdit": "file_write",
    # file_search — searching and navigating the codebase
    "grep": "file_search",
    "grep_search": "file_search",
    "Grep": "file_search",
    "glob": "file_search",
    "Glob": "file_search",
    "find": "file_search",
    "rg": "file_search",
    "ripgrep": "file_search",
    "search": "file_search",
    "semantic_search": "file_search",
    "codeSearch": "file_search",
    "listDir": "file_search",
    "list_dir": "file_search",
    "LS": "file_search",
    "file_search": "file_search",
    "vscode_listCodeUsages": "file_search",
    "tool_search_tool_regex": "file_search",
    "ToolSearch": "file_search",
    "ListMcpResources": "file_search",
    "ListMcpResourceTemplates": "file_search",
    # shell — running commands in a terminal
    "bash": "shell",
    "Bash": "shell",
    "terminal": "shell",
    "exec": "shell",
    "runCommand": "shell",
    "run_in_terminal": "shell",
    "get_terminal_output": "shell",
    "read_bash": "shell",
    "write_bash": "shell",
    "stop_bash": "shell",
    "sql": "bookkeeping",
    # git — version control operations (split read vs write)
    "git_diff": "git_read",
    "git_status": "git_read",
    "git_log": "git_read",
    "get_changed_files": "git_read",
    "git_commit": "git_write",
    "git_push": "git_write",
    "git_add": "git_write",
    "git_checkout": "git_write",
    "git_merge": "git_write",
    "git_rebase": "git_write",
    "git_reset": "git_write",
    "git_stash": "git_write",
    # browser — web fetches and browsing
    "fetch_url": "browser",
    "web_search": "browser",
    "web_fetch": "browser",
    "WebFetch": "browser",
    "WebSearch": "browser",
    "fetch_webpage": "browser",
    "ReadMcpResource": "browser",
    # agent — delegation to sub-agents
    "task": "agent",
    "subagent": "agent",
    "Agent": "agent",
    "runSubagent": "agent",
    "search_subagent": "agent",
    "skill": "agent",
    "Task": "agent",
    "read_agent": "agent",
    "list_agents": "agent",
    # thinking — agent reasoning / planning
    "Think": "thinking",
    "Computer": "thinking",
    # bookkeeping — agent-internal housekeeping
    "report_intent": "bookkeeping",
    "store_memory": "bookkeeping",
    "manage_todo_list": "bookkeeping",
    "memory": "bookkeeping",
}


_CATEGORY_TO_ACTIVITY: dict[str, str] = {
    "file_write": "implementation",
    "git_write": "git_ops",
    "git_read": "git_ops",
    "file_read": "investigation",
    "file_search": "investigation",
    "browser": "investigation",
    "shell": "investigation",
    "agent": "delegation",
    "thinking": "reasoning",
    "bookkeeping": "overhead",
    "other": "overhead",
}

# ---------------------------------------------------------------------------
# Shell command → activity refinement
#
# When we know the actual command a shell tool executed, we can assign a
# more precise activity than the generic "investigation" default.
# ---------------------------------------------------------------------------

_RE_SHELL_TEST = re.compile(
    r"\b(pytest|vitest|jest|mocha|npm\s+test|npx\s+vitest|npx\s+jest|"
    r"cargo\s+test|go\s+test|rspec|phpunit|unittest|npm\s+run\s+test)\b",
    re.IGNORECASE,
)
_RE_SHELL_GIT_WRITE = re.compile(
    r"\bgit\s+(add|commit|push|merge|rebase|checkout|cherry-pick|stash|tag|reset)\b",
    re.IGNORECASE,
)
_RE_SHELL_GIT_READ = re.compile(
    r"\bgit\s+(diff|log|status|show|blame|branch)\b",
    re.IGNORECASE,
)
_RE_SHELL_SETUP = re.compile(
    r"\b(uv\s+sync|uv\s+add|pip\s+install|npm\s+install|npm\s+ci|"
    r"yarn\s+install|cargo\s+build|make\s+build|docker|deploy|"
    r"brew\s+install|apt\s+install|apt-get\s+install)\b",
    re.IGNORECASE,
)
_RE_SHELL_INVESTIGATE = re.compile(
    r"\b(find|ls|cat|head|tail|wc|tree|du|file|grep|awk|sed|diff|less|more|stat|strings)\b",
    re.IGNORECASE,
)


def classify_shell_command(cmd: str) -> str:
    """Classify a shell command string into an activity.

    Returns one of: verification, git_ops, setup, investigation, shell_other.
    """
    if _RE_SHELL_TEST.search(cmd):
        return "verification"
    if _RE_SHELL_GIT_WRITE.search(cmd):
        return "git_ops"
    if _RE_SHELL_SETUP.search(cmd):
        return "setup"
    if _RE_SHELL_GIT_READ.search(cmd):
        return "git_ops"
    if _RE_SHELL_INVESTIGATE.search(cmd):
        return "investigation"
    return "shell_other"


def classify_tool(tool_name: str) -> str:
    """Return the normalized category for a tool name.

    For MCP-style names like ``server/tool``, tries the full name first,
    then falls back to just the tool part after the slash.
    """
    cat = TOOL_CATEGORIES.get(tool_name)
    if cat:
        return cat
    if "/" in tool_name:
        return TOOL_CATEGORIES.get(tool_name.rsplit("/", 1)[-1], "other")
    return "other"


def classify_tool_activity(tool_name: str, tool_args_json: str | None = None) -> str:
    """Return the high-level activity bucket for a tool invocation.

    For shell tools, inspects the actual command from tool_args_json to
    assign a precise activity (verification, git_ops, setup, etc.)
    instead of the generic 'investigation' fallback.
    """
    category = classify_tool(tool_name)
    if category == "shell" and tool_args_json:
        parsed = ensure_dict(tool_args_json)
        if parsed:
            cmd = str(parsed.get("command", "") or parsed.get("cmd", "") or parsed.get("input", ""))
            if cmd:
                shell_activity = classify_shell_command(cmd)
                if shell_activity != "shell_other":
                    return shell_activity
    return _CATEGORY_TO_ACTIVITY.get(category, "overhead")


def extract_tool_target(tool_name: str, tool_args: str | None) -> str:
    """Extract the primary target from tool arguments.

    Returns a short identifier suitable for grouping — e.g. a file path
    for file operations, or the command prefix for shell commands.
    """
    if not tool_args:
        return ""

    parsed = ensure_dict(tool_args)
    if parsed is None:
        return ""

    category = classify_tool(tool_name)

    if category in ("file_read", "file_write"):
        return str(
            parsed.get("path", "")
            or parsed.get("file", "")
            or parsed.get("file_path", "")
            or parsed.get("filePath", "")
        )

    if category == "file_search":
        return str(parsed.get("pattern", "") or parsed.get("query", ""))

    if category == "shell":
        cmd = str(parsed.get("command", "") or parsed.get("cmd", ""))
        # Return first word of command as the target
        return cmd.split()[0] if cmd else ""

    if category in ("git_read", "git_write"):
        return str(parsed.get("path", "") or parsed.get("file", ""))

    if category == "browser":
        return str(parsed.get("url", ""))

    return ""


def extract_file_paths(tool_name: str, tool_args: str | None) -> list[str]:
    """Extract all file paths referenced in tool arguments."""
    if not tool_args:
        return []

    parsed = ensure_dict(tool_args)
    if parsed is None:
        return []

    paths: list[str] = []
    for key in ("path", "file", "file_path", "filePath", "filename"):
        val = parsed.get(key)
        if val and isinstance(val, str):
            paths.append(val)

    # Some tools have a list of files
    for key in ("files", "paths"):
        val = parsed.get(key)
        if isinstance(val, list):
            paths.extend(str(v) for v in val if v)

    return paths
