"""Action classifier — determines (reversible, contained) and tier for every action.

Input channels: file operations, SDK tools, MCP tools, shell commands.
Tier resolution: explicit rules → preset logic → default.
"""

from __future__ import annotations

import fnmatch
import re
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

from backend.services.action_policy.shell_classifier import classify_shell

log = structlog.get_logger()


# Maximum time (seconds) to allow a user-supplied regex to run.
_REGEX_TIMEOUT_SECONDS = 1


def _safe_regex_search(pattern: str, text: str) -> bool:
    """Run ``re.search`` with a timeout to prevent ReDoS from user patterns.

    Uses a daemon thread so it works on all platforms (no SIGALRM).
    """
    result: list[bool] = []
    error: list[BaseException] = []

    def _worker() -> None:
        try:
            result.append(bool(re.search(pattern, text)))
        except re.error as exc:
            error.append(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=_REGEX_TIMEOUT_SECONDS)
    if t.is_alive():
        log.warning("regex_match_timed_out", pattern=pattern[:80])
        return False  # thread abandoned as daemon — will die with process
    if error:
        return False
    return result[0] if result else False


class Tier(StrEnum):
    observe = "observe"
    checkpoint = "checkpoint"
    gate = "gate"


class Preset(StrEnum):
    autonomous = "autonomous"
    supervised = "supervised"
    strict = "strict"


class ActionKind(StrEnum):
    file = "file"
    sdk_tool = "sdk_tool"
    mcp_tool = "mcp_tool"
    shell = "shell"


@dataclass(frozen=True, slots=True)
class Action:
    """Describes a single agent action to be classified."""

    kind: ActionKind
    # File operations
    path: str | None = None
    is_binary: bool = False
    outside_worktree: bool = False
    # Shell
    command: str | None = None
    # SDK tool
    tool_name: str | None = None
    # MCP tool
    mcp_server: str | None = None
    mcp_tool: str | None = None
    mcp_read_only: bool = False
    # Context
    job_id: str | None = None
    workspace_path: str | None = None


@dataclass(frozen=True, slots=True)
class Classification:
    """Result of classifying an action."""

    reversible: bool
    contained: bool
    tier: Tier
    reason: str


@dataclass
class RepoPolicy:
    """In-memory policy loaded from DB at job start."""

    preset: Preset = Preset.supervised
    path_rules: list[dict[str, Any]] = field(default_factory=list)
    action_rules: list[dict[str, Any]] = field(default_factory=list)
    cost_rules: list[dict[str, Any]] = field(default_factory=list)
    mcp_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    batch_window_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class CostContext:
    """Runtime cost data passed into the classifier for cost rule evaluation.

    ``job_spend_usd`` is the total spend for the current job, used as the
    comparison value against cost-rule thresholds.
    """

    job_spend_usd: float = 0.0


# ---------------------------------------------------------------------------
# SDK tool classification table
# ---------------------------------------------------------------------------

_SDK_TOOLS: dict[str, tuple[bool, bool]] = {
    "create_file":    (True,  True),
    "edit_file":      (True,  True),
    "delete_file":    (True,  True),
    "read_file":      (True,  True),
    "list_dir":       (True,  True),
    "search_files":   (True,  True),
    "grep_search":    (True,  True),
    "run_terminal":   (False, True),  # delegates to shell classifier
    "browser_action": (False, False),
    "ask_user":       (True,  True),
    "report_intent":  (True,  True),
}


