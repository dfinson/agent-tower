"""Deterministic per-tool display formatters.

Each formatter extracts a short human-readable label from a tool's
arguments and (optionally) its result, avoiding LLM calls entirely.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# Type alias for deserialized tool argument dicts (JSON-parsed tool_args).
ToolArgs = dict[str, Any]


def _truncate(s: str, max_len: int = 60) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _parse_args(tool_args: str | None) -> ToolArgs:
    if not tool_args:
        return {}
    try:
        parsed = json.loads(tool_args)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_issue_from_json(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("error", "message", "detail", "details", "stderr"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            found = _extract_issue_from_json(nested)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _extract_issue_from_json(item)
            if found:
                return found
    return None


_WORKTREE_MARKER = "/.codeplane-worktrees/"


def _short_path(path: str) -> str:
    """Return a display-friendly path.

    For paths inside a CodePlane worktree, strips the absolute prefix up to
    and including ``/.codeplane-worktrees/``, yielding ``…/<worktree>/<rest>``.
    Falls back to the last two components for other absolute paths.
    """
    idx = path.find(_WORKTREE_MARKER)
    if idx != -1:
        return "…/" + path[idx + len(_WORKTREE_MARKER) :]
    p = PurePosixPath(path)
    parts = p.parts
    if len(parts) <= 2:
        return str(p)
    return str(PurePosixPath(*parts[-2:]))


def _trim_worktree_paths(text: str) -> str:
    """Strip worktree path prefixes from an arbitrary string (e.g. a shell command).

    Matches the absolute path up to and including ``/.codeplane-worktrees/``,
    anchoring on the leading ``/`` so that option names like ``--flag=`` are
    preserved:

    ``cat /home/user/.codeplane-worktrees/my-branch/src/f.py``
    → ``cat …/my-branch/src/f.py``

    ``--path=/home/user/.codeplane-worktrees/branch/f.py``
    → ``--path=…/branch/f.py``
    """
    return re.sub(r"/[^\s]*\.codeplane-worktrees/", "…/", text)


# -- Formatter / hint factories for common patterns --------------------------


@dataclass(frozen=True, slots=True)
class _FmtSpec:
    """Declarative spec for a simple single-arg formatter."""

    keys: tuple[str, ...]  # arg keys to try, first non-empty wins
    prefix: str  # label prefix (e.g. "Create", "Grep")
    fallback: str  # returned when no arg found
    use_path: bool = False  # apply _short_path to the value
    trim_paths: bool = False  # apply _trim_worktree_paths (for command strings)
    truncate: int = 0  # apply _truncate (0 = no truncation)
    quote: bool = False  # wrap value in double quotes
    separator: str = " "  # between prefix and value


def _build_formatter(spec: _FmtSpec, no_truncate: bool = False) -> Callable[[ToolArgs], str]:
    """Build a formatter function from a declarative spec.

    When *no_truncate* is True the ``truncate`` field on *spec* is ignored,
    yielding a display string that is only path-trimmed, not length-capped.
    """

    def fmt(args: ToolArgs) -> str:
        for k in spec.keys:
            v = args.get(k, "")
            if v:
                display = _short_path(v) if spec.use_path else v
                if spec.trim_paths:
                    display = _trim_worktree_paths(display)
                if spec.truncate and not no_truncate:
                    display = _truncate(display, spec.truncate)
                if spec.quote:
                    display = f'"{display}"'
                return f"{spec.prefix}{spec.separator}{display}"
        return spec.fallback

    return fmt


def _count_hint(unit: str, *, empty: str = "") -> Callable[[str, bool], str]:
    """Factory for hints like '→ 12 matches' / '→ no matches'."""

    def hint(result: str, success: bool) -> str:
        n = _count_lines(result)
        return f"→ {n} {unit}" if n else (empty or f"→ no {unit}")

    return hint


def _static_hint(ok: str, fail: str = "→ FAIL") -> Callable[[str, bool], str]:
    """Factory for hints that return a fixed string."""

    def hint(result: str, success: bool) -> str:
        return ok if success else fail

    return hint


# Declarative specs for simple formatters
_SIMPLE_SPECS: dict[str, _FmtSpec] = {
    # ---- Copilot / generic snake_case tools ---------------------------------
    "bash": _FmtSpec(("command",), "$", "bash", truncate=55, trim_paths=True),
    "run_in_terminal": _FmtSpec(("command",), "$", "Run command", truncate=55, trim_paths=True),
    "create_file": _FmtSpec(("filePath", "file_path"), "Create", "Create file", use_path=True),
    "replace_string_in_file": _FmtSpec(("filePath", "file_path"), "Edit", "Edit file", use_path=True),
    "edit": _FmtSpec(("path", "file_path"), "Edit", "Edit file", use_path=True),
    "grep_search": _FmtSpec(("query", "pattern"), "Grep:", "Grep search", truncate=40, quote=True),
    "semantic_search": _FmtSpec(("query",), "Search:", "Semantic search", truncate=40, quote=True),
    "file_search": _FmtSpec(("query", "pattern"), "Find:", "File search", truncate=40, quote=True),
    "list_dir": _FmtSpec(("path", "directory"), "List", "List directory", use_path=True),
    "runSubagent": _FmtSpec(("description",), "Subagent:", "Run subagent", truncate=50),
    "search_subagent": _FmtSpec(("description", "query"), "Search agent:", "Search agent", truncate=45),
    "get_terminal_output": _FmtSpec(("id",), "Read terminal", "Read terminal"),
    "tool_search_tool_regex": _FmtSpec(("pattern",), "Find tools:", "Find tools", truncate=40, quote=True),
    "vscode_listCodeUsages": _FmtSpec(("symbol", "query"), "Usages:", "Find usages", truncate=45),
    "glob": _FmtSpec(("pattern",), "Glob:", "Glob", truncate=50),
    "grep": _FmtSpec(("pattern", "query"), "Grep:", "Grep", truncate=40, quote=True),
    "write": _FmtSpec(("path",), "Write", "Write file", use_path=True),
    "str_replace_based_edit_tool": _FmtSpec(("path",), "Edit", "Edit file", use_path=True),
    "str_replace_editor": _FmtSpec(("path",), "Edit", "Edit file", use_path=True),
    # ---- Copilot-only tools missing from original registry ------------------
    "web_search": _FmtSpec(("query",), "Search:", "Web search", truncate=40, quote=True),
    "insert_edit_into_file": _FmtSpec(("filePath", "file_path"), "Edit", "Edit file", use_path=True),
    "get_changed_files": _FmtSpec((), "", "Get changed files"),
    "run_vs_code_task": _FmtSpec(("task",), "Run task:", "Run task", truncate=40),
    "open_file": _FmtSpec(("filePath", "file_path"), "Open", "Open file", use_path=True),
    "skill": _FmtSpec(("skill",), "Skill:", "Run skill", truncate=50),
    # ---- Claude SDK PascalCase tools ----------------------------------------
    "Bash": _FmtSpec(("command",), "$", "bash", truncate=55, trim_paths=True),
    "Glob": _FmtSpec(("pattern",), "Glob:", "Glob", truncate=50),
    "LS": _FmtSpec(("path",), "List", "List directory", use_path=True),
    "Task": _FmtSpec(("description",), "Task:", "Run task", truncate=50),
    "WebSearch": _FmtSpec(("query",), "Search:", "Web search", truncate=40, quote=True),
    "TodoRead": _FmtSpec((), "", "Read todo list"),
    "TodoWrite": _FmtSpec((), "", "Update todo list"),
    "Think": _FmtSpec(("thought",), "Think:", "Think", truncate=55),
    "NotebookRead": _FmtSpec(("notebook_path",), "Read", "Read notebook", use_path=True),
    "NotebookEdit": _FmtSpec(("notebook_path",), "Edit", "Edit notebook", use_path=True),
    "ListMcpResourceTemplates": _FmtSpec((), "", "List MCP resource templates"),
    "ListMcpResources": _FmtSpec((), "", "List MCP resources"),
    # Complex arg shapes (file_path first, path fallback) — kept here to
    # co-locate with related PascalCase entries; registered via _build_formatter.
    "Write": _FmtSpec(("file_path", "path"), "Write", "Write file", use_path=True),
    "Edit": _FmtSpec(("file_path", "path"), "Edit", "Edit file", use_path=True),
    "Grep": _FmtSpec(("pattern",), "Grep:", "Grep", truncate=40, quote=True),
    "Sql": _FmtSpec(("query",), "SQL:", "SQL query", truncate=55, quote=True),
    # ---- Additional aliases / less common tools ----------------------------
    "delete_file": _FmtSpec(("filePath", "file_path", "path"), "Delete", "Delete file", use_path=True),
    "edit_file": _FmtSpec(("filePath", "file_path"), "Edit", "Edit file", use_path=True),
    "write_file": _FmtSpec(("filePath", "file_path", "path"), "Write", "Write file", use_path=True),
    "create": _FmtSpec(("path", "file_path"), "Create", "Create file", use_path=True),
    "create_or_update_file": _FmtSpec(("path", "file_path"), "Create/update", "Create or update file", use_path=True),
    "apply_patch": _FmtSpec(("patch",), "Apply patch", "Apply patch", truncate=40),
    "view_image": _FmtSpec(("filePath", "file_path"), "View image", "View image", use_path=True),
    "run_vscode_command": _FmtSpec(("command",), "VS Code:", "VS Code command", truncate=40),
    "git_diff": _FmtSpec(("path",), "Git diff", "Git diff", use_path=True),
    "git_status": _FmtSpec((), "", "Git status"),
    "git_log": _FmtSpec(("path",), "Git log", "Git log", use_path=True),
    "readFile": _FmtSpec(("filePath", "file_path"), "Read", "Read file", use_path=True),
    "editFile": _FmtSpec(("filePath", "file_path"), "Edit", "Edit file", use_path=True),
    "listDir": _FmtSpec(("path",), "List", "List directory", use_path=True),
    "Agent": _FmtSpec(("description",), "Agent:", "Run agent", truncate=50),
    # ---- Legacy / rare aliases (humanize_tool_name fallback is fine) --------
    "cat": _FmtSpec(("path",), "Read", "Read file", use_path=True),
    "find": _FmtSpec(("pattern", "path"), "Find:", "Find", truncate=40),
    "rg": _FmtSpec(("pattern",), "Ripgrep:", "Ripgrep", truncate=40, quote=True),
    "fetch_url": _FmtSpec(("url",), "Fetch:", "Fetch URL", truncate=50),
    "web_fetch": _FmtSpec(("url",), "Fetch:", "Fetch URL", truncate=50),
    "WebFetch": _FmtSpec(("url",), "Fetch:", "Fetch URL", truncate=50),
}


# -- Complex formatters (not reducible to _FmtSpec) --------------------------


def _fmt_multi_edit(args: ToolArgs) -> str:
    """Formatter for Claude SDK's MultiEdit tool (edits: [{file_path, ...}])."""
    edits = args.get("edits", [])
    paths: set[str] = set()
    for e in edits:
        if isinstance(e, dict):
            p = e.get("file_path", e.get("path", ""))
            if p:
                paths.add(_short_path(p))
    if paths:
        listed = ", ".join(sorted(paths)[:3])
        suffix = "…" if len(paths) > 3 else ""
        return f"Edit {listed}{suffix}"
    count = len(edits) if isinstance(edits, list) else 0
    return f"Edit {count} locations"


