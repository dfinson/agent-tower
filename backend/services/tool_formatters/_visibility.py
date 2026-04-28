"""Tool visibility classification and edit-success correction."""

from __future__ import annotations

import contextlib
import json
import re

from backend.services.tool_formatters._display import _extract_issue_from_json, _truncate


# ---------------------------------------------------------------------------
# Tool visibility classification
# ---------------------------------------------------------------------------

# Always hidden regardless of args — pure SDK/agent bookkeeping.
_ALWAYS_HIDDEN: frozenset[str] = frozenset(
    {
        "report_intent",
        "manage_todo_list",
        "TodoWrite",
        "TodoRead",
        "Think",
        "Sql",
        "sql",
        "ListMcpResourceTemplates",
        "ListMcpResources",
    }
)

# Always collapsed regardless of args — read-only reconnaissance.
_ALWAYS_COLLAPSED: frozenset[str] = frozenset(
    {
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
    }
)

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


# ---------------------------------------------------------------------------
# Edit-tool success correction
# ---------------------------------------------------------------------------
# Agent SDKs (Claude Code, Copilot) can report is_error / success=False on
# file-edit tool results even when the edit was successfully applied to disk.
# This happens because the SDK performs post-edit validation (lint, syntax
# check) and conflates a validation warning with a tool failure.  The result
# is a misleading "Failed" badge in the UI while the diff clearly shows
# the applied changes.
#
# ``correct_edit_success`` inspects the tool result text for definitive
# evidence that the edit did NOT happen (no match, file not found, etc.).
# If no such evidence is found, it overrides the SDK's error flag to True
# (success), preventing the false-failure display.
# ---------------------------------------------------------------------------

# Patterns that indicate the file-edit genuinely did not apply.
_EDIT_FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:old_?str(?:ing)?|search.string).{0,30}not found", re.IGNORECASE),
    re.compile(r"no\s+match", re.IGNORECASE),
    re.compile(r"(?:file|path).{0,20}(?:not found|does not exist|doesn.t exist)", re.IGNORECASE),
    re.compile(r"(?:multiple|ambiguous).{0,20}(?:match|occurrence)", re.IGNORECASE),
    re.compile(r"(?:string|text).{0,30}(?:not found|does not appear)", re.IGNORECASE),
    re.compile(r"permission\s+denied", re.IGNORECASE),
    re.compile(r"is a directory", re.IGNORECASE),
    re.compile(r"matched\s+multiple\s+locations", re.IGNORECASE),
)

# Tools whose success flag we're willing to correct.
_EDIT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "replace_string_in_file",
        "multi_replace_string_in_file",
        "str_replace_based_edit_tool",
        "str_replace_editor",
        "insert_edit_into_file",
        "edit_file",
        "edit",
        "Edit",
        "MultiEdit",
        "editFile",
        "apply_patch",
    }
)


def _is_definite_edit_failure(result_text: str) -> bool:
    """Return True if the result text clearly indicates the edit was not applied."""
    return any(pattern.search(result_text) for pattern in _EDIT_FAILURE_PATTERNS)


def correct_edit_success(
    tool_name: str,
    sdk_success: bool,
    result_text: str,
) -> bool:
    """Return a corrected success flag for file-edit tools.

    If the SDK reported failure but the result text does not contain evidence
    that the edit genuinely failed (no match, file not found, etc.), return
    True to prevent a misleading "Failed" label in the UI.

    For non-edit tools or when the SDK already reports success, the original
    flag is returned unchanged.
    """
    if sdk_success:
        return True
    if tool_name not in _EDIT_TOOL_NAMES:
        return sdk_success
    if not result_text or not result_text.strip():
        return sdk_success
    # SDK says error but no evidence the edit failed — override to success.
    return not _is_definite_edit_failure(result_text)
