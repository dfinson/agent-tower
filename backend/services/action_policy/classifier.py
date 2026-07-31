"""Action model + governance-derived classification result.

Input channels: file operations, SDK tools, MCP tools, shell commands.

The DECISION (what to do about an action) is delegated **wholesale** to
``traceforge.governance`` via :mod:`backend.services.action_policy.governance`.
This module only defines CodePlane's action model, the preset enum, and the
reshaped :class:`Classification` that surfaces TraceForge's native decision
(:class:`~traceforge.governance.RecommendedAction` + risk + reason code) to the
enforcement layer (router), the audit trail, and the UI. The retired
hand-rolled tier resolution / explicit-rule matching / cost promotion lived here
and have been deleted, not translated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from traceforge.governance import RecommendedAction

log = structlog.get_logger()


class Preset(StrEnum):
    autonomous = "autonomous"
    supervised = "supervised"
    locked = "locked"


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
    """Governance decision for an action, surfaced from TraceForge's ``SessionMeta``.

    ``recommended_action`` is TraceForge's native verdict; the enforcement layer
    acts on it directly (no CodePlane tier vocabulary). ``risk_score`` /
    ``risk_band`` come from the Assessor, ``effect`` / ``mechanism`` from the
    classifier, and ``reason_code`` from the matched rule (or ``"allow"`` when no
    rule fired and risk was below every threshold — an implicit allow).
    """

    recommended_action: RecommendedAction
    reason_code: str
    risk_score: int
    risk_band: str
    effect: str | None
    mechanism: str
    reason: str


@dataclass
class RepoPolicy:
    """In-memory policy loaded from DB at job start.

    Wholesale adoption slimmed this to the two settings CodePlane still owns: the
    ``preset`` (which selects a TraceForge governance profile) and the approval
    ``batch_window_seconds``. The retired path/action/cost rule tables and the
    MCP reversibility hints are gone — governance classifies natively.
    """

    preset: Preset = Preset.supervised
    batch_window_seconds: float = 5.0
    mcp_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