def _fmt_computer(args: ToolArgs) -> str:
    """Formatter for Claude SDK's Computer tool."""
    action = str(args.get("action", ""))
    if action == "screenshot":
        return "Take screenshot"
    if action == "key":
        key = args.get("text", "")
        return f"Key: {_truncate(key, 20)}" if key else "Press key"
    if action == "type":
        text = _truncate(args.get("text", ""), 30)
        return f"Type: {text}" if text else "Type text"
    if action in ("mouse_move", "left_click", "right_click", "double_click"):
        coord = args.get("coordinate", [])
        label = action.replace("_", " ").title()
        if coord and len(coord) >= 2:
            return f"{label} ({coord[0]}, {coord[1]})"
        return label
    if action:
        return f"Computer: {_truncate(action, 30)}"
    return "Computer action"


def _fmt_read_mcp_resource(args: ToolArgs) -> str:
    """Formatter for Claude SDK's ReadMcpResource tool."""
    uri = args.get("uri", "")
    if uri:
        return f"Read MCP: {_truncate(uri, 50)}"
    server = args.get("server_name", "")
    return f"Read MCP resource ({server})" if server else "Read MCP resource"


def _fmt_read_file(args: ToolArgs) -> str:
    path = args.get("filePath", args.get("file_path", ""))
    if not path:
        return "Read file"
    short = _short_path(path)
    start = args.get("startLine", args.get("start_line"))
    end = args.get("endLine", args.get("end_line"))
    if start and end:
        return f"Read {short}:{start}-{end}"
    return f"Read {short}"


