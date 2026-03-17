"""Permission policy evaluation for SDK permission requests.

Evaluates tool-call permission decisions based on the active PermissionMode.

Modes
-----
AUTO             — approve everything within the current worktree.
READ_ONLY        — approve reads and grep/find; deny everything else.
APPROVAL_REQUIRED — approve read_file; require approval for shells
                    (except grep/find), URL fetches, and writes.
"""

from __future__ import annotations

import os
import re
from enum import StrEnum

import structlog

log = structlog.get_logger()


class PolicyDecision(StrEnum):
    """Result of evaluating a permission request against the active policy."""

    approve = "approve"
    ask = "ask"
    deny = "deny"


# Read-only shell commands that are always safe.
# Covers Unix (grep, ls, cat …), Windows cmd (dir, findstr, where …),
# and PowerShell cmdlets (Get-ChildItem, Select-String …).
_READONLY_SHELL_RE = re.compile(
    r"^\s*("
    # Unix
    r"grep|egrep|fgrep|rg|find|ls|cat|head|tail|wc|sort|diff|file|stat|du|tree"
    r"|echo|pwd|which|type|printenv|env|more|less"
    # Windows cmd builtins
    r"|dir|findstr|where|fc|more"
    # PowerShell cmdlets & common aliases
    r"|Get-ChildItem|Get-Content|Get-Item|Get-ItemProperty|Get-Location"
    r"|Select-String|Measure-Object|Compare-Object|Test-Path|Resolve-Path"
    r"|Write-Output|Out-Host|Format-List|Format-Table"
    r"|gci|gc|gi|sls|measure|compare"
    r")\b",
    re.IGNORECASE,
)


def _is_path_within_workspace(path: str, workspace: str) -> bool:
    """Check whether *path* is inside (or equal to) *workspace*."""
    try:
        rp = os.path.realpath(path)
        rw = os.path.realpath(workspace)
        return rp == rw or rp.startswith(rw + os.sep)
    except (TypeError, ValueError):
        return False


def evaluate_auto(
    *,
    kind: str,
    workspace_path: str,
    possible_paths: list[str] | None = None,
    file_name: str | None = None,
    path: str | None = None,
) -> PolicyDecision:
    """AUTO mode: approve everything that touches the current worktree."""

    # All reads — approve
    if kind in ("read", "memory"):
        return PolicyDecision.approve

    # Writes/shells within workspace — approve
    target = file_name or path
    if target and _is_path_within_workspace(target, workspace_path):
        return PolicyDecision.approve

    # Check possible_paths
    if possible_paths:
        if all(_is_path_within_workspace(p, workspace_path) for p in possible_paths):
            return PolicyDecision.approve

    # Shell commands — approve (agent has full execution permission)
    if kind == "shell":
        return PolicyDecision.approve

    # MCP tools — approve
    if kind == "mcp":
        return PolicyDecision.approve

    # URL fetches — approve
    if kind == "url":
        return PolicyDecision.approve

    # Writes with no path info — approve (trust the agent)
    if kind == "write":
        return PolicyDecision.approve

    # Unknown — approve (AUTO = full trust)
    return PolicyDecision.approve


def evaluate_read_only(
    *,
    kind: str,
    workspace_path: str,
    full_command_text: str | None = None,
    file_name: str | None = None,
    path: str | None = None,
    read_only: bool | None = None,
) -> PolicyDecision:
    """READ_ONLY mode: allow reads within worktree + grep/find. Block everything else."""

    # Memory — approve
    if kind == "memory":
        return PolicyDecision.approve

    # Reads within workspace — approve
    if kind == "read":
        target = file_name or path
        if target is None or _is_path_within_workspace(target, workspace_path):
            return PolicyDecision.approve
        return PolicyDecision.deny

    # Shell: only grep/find allowed
    if kind == "shell":
        cmd = full_command_text or ""
        if _READONLY_SHELL_RE.match(cmd):
            return PolicyDecision.approve
        return PolicyDecision.deny

    # MCP: only read-only tools
    if kind == "mcp":
        if read_only:
            return PolicyDecision.approve
        return PolicyDecision.deny

    # Writes, URL fetches — deny
    if kind in ("write", "url", "custom-tool"):
        return PolicyDecision.deny

    return PolicyDecision.deny


def evaluate_approval_required(
    *,
    kind: str,
    workspace_path: str,
    full_command_text: str | None = None,
    file_name: str | None = None,
    path: str | None = None,
    read_only: bool | None = None,
) -> PolicyDecision:
    """APPROVAL_REQUIRED mode: always allow read_file. Require approval for the rest."""

    # Memory — approve
    if kind == "memory":
        return PolicyDecision.approve

    # Reads — always approve
    if kind == "read":
        return PolicyDecision.approve

    # Shell: grep/find auto-approve, everything else needs approval
    if kind == "shell":
        cmd = full_command_text or ""
        if _READONLY_SHELL_RE.match(cmd):
            return PolicyDecision.approve
        return PolicyDecision.ask

    # Writes — need approval
    if kind == "write":
        return PolicyDecision.ask

    # URL fetches — need approval
    if kind == "url":
        return PolicyDecision.ask

    # MCP: read-only auto-approve, mutations need approval
    if kind == "mcp":
        if read_only:
            return PolicyDecision.approve
        return PolicyDecision.ask

    # Custom tools — need approval
    if kind == "custom-tool":
        return PolicyDecision.ask

    # Unknown — ask
    log.warning("unknown_permission_kind", kind=kind)
    return PolicyDecision.ask