def classify_properties(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    """Determine (reversible, contained, reason) for an action.

    Uses the action kind to pick the right classification channel.
    MCP server-level config acts as a floor — tool annotations can only relax.
    """
    if action.kind == ActionKind.file:
        return _classify_file(action, policy)
    if action.kind == ActionKind.sdk_tool:
        return _classify_sdk_tool(action, policy)
    if action.kind == ActionKind.mcp_tool:
        return _classify_mcp_tool(action, policy)
    if action.kind == ActionKind.shell:
        return _classify_shell_action(action, policy)
    return False, True, "unknown action kind"


def resolve_tier(
    reversible: bool,
    contained: bool,
    preset: Preset,
) -> Tier:
    """Map (reversible, contained) to a tier based on the active preset."""
    if preset == Preset.autonomous:
        if not contained:
            return Tier.gate
        return Tier.observe
    if preset == Preset.supervised:
        if not contained or not reversible:
            return Tier.gate
        return Tier.observe
    # strict
    if reversible and contained:
        return Tier.checkpoint
    return Tier.gate


def classify(action: Action, policy: RepoPolicy, cost: CostContext | None = None) -> Classification:
    """Full classification: properties → rule check → tier resolution → cost promotion."""
    reversible, contained, reason = classify_properties(action, policy)

    # 1. Explicit rules override tier
    rule_tier = _match_explicit_rule(action, policy)
    if rule_tier is not None:
        tier = rule_tier
        reason = f"explicit rule: {reason}"
    else:
        # 2. Preset-based tier
        tier = resolve_tier(reversible, contained, policy.preset)

    # 3. Cost rule promotion — can only promote tier upward
    if cost is not None:
        promoted = _apply_cost_promotion(tier, policy.cost_rules, cost)
        if promoted != tier:
            reason = f"cost promotion: {reason}"
            tier = promoted

    return Classification(
        reversible=reversible,
        contained=contained,
        tier=tier,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Channel classifiers
# ---------------------------------------------------------------------------

def _classify_file(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    if action.outside_worktree:
        return True, False, "file outside worktree"
    if action.is_binary:
        return False, True, "binary file (no meaningful diff)"
    return True, True, "tracked file operation"


def _classify_sdk_tool(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    tool = action.tool_name or ""
    # run_terminal delegates to shell classifier
    if tool == "run_terminal" and action.command:
        rev, cont = classify_shell(action.command)
        return rev, cont, f"shell via run_terminal: {action.command[:60]}"

    props = _SDK_TOOLS.get(tool)
    if props:
        return props[0], props[1], f"SDK tool: {tool}"
    return False, True, f"unknown SDK tool: {tool}"


def _classify_mcp_tool(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    server_name = action.mcp_server or ""
    server_config = policy.mcp_configs.get(server_name, {})

    # Server-level defaults
    srv_reversible = server_config.get("reversible", False)
    srv_contained = server_config.get("contained", False)

    # Per-tool overrides can only relax (make less restrictive)
    tool_name = action.mcp_tool or ""
    tool_overrides = server_config.get("tool_overrides", {})
    tool_config = tool_overrides.get(tool_name, {})

    reversible = tool_config.get("reversible", srv_reversible) or srv_reversible
    contained = tool_config.get("contained", srv_contained) or srv_contained

    # readOnlyHint from MCP protocol relaxes to observe
    if action.mcp_read_only:
        reversible = True

    reason = f"MCP {server_name}/{tool_name}"
    return reversible, contained, reason


def _classify_shell_action(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    cmd = action.command or ""
    rev, cont = classify_shell(cmd)
    return rev, cont, f"shell: {cmd[:60]}"


# ---------------------------------------------------------------------------
# Explicit rule matching
# ---------------------------------------------------------------------------

def _match_explicit_rule(action: Action, policy: RepoPolicy) -> Tier | None:
    """Check if any explicit rule matches this action. Returns tier or None."""
    # Path rules (file actions)
    if action.kind == ActionKind.file and action.path:
        for rule in policy.path_rules:
            if fnmatch.fnmatch(action.path, rule["path_pattern"]):
                return Tier(rule["tier"])

    # Action rules (regex match against command or tool name)
    identifier = ""
    if action.kind == ActionKind.shell and action.command:
        identifier = action.command
    elif action.tool_name:
        identifier = action.tool_name
    elif action.mcp_tool:
        identifier = f"{action.mcp_server}/{action.mcp_tool}"

    if identifier:
        for rule in policy.action_rules:
            if _safe_regex_search(rule["match_pattern"], identifier):
                return Tier(rule["tier"])

    return None


# -- Cost rule promotion --------------------------------------------------- #

_TIER_ORDER = {Tier.observe: 0, Tier.checkpoint: 1, Tier.gate: 2}


def _apply_cost_promotion(
    current_tier: Tier,
    cost_rules: list[dict[str, Any]],
    cost: CostContext,
) -> Tier:
    """Promote tier upward based on cost rules. Never demotes.

    Each cost rule has ``threshold_value`` (USD) and ``promote_to``
    (checkpoint or gate). If the current daily spend meets or exceeds
    the threshold, the tier is promoted — but only if the target tier
    is higher than the current tier.
    """
    best = current_tier
    for rule in cost_rules:
        threshold = rule.get("threshold_value")
        if threshold is None:
            continue  # informational-only rule, no numeric threshold
        promote_to_raw = rule.get("promote_to")
        if promote_to_raw is None:
            continue
        try:
            target = Tier(promote_to_raw)
        except ValueError:
            log.warning("cost_rule_invalid_tier", promote_to=promote_to_raw)
            continue
        if cost.job_spend_usd >= threshold and _TIER_ORDER.get(target, 0) > _TIER_ORDER.get(best, 0):
            best = target
    return best