def _fmt_multi_replace(args: ToolArgs) -> str:
    replacements = args.get("replacements", [])
    paths: set[str] = set()
    for r in replacements:
        if isinstance(r, dict):
            p = r.get("filePath", r.get("file_path", ""))
            if p:
                paths.add(_short_path(p))
    if paths:
        listed = ", ".join(sorted(paths)[:3])
        suffix = "…" if len(paths) > 3 else ""
        return f"Edit {listed}{suffix}"
    count = len(replacements) if isinstance(replacements, list) else 0
    return f"Edit {count} locations"


def _fmt_memory(args: ToolArgs) -> str:
    cmd = args.get("command", "")
    path = args.get("path", "")
    if cmd and path:
        return f"Memory {cmd}: {_short_path(path)}"
    return f"Memory {cmd}" if cmd else "Memory"


def _fmt_manage_todo(args: ToolArgs) -> str:
    items = args.get("todoList", [])
    count = len(items) if isinstance(items, list) else 0
    return f"Update todo list ({count} items)" if count else "Update todo list"


def _fmt_get_errors(args: ToolArgs) -> str:
    paths = args.get("filePaths", [])
    if not paths:
        return "Check all errors"
    if len(paths) == 1:
        return f"Check errors: {_short_path(paths[0])}"
    return f"Check errors: {len(paths)} files"


