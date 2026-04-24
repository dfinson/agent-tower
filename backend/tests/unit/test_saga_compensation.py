"""Saga compensation tests for job creation.

Tests that when worktree creation fails during setup_workspace,
the job transitions to 'failed' state with a failure reason.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.domain import JobSpec, JobState
from backend.services.git_service import GitError
from backend.services.job_service import JobService


def _make_config(**overrides: Any) -> Any:
    """Create a minimal CPLConfig mock."""
    config = MagicMock()
    config.repos = ["/repos/test"]
    config.runtime.default_sdk = "copilot"
    config.runtime.max_concurrent_jobs = 5
    return config


class TestJobCreationCompensation:
    """Job transitions to failed when worktree creation fails during setup."""

    @pytest.mark.asyncio
    async def test_worktree_failure_transitions_to_failed(self) -> None:
        """If create_worktree fails during setup_workspace, job goes to failed."""
        job_repo = AsyncMock()
        job_repo.list_ids = AsyncMock(return_value=set())

        # Mock a job in preparing state
        mock_job = MagicMock()
        mock_job.id = "fix-bug"
        mock_job.state = JobState.preparing
        mock_job.repo = "/repos/test"
        mock_job.base_ref = "main"
        mock_job.branch = None
        mock_job.worktree_name = "fix-bug"
        job_repo.get = AsyncMock(return_value=mock_job)
        job_repo.create = AsyncMock()
        job_repo.update_state = AsyncMock()
        job_repo.update_failure_reason = AsyncMock()

        git_service = AsyncMock()
        git_service.get_default_branch = AsyncMock(return_value="main")
        git_service.create_worktree = AsyncMock(side_effect=GitError("worktree failed"))

        config = _make_config()

        svc = JobService(
            job_repo=job_repo,
            git_service=git_service,
            config=config,
        )

        result = await svc.setup_workspace("fix-bug")

        # Job should be marked as failed
        job_repo.update_state.assert_called_once()
        assert job_repo.update_state.call_args[0][1] == JobState.failed
        job_repo.update_failure_reason.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_failure_during_create_raises(self) -> None:
        """If job_repo.create() fails, the error propagates (no worktree to clean up)."""
        job_repo = AsyncMock()
        job_repo.list_ids = AsyncMock(return_value=set())
        job_repo.get = AsyncMock(return_value=None)
        job_repo.create = AsyncMock(side_effect=Exception("DB write failed"))

        git_service = AsyncMock()
        git_service.get_default_branch = AsyncMock(return_value="main")

        config = _make_config()

        svc = JobService(
            job_repo=job_repo,
            git_service=git_service,
            config=config,
        )

        with (
            patch.object(svc, "validate_repo", return_value="/repos/test"),
            pytest.raises(Exception, match="DB write failed"),
        ):
            await svc.create_job(JobSpec(repo="/repos/test", prompt="Fix the bug"))

        # No worktree was created, so no cleanup needed
        git_service.create_worktree.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_creation_returns_preparing(self) -> None:
        """Normal job creation returns job in preparing state without worktree."""
        job_repo = AsyncMock()
        job_repo.list_ids = AsyncMock(return_value=set())
        job_repo.create = AsyncMock(return_value=None)

        git_service = AsyncMock()
        git_service.get_default_branch = AsyncMock(return_value="main")
        git_service.list_branches = AsyncMock(return_value=set())
        git_service.list_worktree_names = AsyncMock(return_value=set())

        config = _make_config()

        svc = JobService(
            job_repo=job_repo,
            git_service=git_service,
            config=config,
        )

        with patch.object(svc, "validate_repo", return_value="/repos/test"):
            job = await svc.create_job(JobSpec(repo="/repos/test", prompt="Fix the bug"))

        assert job.state == JobState.preparing
        # No worktree created during create_job phase
        git_service.create_worktree.assert_not_called()
