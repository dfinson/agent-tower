"""Checkpoint service — git savepoints for checkpoint and gate tier actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.git_service import GitService

log = structlog.get_logger()


class CheckpointService:
    """Creates lightweight git tags as savepoints before risky actions.

    Rollback creates a revert commit (history-preserving). It does not reset.
    """

    def __init__(self, git_service: GitService) -> None:
        self._git = git_service
        self._counters: dict[str, int] = {}  # job_id → seq

    def _next_seq(self, job_id: str) -> int:
        n = self._counters.get(job_id, 0) + 1
        self._counters[job_id] = n
        return n

    async def create(
        self,
        job_id: str,
        action_summary: str,
        *,
        cwd: str,
    ) -> str:
        """Create a lightweight git tag as a savepoint. Returns the tag name."""
        seq = self._next_seq(job_id)
        tag = f"cp/{job_id[:12]}/{seq}"
        try:
            await self._git.tag(tag, message=action_summary, cwd=cwd)
        except Exception:
            log.warning("checkpoint_create_failed", job_id=job_id, tag=tag, exc_info=True)
            # Fall back to HEAD ref
            try:
                return await self._git.rev_parse("HEAD", cwd=cwd)
            except Exception:
                return ""
        log.debug("checkpoint_created", job_id=job_id, tag=tag)
        return tag

    async def rollback(
        self,
        checkpoint_ref: str,
        *,
        cwd: str,
    ) -> bool:
        """Revert all commits since checkpoint. Preserves history via revert.

        Returns True if rollback succeeded.
        """
        if not checkpoint_ref:
            return False
        try:
            # Get current HEAD
            head = await self._git.rev_parse("HEAD", cwd=cwd)
            if head == checkpoint_ref:
                return True  # Nothing to revert

            # Revert range: checkpoint..HEAD
            await self._git.run_git(
                "revert", "--no-commit", f"{checkpoint_ref}..HEAD",
                cwd=cwd,
            )
            await self._git.run_git(
                "commit", "-m", f"Rollback to checkpoint {checkpoint_ref}",
                cwd=cwd,
            )
            log.info("checkpoint_rollback_success", ref=checkpoint_ref)
            return True
        except Exception:
            log.error("checkpoint_rollback_failed", ref=checkpoint_ref, exc_info=True)
            # Try to abort the revert if it's in progress
            try:
                await self._git.run_git("revert", "--abort", cwd=cwd)
            except Exception:
                pass
            return False

    def cleanup_job(self, job_id: str) -> None:
        """Remove counter state for a completed job."""
        self._counters.pop(job_id, None)