def _fmt_fetch_webpage(args: ToolArgs) -> str:
    url = args.get("url", "")
    if url:
        from urllib.parse import urlparse

        try:
            p = urlparse(url)
            short = p.netloc + p.path[:30]
            return f"Fetch {_truncate(short, 50)}"
        except Exception:
            pass
    return "Fetch webpage"


def _fmt_rename_symbol(args: ToolArgs) -> str:
    old = args.get("oldName", args.get("old_name", ""))
    new = args.get("newName", args.get("new_name", ""))
    if old and new:
        return f"Rename {_truncate(old, 20)} → {_truncate(new, 20)}"
    return "Rename symbol"


def _fmt_view(args: ToolArgs) -> str:
    path = args.get("path", "")
    if not path:
        return "View file"
    short = _short_path(path)
    view_range = args.get("view_range")
    if isinstance(view_range, list) and len(view_range) >= 2:
        start, end = view_range[0], view_range[1]
        if end is not None and end != -1:
            return f"View {short}:{start}-{end}"
        return f"View {short}:{start}–end"
    return f"View {short}"


# -- Result hint formatters ---------------------------------------------------
# Each takes the raw result string and returns a terse suffix like "→ 12 matches".


def _count_lines(result: str) -> int:
    """Count non-empty lines in a result string."""
    return sum(1 for line in result.splitlines() if line.strip())


def _hint_bash(result: str, success: bool) -> str:
    if not success:
        first = result.strip().splitlines()[0] if result.strip() else "error"
        return f"→ FAIL: {_truncate(first, 40)}"
    n = _count_lines(result)
    return f"→ {n} lines" if n else "→ done"


def _hint_replace_string(result: str, success: bool) -> str:
    return "→ applied" if success else "→ FAIL: no match"


def _hint_multi_replace(result: str, success: bool) -> str:
    if not success:
        return "→ partial FAIL"
    return "→ applied"


