"""TraceForge classify → CodePlane policy adapter.

Replaces CodePlane's hand-rolled ``classify_properties`` derivation (and the
retired ``shell_classifier``) with TraceForge's trained 7-dimension classifier
(``traceforge.classify``) plus its canonical risk model (``assess_risk`` /
``assess_tool_risk``).

The public entry point ``derive_properties`` is a drop-in replacement for the old
``classify_properties`` — same signature, same ``(reversible, contained, reason)``
contract — so the downstream enforcement path (``resolve_tier``, explicit rules,
cost promotion, router, batcher, trust) is unchanged. This adapter only changes
how ``(reversible, contained)`` are *derived*.

Mapping philosophy — TraceForge dimensions → CodePlane policy inputs:

* ``contained``  — effects stay inside the local worktree/sandbox. Network egress
  (``network.*`` mechanism or ``network_outbound`` capability), actions on files
  outside the worktree, or a ``critical`` risk level break containment.
* ``reversible`` — the action can be undone. File-channel operations are backed by
  the git worktree checkpoint, so they are reversible even when destructive
  (``git checkout`` restores a deleted tracked file). For non-git-backed channels
  (shell, MCP, network tools) reversibility follows TraceForge's ``effect`` and
  risk level: ``destructive`` / ``danger`` / ``critical`` / remote-mutation are
  irreversible; unrecognized tools default to irreversible (CodePlane's historical
  conservative stance); everything else is reversible.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from traceforge.classify import (
    assess_risk,
    assess_tool_risk,
    classify_cmd_command,
    classify_powershell_command,
    classify_shell,
    classify_tool,
    normalize_tool_name,
)
from traceforge.classify.config import ClassificationEngine, load_config

from backend.services.action_policy.classifier import Action, ActionKind, RepoPolicy

if TYPE_CHECKING:
    from traceforge.classify.core import Classification as TFClassification
    from traceforge.classify.risk import RiskAssessment

log = structlog.get_logger()

_OVERLAY_PATH = Path(__file__).parent / "data" / "traceforge_overlay.yaml"

# Shell tool names that carry a command string handled via the shell dialect
# classifiers. Detected structurally (command present + normalizes to "shell").
_PWSH_TOOL_HINTS = frozenset({"powershell", "pwsh"})
_CMD_TOOL_HINTS = frozenset({"cmd", "cmd.exe"})


@functools.lru_cache(maxsize=1)
def _engine() -> ClassificationEngine:
    """Build (once) the CodePlane-overlaid classification engine.

    The overlay is merged on top of TraceForge's built-in defaults and passed
    explicitly as ``engine=`` to every classify/assess call, so classification is
    deterministic regardless of process cwd and never mutates TraceForge's global
    default engine.
    """
    return ClassificationEngine(load_config(_OVERLAY_PATH, merge_defaults=True))


def derive_properties(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    """Determine ``(reversible, contained, reason)`` for an action via TraceForge.

    Drop-in replacement for the retired ``classify_properties``.
    """
    if action.kind == ActionKind.file:
        return _derive_file(action)
    if action.kind == ActionKind.sdk_tool:
        return _derive_sdk_tool(action)
    if action.kind == ActionKind.mcp_tool:
        return _derive_mcp_tool(action, policy)
    if action.kind == ActionKind.shell:
        return _derive_shell(action.command or "", channel="shell")
    return False, True, "unknown action kind"


# ---------------------------------------------------------------------------
# Property mapping — TraceForge Classification + RiskAssessment → (rev, cont)
# ---------------------------------------------------------------------------


def _is_network(cls: TFClassification) -> bool:
    return cls.mechanism.startswith("network") or "network_outbound" in cls.capability


def _props_from_tf(
    cls: TFClassification,
    risk: RiskAssessment | None,
    *,
    git_backed: bool,
    outside_worktree: bool = False,
) -> tuple[bool, bool]:
    """Map a TraceForge classification + risk assessment to ``(reversible, contained)``."""
    network = _is_network(cls)
    level = risk.level if risk is not None else "caution"

    contained = not (network or outside_worktree or level == "critical")

    if level == "critical":
        reversible = False
    elif git_backed and not network:
        # git worktree checkpoint restores any in-tree filesystem change.
        reversible = True
    elif (
        # Irreversible: destructive effect, high risk, remote/outbound mutation
        # (push/POST/publish cannot be undone locally), or an unrecognized non-read
        # tool (CodePlane's historical conservative default).
        cls.effect == "destructive"
        or level == "danger"
        or (cls.effect == "mutating" and network)
        or (cls.mechanism == "unknown" and cls.effect != "read_only")
    ):
        reversible = False
    else:
        reversible = True

    return reversible, contained


def _risk_tag(cls: TFClassification, risk: RiskAssessment | None) -> str:
    level = risk.level if risk is not None else "?"
    return f"[{cls.mechanism}/{cls.effect or 'n/a'}/risk={level}]"


# ---------------------------------------------------------------------------
# Channel derivation
# ---------------------------------------------------------------------------


def _derive_file(action: Action) -> tuple[bool, bool, str]:
    """File operations are git-backed: reversible via checkout, contained in-tree."""
    if action.outside_worktree:
        return True, False, "file outside worktree"
    if action.is_binary:
        return True, True, "binary file (git-tracked, reversible via checkout)"
    return True, True, "tracked file operation"


def _derive_sdk_tool(action: Action) -> tuple[bool, bool, str]:
    tool = action.tool_name or ""
    engine = _engine()

    # Shell tools carry a command → classify via the shell dialect classifiers.
    if action.command and normalize_tool_name(tool, engine) == "shell":
        rev, cont, _ = _derive_shell(action.command, channel=f"shell via {tool}")
        return rev, cont, f"shell via {tool}: {action.command[:60]}"

    cls = classify_tool(tool, engine=engine)
    risk = assess_tool_risk(classification=cls, engine=engine, targets=_targets(action))
    git_backed = cls.mechanism == "filesystem" and not action.outside_worktree
    rev, cont = _props_from_tf(cls, risk, git_backed=git_backed, outside_worktree=action.outside_worktree)
    return rev, cont, f"SDK tool {tool} {_risk_tag(cls, risk)}"


def _derive_mcp_tool(action: Action, policy: RepoPolicy) -> tuple[bool, bool, str]:
    server_name = action.mcp_server or ""
    tool_name = action.mcp_tool or ""
    engine = _engine()

    # Base classification from TraceForge (MCP profiles → verb inference → unknown).
    raw = f"mcp__{server_name}__{tool_name}" if server_name else tool_name
    cls = classify_tool(raw, engine=engine)
    risk = assess_tool_risk(classification=cls, engine=engine, targets=_targets(action))
    tf_reversible, tf_contained = _props_from_tf(cls, risk, git_backed=False)

    # CodePlane per-server policy (loaded from DB) acts as the floor; TraceForge's
    # derivation is the default when the server is unconfigured. Per-tool overrides
    # can only relax (make less restrictive), matching the retired behavior.
    server_config = policy.mcp_configs.get(server_name, {})
    srv_reversible = server_config.get("reversible", tf_reversible)
    srv_contained = server_config.get("contained", tf_contained)

    tool_overrides = server_config.get("tool_overrides", {})
    tool_config = tool_overrides.get(tool_name, {})
    reversible = tool_config.get("reversible", srv_reversible) or srv_reversible
    contained = tool_config.get("contained", srv_contained) or srv_contained

    # readOnlyHint from the MCP protocol can relax reversibility, but only for
    # servers explicitly trusted in config (a malicious server can self-declare it).
    if action.mcp_read_only and server_config.get("trust_read_only_hint", False):
        reversible = True

    return reversible, contained, f"MCP {server_name}/{tool_name} {_risk_tag(cls, risk)}"


def _derive_shell(command: str, *, channel: str) -> tuple[bool, bool, str]:
    engine = _engine()
    cls = _classify_shell_dialect(command, engine)
    risk = assess_risk(classification=cls, command=command, engine=engine)
    rev, cont = _props_from_tf(cls, risk, git_backed=False)
    return rev, cont, f"shell: {command[:60]} {_risk_tag(cls, risk)}"


def _classify_shell_dialect(command: str, engine: ClassificationEngine) -> TFClassification:
    """Dispatch to the bash / powershell / cmd classifier by lightweight sniffing.

    CodePlane actions do not carry an explicit dialect, so default to bash (matching
    the retired sh-guard classifier) and only switch on unambiguous PowerShell/cmd
    leading tokens.
    """
    head = command.strip().split(None, 1)[0].lower() if command.strip() else ""
    if head in _PWSH_TOOL_HINTS:
        return classify_powershell_command(command, engine=engine)
    if head in _CMD_TOOL_HINTS:
        return classify_cmd_command(command, engine=engine)
    return classify_shell(command, engine=engine)


def _targets(action: Action) -> list[str] | None:
    """Best-effort file targets for risk target-sensitivity scoring."""
    return [action.path] if action.path else None
