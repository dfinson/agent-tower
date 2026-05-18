"""Secondary session domain model.

Unified representation for all non-primary agent sessions: preflight curator,
sidecars, monitors, memory extractors.  Each session has a lifecycle (running →
completed/failed/timeout) and a stream of entries (reasoning, tool calls,
output chunks, errors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SecondarySessionKind(str, Enum):
    preflight = "preflight"
    sidecar = "sidecar"
    monitor = "monitor"
    extractor = "extractor"


class SecondarySessionStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


class EntryKind(str, Enum):
    reasoning = "reasoning"
    tool_call = "tool_call"
    output = "output"
    error = "error"


@dataclass
class SecondarySessionEntry:
    """One unit of activity inside a secondary session."""

    seq: int
    timestamp: datetime
    kind: EntryKind
    content: str
    # tool_call-specific fields
    tool_name: str | None = None
    tool_args: str | None = None
    duration_ms: float | None = None


@dataclass
class SecondarySession:
    """A complete secondary session lifecycle."""

    id: str
    job_id: str
    kind: SecondarySessionKind
    name: str
    icon: str
    status: SecondarySessionStatus
    started_at: datetime
    completed_at: datetime | None = None
    entries: list[SecondarySessionEntry] = field(default_factory=list)
    output: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