def _hint_edit_with_args(result: str, success: bool, tool_args: str | None = None) -> str:
    """Edit hint showing line count derived from oldString/newString."""
    if not success:
        return "→ FAIL: no match"
    args = _parse_args(tool_args)
    old = args.get("oldString", args.get("old_str", args.get("old_string", "")))
    new = args.get("newString", args.get("new_str", args.get("new_string", "")))
    if isinstance(old, str) and isinstance(new, str) and (old or new):
        old_n = len(old.splitlines()) if old else 0
        new_n = len(new.splitlines()) if new else 0
        changed = max(old_n, new_n)
        if changed:
            return f"→ {changed} lines"
    return "→ applied"


def _hint_multi_edit_with_args(result: str, success: bool, tool_args: str | None = None) -> str:
    """Multi-edit hint showing total line count across all replacements."""
    if not success:
        return "→ partial FAIL"
    args = _parse_args(tool_args)
    replacements = args.get("replacements", args.get("edits", []))
    total = 0
    if isinstance(replacements, list):
        for r in replacements:
            if not isinstance(r, dict):
                continue
            old = r.get("oldString", r.get("old_string", r.get("old_str", "")))
            new = r.get("newString", r.get("new_string", r.get("new_str", "")))
            old_n = len(old.splitlines()) if isinstance(old, str) and old else 0
            new_n = len(new.splitlines()) if isinstance(new, str) and new else 0
            total += max(old_n, new_n)
    if total:
        return f"→ {total} lines"
    return "→ applied"


def _hint_get_errors(result: str, success: bool) -> str:
    n = _count_lines(result)
    return "→ clean" if n == 0 else f"→ {n} diagnostics"


def _hint_subagent(result: str, success: bool) -> str:
    if not success:
        return "→ FAIL"
    n = _count_lines(result)
    return f"→ done ({n} lines)" if n > 1 else "→ done"


def _hint_fetch_webpage(result: str, success: bool) -> str:
    if not success:
        return "→ FAIL"
    n = len(result)
    if n > 1024:
        return f"→ {n // 1024}KB"
    return f"→ {n} bytes"


def _hint_memory(result: str, success: bool) -> str:
    if not success:
        return "→ FAIL"
    n = _count_lines(result)
    return f"→ {n} lines" if n else "→ done"


# -- Registries ---------------------------------------------------------------
# Built from _SIMPLE_SPECS + explicit complex entries.

_FORMATTERS: dict[str, Callable[[ToolArgs], str]] = {
    name: _build_formatter(spec) for name, spec in _SIMPLE_SPECS.items()
}
_FORMATTERS.update(
    {
        "read_file": _fmt_read_file,
        "multi_replace_string_in_file": _fmt_multi_replace,
        "memory": _fmt_memory,
        "manage_todo_list": _fmt_manage_todo,
        "get_errors": _fmt_get_errors,
        "fetch_webpage": _fmt_fetch_webpage,
        "vscode_renameSymbol": _fmt_rename_symbol,
        "view": _fmt_view,
        # ---- Claude SDK PascalCase tools ------------------------------------
        # Simple-spec tools above cover: Bash, Glob, LS, Task, WebSearch,
        # TodoRead, Think, NotebookRead, NotebookEdit, Write, Edit, Grep, ListMcp*
        "Read": _fmt_read_file,  # same shape as read_file
        "MultiEdit": _fmt_multi_edit,
        "WebFetch": _fmt_fetch_webpage,
        "Computer": _fmt_computer,
        "ReadMcpResource": _fmt_read_mcp_resource,
    }
)

# Untruncated variant — same path-trimming as _FORMATTERS but no char limit.
# Used by format_tool_display_full so the frontend can apply CSS-based responsive
# truncation instead of a hardcoded character cap.
# Complex formatters (the .update() block above) don't truncate, so they're shared.
_FORMATTERS_FULL: dict[str, Callable[[ToolArgs], str]] = {
    name: _build_formatter(spec, no_truncate=True) for name, spec in _SIMPLE_SPECS.items()
}
_FORMATTERS_FULL.update({k: v for k, v in _FORMATTERS.items() if k not in _FORMATTERS_FULL})

