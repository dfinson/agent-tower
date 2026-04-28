"""Types, constants, and helpers for merge_service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.models.domain import GitMergeOutcome
from backend.services.git_service import GitError
from backend.validators import REF_PATTERN as _REF_PATTERN  # noqa: F401


class _MergeOutcome(StrEnum):
    """Result of a low-level checkout-and-merge attempt."""

    success = "success"
    conflict = "conflict"
    error = "error"


_PR_TITLE_MAX_PROMPT_LEN = 80
_CHERRY_PICK_ALREADY_APPLIED_PATTERNS = (
    "empty commit set passed",
    "the previous cherry-pick is now empty",
    "previous cherry-pick is now empty",
    "patch contents already upstream",
    "nothing to commit, working tree clean",
)


def _classify_cherry_pick_failure(exc: GitError) -> str:
    """Map cherry-pick failures without conflict markers to a user-facing error."""
    combined_message = "\n".join(part for part in (str(exc), exc.stderr) if part).lower()
    if any(pattern in combined_message for pattern in _CHERRY_PICK_ALREADY_APPLIED_PATTERNS):
        return (
            "Cherry-pick stopped because one or more branch commits are already present"
            " on the base branch; rebase the branch or create a PR"
        )
    return "Cherry-pick failed without conflict markers; check git configuration or hooks"


class MergeStatus(StrEnum):
    """Outcome status for a merge-back attempt."""

    merged = "merged"
    conflict = "conflict"
    pr_created = "pr_created"
    skipped = "skipped"
    error = "error"


@dataclass
class MergeResult:
    """Outcome of a merge-back attempt."""

    status: MergeStatus
    strategy: str | None = None  # ff_only | merge | pr
    pr_url: str | None = None
    conflict_files: list[str] | None = None
    error: str | None = None


# Persisted merge_status value for jobs whose branch has not yet been merged.
_NOT_MERGED = GitMergeOutcome.not_merged
