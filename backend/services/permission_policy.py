"""Permission policy — hard-gated command detection.

Only ``is_git_reset_hard`` and the ``PermissionRequest`` dataclass survive
from the legacy rule-based permission system.  All runtime policy decisions
are now made by the action_policy router/classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()


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
# Hard-blocked commands — always require explicit operator approval,
# regardless of trust level.
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

    Quoted string contents (e.g. a ``git commit -m "..."`` message) are
    stripped before matching so that literal text inside arguments does not
    cause false positives.
    """
    return bool(_GIT_RESET_HARD_RE.search(_strip_quoted_strings(command)))