_RESULT_HINTS: dict[str, Callable[[str, bool], str]] = {
    "bash": _hint_bash,
    "run_in_terminal": _hint_bash,
    "read_file": _count_hint("lines", empty="→ empty"),
    "create_file": _static_hint("→ created"),
    "replace_string_in_file": _hint_replace_string,
    "multi_replace_string_in_file": _hint_multi_replace,
    "grep_search": _count_hint("matches"),
    "semantic_search": _count_hint("results"),
    "file_search": _count_hint("files"),
    "list_dir": _count_hint("entries", empty="→ empty"),
    "manage_todo_list": _static_hint("→ updated"),
    "get_errors": _hint_get_errors,
    "runSubagent": _hint_subagent,
    "search_subagent": _hint_subagent,
    "get_terminal_output": _count_hint("lines", empty="→ empty"),
    "fetch_webpage": _hint_fetch_webpage,
    "memory": _hint_memory,
    "vscode_renameSymbol": _static_hint("→ renamed"),
    "vscode_listCodeUsages": _count_hint("usages", empty="→ none"),
    "glob": _count_hint("files", empty="→ no matches"),
    "grep": _count_hint("matches", empty="→ no matches"),
    "view": _count_hint("lines", empty="→ empty"),
    "write": _static_hint("→ written"),
    "str_replace_based_edit_tool": _hint_replace_string,
    "str_replace_editor": _hint_replace_string,
    # ---- Copilot-only tools -------------------------------------------------
    "web_search": _count_hint("results", empty="→ no results"),
    "insert_edit_into_file": _hint_replace_string,
    "get_changed_files": _count_hint("files", empty="→ none"),
    "run_vs_code_task": _static_hint("→ done"),
    "open_file": _static_hint("→ opened"),
    # ---- Claude SDK PascalCase tools ----------------------------------------
    "Bash": _hint_bash,
    "Read": _count_hint("lines", empty="→ empty"),
    "Write": _static_hint("→ written"),
    "Edit": _hint_replace_string,
    "MultiEdit": _hint_multi_replace,
    "Glob": _count_hint("files", empty="→ no matches"),
    "Grep": _count_hint("matches", empty="→ no matches"),
    "LS": _count_hint("entries", empty="→ empty"),
    "Task": _hint_subagent,
    "WebFetch": _hint_fetch_webpage,
    "WebSearch": _count_hint("results", empty="→ no results"),
    "TodoRead": _count_hint("items", empty="→ empty"),
    "NotebookRead": _count_hint("lines", empty="→ empty"),
    "NotebookEdit": _static_hint("→ applied"),
    "Computer": _static_hint("→ done"),
    "ReadMcpResource": _count_hint("lines", empty="→ empty"),
    # ---- Additional aliases ------------------------------------------------
    "delete_file": _static_hint("→ deleted"),
    "edit_file": _hint_replace_string,
    "write_file": _static_hint("→ written"),
    "create": _static_hint("→ created"),
    "create_or_update_file": _static_hint("→ done"),
    "apply_patch": _static_hint("→ applied"),
    "view_image": _static_hint("→ viewed"),
    "run_vscode_command": _static_hint("→ done"),
    "git_diff": _count_hint("lines", empty="→ clean"),
    "git_status": _count_hint("lines", empty="→ clean"),
    "git_log": _count_hint("commits", empty="→ empty"),
    "readFile": _count_hint("lines", empty="→ empty"),
    "editFile": _hint_replace_string,
    "listDir": _count_hint("entries", empty="→ empty"),
    "Agent": _hint_subagent,
    "cat": _count_hint("lines", empty="→ empty"),
    "find": _count_hint("files", empty="→ no matches"),
    "rg": _count_hint("matches", empty="→ no matches"),
    "fetch_url": _hint_fetch_webpage,
    "web_fetch": _hint_fetch_webpage,
    "WebFetch": _hint_fetch_webpage,
}

# Hint functions that also receive tool_args (third parameter) to compute
# richer information (e.g. line counts for edit tools).
_RESULT_HINTS_WITH_ARGS: dict[str, Callable[[str, bool, str | None], str]] = {
    "replace_string_in_file": _hint_edit_with_args,
    "edit": _hint_edit_with_args,
    "str_replace_based_edit_tool": _hint_edit_with_args,
    "str_replace_editor": _hint_edit_with_args,
    "Edit": _hint_edit_with_args,
    "insert_edit_into_file": _hint_edit_with_args,
    "multi_replace_string_in_file": _hint_multi_edit_with_args,
    "MultiEdit": _hint_multi_edit_with_args,
}


