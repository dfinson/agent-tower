"""Permission policy evaluation for SDK permission requests.

Evaluates tool-call permission decisions based on the active PermissionMode.

Modes
-----
FULL_AUTO          — approve everything within the current worktree.
OBSERVE_ONLY       — approve reads and grep/find; deny everything else.
REVIEW_AND_APPROVE — approve read_file; require approval for shells
                     (except grep/find), URL fetches, and writes.

Hard blocks
-----------
Regardless of mode or trust level, the following operations are ALWAYS
routed to the operator for explicit approval and can never be bypassed:

* ``git reset --hard`` — destructive history rewrite that discards all
  uncommitted changes and moves HEAD.  An agent must never run this
  without a human story and explicit sign-off.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

import structlog

from backend.models.domain import PermissionMode

log = structlog.get_logger()


class PolicyDecision(StrEnum):
    """Result of evaluating a permission request against the active policy."""

    approve = "approve"
    ask = "ask"
    deny = "deny"


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """Context for a single permission evaluation."""

    kind: str
    workspace_path: str
    possible_paths: list[str] | None = field(default=None)
    full_command_text: str | None = None
    file_name: str | None = None
    path: str | None = None
    read_only: bool | None = None


# ---------------------------------------------------------------------------
# Hard-gated shell commands — ALWAYS require operator approval regardless of
# permission mode.  These are irreversible or bypass CodePlane controls
# (e.g. merging outside the managed merge flow).
# ---------------------------------------------------------------------------
_HARD_GATED_SHELL_RE = re.compile(
    r"(?i)"
    # git merge / pull / rebase / cherry-pick — bypass CodePlane merge controls
    r"(?:^\s*git\s+(?:merge|pull|rebase|cherry-pick)\b)"
    # git reset --hard — destructive history rewrite
    r"|(?:^\s*git\s+reset\s+.*--hard\b)"
    r"|(?:^\s*git\s+reset\s+--hard\b)",
)


# ---------------------------------------------------------------------------
# Hard-blocked commands — always require explicit operator approval,
# regardless of permission mode or trust level.
# ---------------------------------------------------------------------------

# Matches `git reset --hard` in any reasonable shell command string, including
# compound commands joined with &&, || or ;.  Both orderings are covered:
#   git reset --hard HEAD
#   git reset HEAD --hard
#   cd /repo && git reset --hard origin/main
_GIT_RESET_HARD_RE = re.compile(
    r"\bgit\s+reset\b[^|;&\n]*?\s--hard\b",
    re.IGNORECASE,
)

# Strips the *contents* of shell string literals so that `git reset --hard`
# appearing only inside a quoted argument (e.g. a ``git commit -m "..."``
# message) is not mistakenly matched as a real command invocation.
_QUOTED_STRING_RE = re.compile(
    r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'',
    re.DOTALL,
)


def _strip_quoted_strings(cmd: str) -> str:
    """Replace the contents of every quoted string with an empty placeholder."""
    return _QUOTED_STRING_RE.sub('""', cmd)


def is_git_reset_hard(command: str) -> bool:
    """Return True if *command* contains a ``git reset --hard`` invocation.

    This is used to enforce the platform-level hard block: no agent may run
    ``git reset --hard`` without explicit operator approval, regardless of
    the active permission mode or whether the job has been trusted.

    Quoted string contents (e.g. a ``git commit -m "..."`` message) are
    stripped before matching so that literal text inside arguments does not
    cause false positives.
    """
    return bool(_GIT_RESET_HARD_RE.search(_strip_quoted_strings(command)))


# ---------------------------------------------------------------------------
# Read-only shell commands that are always safe.
# Covers Unix (grep, ls, cat …), Windows cmd (dir, findstr, where …),
# and PowerShell cmdlets (Get-ChildItem, Select-String …).
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------

_APPROVE = PolicyDecision.approve
_DENY = PolicyDecision.deny
_ASK = PolicyDecision.ask

# Sentinel callables for special-case evaluation
_SHELL_RO = "shell_readonly"  # approve if readonly shell, else <fallback>
_PATH_WS = "path_in_ws"  # approve if target is inside workspace
_MCP_RO = "mcp_readonly"  # approve if mcp tool is read-only
_READ_WS = "read_in_ws"  # approve if read target is in workspace (deny otherwise)


class _Rule(NamedTuple):
    decision: PolicyDecision | str
    fallback: PolicyDecision = _APPROVE  # used by compound rules


# (mode, kind) → rule.  Missing entries fall through to the mode default.
_RULES: dict[tuple[str, str], _Rule] = {
    # ── FULL_AUTO ──────────────────────────────────────────────────────────
    (PermissionMode.full_auto, "read"): _Rule(_APPROVE),
    (PermissionMode.full_auto, "memory"): _Rule(_APPROVE),
    (PermissionMode.full_auto, "write"): _Rule(_PATH_WS, _APPROVE),  # approve; workspace path check first
    (PermissionMode.full_auto, "shell"): _Rule(_APPROVE),
    (PermissionMode.full_auto, "mcp"): _Rule(_APPROVE),
    (PermissionMode.full_auto, "url"): _Rule(_APPROVE),
    (PermissionMode.full_auto, "custom-tool"): _Rule(_APPROVE),
    # ── OBSERVE_ONLY ────────────────────────────────────────────────────
    (PermissionMode.observe_only, "memory"): _Rule(_APPROVE),
    (PermissionMode.observe_only, "read"): _Rule(_READ_WS),
    (PermissionMode.observe_only, "shell"): _Rule(_SHELL_RO, _DENY),
    (PermissionMode.observe_only, "mcp"): _Rule(_MCP_RO, _DENY),
    (PermissionMode.observe_only, "write"): _Rule(_DENY),
    (PermissionMode.observe_only, "url"): _Rule(_DENY),
    (PermissionMode.observe_only, "custom-tool"): _Rule(_DENY),
    # ── REVIEW_AND_APPROVE ────────────────────────────────────────────
    (PermissionMode.review_and_approve, "memory"): _Rule(_APPROVE),
    (PermissionMode.review_and_approve, "read"): _Rule(_APPROVE),
    (PermissionMode.review_and_approve, "shell"): _Rule(_SHELL_RO, _ASK),
    (PermissionMode.review_and_approve, "write"): _Rule(_ASK),
    (PermissionMode.review_and_approve, "url"): _Rule(_ASK),
    (PermissionMode.review_and_approve, "mcp"): _Rule(_MCP_RO, _ASK),
    (PermissionMode.review_and_approve, "custom-tool"): _Rule(_ASK),
}

# Default decisions when a (mode, kind) pair is not in the table.
_MODE_DEFAULTS: dict[str, PolicyDecision] = {
    PermissionMode.full_auto: _APPROVE,
    PermissionMode.observe_only: _DENY,
    PermissionMode.review_and_approve: _ASK,
}


def _resolve_path_ws(
    rule: _Rule,
    *,
    workspace_path: str,
    file_name: str | None,
    path: str | None,
    possible_paths: list[str] | None,
    **_kw: object,
) -> PolicyDecision:
    target = file_name or path
    if target and _is_path_within_workspace(target, workspace_path):
        return _APPROVE
    if possible_paths and all(_is_path_within_workspace(p, workspace_path) for p in possible_paths):
        return _APPROVE
    return rule.fallback


def _resolve_shell_ro(
    rule: _Rule,
    *,
    full_command_text: str | None,
    **_kw: object,
) -> PolicyDecision:
    cmd = full_command_text or ""
    return _APPROVE if _READONLY_SHELL_RE.match(cmd) else rule.fallback


def _resolve_mcp_ro(
    rule: _Rule,
    *,
    read_only: bool | None,
    **_kw: object,
) -> PolicyDecision:
    return _APPROVE if read_only else rule.fallback


def _resolve_read_ws(
    rule: _Rule,
    *,
    workspace_path: str,
    file_name: str | None,
    path: str | None,
    **_kw: object,
) -> PolicyDecision:
    target = file_name or path
    if target is None or _is_path_within_workspace(target, workspace_path):
        return _APPROVE
    return _DENY


_SENTINEL_RESOLVERS = {
    _PATH_WS: _resolve_path_ws,
    _SHELL_RO: _resolve_shell_ro,
    _MCP_RO: _resolve_mcp_ro,
    _READ_WS: _resolve_read_ws,
}


def _resolve(
    rule: _Rule,
    *,
    workspace_path: str,
    file_name: str | None,
    path: str | None,
    possible_paths: list[str] | None,
    full_command_text: str | None,
    read_only: bool | None,
) -> PolicyDecision:
    """Resolve a rule entry into a concrete PolicyDecision."""
    decision = rule.decision

    if isinstance(decision, PolicyDecision):
        return decision

    resolver = _SENTINEL_RESOLVERS.get(decision)
    if resolver is not None:
        return resolver(
            rule,
            workspace_path=workspace_path,
            file_name=file_name,
            path=path,
            possible_paths=possible_paths,
            full_command_text=full_command_text,
            read_only=read_only,
        )

    return rule.fallback  # pragma: no cover


def evaluate(
    mode: str,
    *,
    req: PermissionRequest | None = None,
    # Legacy keyword arguments — prefer passing a PermissionRequest.
    kind: str = "",
    workspace_path: str = "",
    possible_paths: list[str] | None = None,
    full_command_text: str | None = None,
    file_name: str | None = None,
    path: str | None = None,
    read_only: bool | None = None,
) -> PolicyDecision:
    """Evaluate a permission request against the given mode.

    This is the single public entry-point — callers pass the mode string
    directly instead of picking a mode-specific wrapper function.

    Accepts either a ``PermissionRequest`` via *req* or individual keyword
    arguments for backward compatibility.
    """
    if req is None:
        req = PermissionRequest(
            kind=kind,
            workspace_path=workspace_path,
            possible_paths=possible_paths,
            full_command_text=full_command_text,
            file_name=file_name,
            path=path,
            read_only=read_only,
        )

    # Hard-gated commands always require approval, regardless of mode or trust level.
    # _HARD_GATED_SHELL_RE covers merge/pull/rebase/cherry-pick and simple git reset --hard.
    # is_git_reset_hard() additionally catches compound commands (e.g. cd /x && git reset --hard).
    if (
        req.kind == "shell"
        and req.full_command_text
        and (_HARD_GATED_SHELL_RE.search(req.full_command_text) or is_git_reset_hard(req.full_command_text))
    ):
        log.info("hard_gated_command", command=req.full_command_text, mode=mode)
        return _ASK

    rule = _RULES.get((mode, req.kind))
    if rule is None:
        default = _MODE_DEFAULTS.get(mode, _ASK)
        if default == _ASK:
            log.warning("unknown_permission_kind", kind=req.kind)
        return default

    return _resolve(
        rule,
        workspace_path=req.workspace_path,
        file_name=req.file_name,
        path=req.path,
        possible_paths=req.possible_paths,
        full_command_text=req.full_command_text,
        read_only=req.read_only,
    )