_UUID_RE = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-f]{8,}$", re.IGNORECASE)


def _humanize_tool_name(name: str) -> str:
    """Turn snake_case or camelCase tool names into human-readable labels.

    ``search_code`` → ``"Search code"``, ``listAllFiles`` → ``"List all files"``.
    UUIDs and hex strings are replaced with a generic label.
    """
    if _UUID_RE.match(name) or _HEX_RE.match(name):
        return "Tool action"
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    if not parts:
        return name
    return parts[0].capitalize() + (" " + " ".join(p.lower() for p in parts[1:]) if len(parts) > 1 else "")


# Keys commonly used by agent SDKs for human-readable descriptions in tool args.
_DESCRIPTION_KEYS: tuple[str, ...] = (
    "description",
    "explanation",
    "goal",
    "query",
    "prompt",
    "message",
    "title",
    "summary",
    "reason",
    "task",
)


def _extract_description_from_args(tool_args: str | None, max_len: int = 60) -> str | None:
    """Try to pull a human-readable label from common tool argument fields."""
    args = _parse_args(tool_args)
    if not args:
        return None
    for key in _DESCRIPTION_KEYS:
        val = args.get(key, "")
        if isinstance(val, str) and val.strip():
            return _truncate(val.strip(), max_len)
    return None


def format_tool_display(
    tool_name: str,
    tool_args: str | None,
    tool_result: str | None = None,
    tool_success: bool = True,
) -> str:
    """Return a short, deterministic, human-readable label for a tool call.

    When *tool_result* is provided (i.e. after execution), a result hint
    is appended (e.g. ``Grep: "foo" → 12 matches``).
    Falls back to the raw tool name if no formatter is registered.
    """
    # Strip MCP server prefix for lookup (e.g. "github/search_code" → "search_code")
    lookup_name = tool_name.rsplit("/", 1)[-1] if "/" in tool_name else tool_name
    formatter = _FORMATTERS.get(lookup_name)
    if formatter is None:
        # Try extracting a description from common arg fields before falling
        # back to the raw (humanized) tool name.
        desc = _extract_description_from_args(tool_args)
        humanized = _humanize_tool_name(lookup_name)
        if desc:
            label = f"{humanized}: {desc}" if humanized != "Tool action" else desc
        else:
            label = humanized
    else:
        args = _parse_args(tool_args)
        try:
            label = formatter(args)
        except Exception:
            label = tool_name

    # Append result hint when result is available
    if tool_result is not None:
        hint_args_fn = _RESULT_HINTS_WITH_ARGS.get(lookup_name)
        if hint_args_fn is not None:
            with contextlib.suppress(Exception):
                label = f"{label} {hint_args_fn(tool_result, tool_success, tool_args)}"
        else:
            hint_fn = _RESULT_HINTS.get(lookup_name)
            if hint_fn is not None:
                with contextlib.suppress(Exception):
                    label = f"{label} {hint_fn(tool_result, tool_success)}"

    return label


def format_tool_display_full(
    tool_name: str,
    tool_args: str | None,
    tool_result: str | None = None,
    tool_success: bool = True,
) -> str:
    """Like :func:`format_tool_display` but without character truncation.

    The returned label has worktree paths collapsed (``…/<branch>/…``) but is
    not capped at a fixed character count, so the frontend can apply CSS-based
    responsive truncation that adapts to the available viewport width.
    """
    lookup_name = tool_name.rsplit("/", 1)[-1] if "/" in tool_name else tool_name
    formatter = _FORMATTERS_FULL.get(lookup_name)
    if formatter is None:
        desc = _extract_description_from_args(tool_args, max_len=200)
        humanized = _humanize_tool_name(lookup_name)
        if desc:
            label = f"{humanized}: {desc}" if humanized != "Tool action" else desc
        else:
            label = humanized
    else:
        args = _parse_args(tool_args)
        try:
            label = formatter(args)
        except Exception:
            label = tool_name

    if tool_result is not None:
        hint_args_fn = _RESULT_HINTS_WITH_ARGS.get(lookup_name)
        if hint_args_fn is not None:
            with contextlib.suppress(Exception):
                label = f"{label} {hint_args_fn(tool_result, tool_success, tool_args)}"
        else:
            hint_fn = _RESULT_HINTS.get(lookup_name)
            if hint_fn is not None:
                with contextlib.suppress(Exception):
                    label = f"{label} {hint_fn(tool_result, tool_success)}"

    return label


# ---------------------------------------------------------------------------
# Tool visibility classification
# ---------------------------------------------------------------------------

# Always hidden regardless of args — pure SDK/agent bookkeeping.
_ALWAYS_HIDDEN: frozenset[str] = frozenset({
    "report_intent",
    "manage_todo_list",
    "TodoWrite",
    "TodoRead",
    "Think",
    "Sql",
    "sql",
    "ListMcpResourceTemplates",
    "ListMcpResources",
})

# Always collapsed regardless of args — read-only reconnaissance.
_ALWAYS_COLLAPSED: frozenset[str] = frozenset({
    "read_file",
    "list_dir",
    "get_errors",
    "grep_search",
    "file_search",
    "semantic_search",
    "tool_search_tool_regex",
    "view_image",
    "view",
    "Read",
    "View",
    "read_files",
    "list_files",
    "Glob",
    "LS",
    "Grep",
    "glob",
    "grep",
    "search_subagent",
    "get_terminal_output",
    "memory",
    "get_changed_files",
    "open_file",
    "vscode_listCodeUsages",
    "skill",
})

# Patterns in tool args that indicate agent-internal metadata (→ hidden).
_HIDDEN_ARG_PATTERNS: tuple[str, ...] = (
    "INSERT INTO todo",
    "UPDATE todo",
    "DELETE FROM todo",
    "SELECT * FROM todo",
    "manage_todo",
    '"intent"',
    "todoList",
)

# Patterns in tool args that indicate read-only recon (→ collapsed).
_COLLAPSED_ARG_PATTERNS: tuple[str, ...] = (
    "cat ",
    "head ",
    "tail ",
    "wc -l",
    "ls ",
    "find ",
    "which ",
    "command -v",
    "echo ",
    "pwd",
    "git status",
    "git log",
    "git diff",
    "git show",
)


def classify_tool_visibility(tool_name: str, tool_args: str | None = None) -> str:
    """Classify a tool into a visibility tier.

    - **hidden**: SDK-internal bookkeeping — never shown.
    - **collapsed**: Read-only reconnaissance — shown as a count.
    - **visible**: Meaningful mutations — always shown.
    """
    lookup = tool_name.rsplit("/", 1)[-1] if "/" in tool_name else tool_name

    if lookup in _ALWAYS_HIDDEN:
        return "hidden"
    if lookup in _ALWAYS_COLLAPSED:
        return "collapsed"

    if tool_args:
        args_lower = tool_args.lower()
        for pattern in _HIDDEN_ARG_PATTERNS:
            if pattern.lower() in args_lower:
                return "hidden"
        for pattern in _COLLAPSED_ARG_PATTERNS:
            if pattern.lower() in args_lower:
                return "collapsed"

    return "visible"


def extract_tool_issue(tool_result: str | None) -> str | None:
    """Return a concise issue summary for a non-successful tool result."""
    if not tool_result:
        return None

    stripped = tool_result.strip()
    if not stripped:
        return None

    with contextlib.suppress(json.JSONDecodeError, TypeError):
        parsed = json.loads(stripped)
        candidate = _extract_issue_from_json(parsed)
        if candidate:
            return _truncate(" ".join(candidate.split()), 120)

    lines = [" ".join(line.split()) for line in stripped.splitlines() if line.strip()]
    if not lines:
        return None

    for line in lines:
        lowered = line.lower()
        if lowered.startswith(("error:", "errors:", "failed:", "failure:", "warning:", "warnings:")):
            return _truncate(line, 120)

    return _truncate(lines[0], 120)
