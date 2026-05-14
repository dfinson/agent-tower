"""Tests for backend.services.action_policy.checkpoint_service — CheckpointService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.action_policy.checkpoint_service import CheckpointService


@pytest.fixture()
def git_service():
    svc = AsyncMock()
    svc.tag = AsyncMock()
    svc.rev_parse = AsyncMock(return_value="abc123")
    svc.run_git = AsyncMock()
    return svc


@pytest.fixture()
def checkpoint_svc(git_service):
    return CheckpointService(git_service)


class TestNextSeq:
    def test_first_call(self, checkpoint_svc: CheckpointService):
        assert checkpoint_svc._next_seq("job-1") == 1

    def test_increments(self, checkpoint_svc: CheckpointService):
        assert checkpoint_svc._next_seq("job-1") == 1
        assert checkpoint_svc._next_seq("job-1") == 2
        assert checkpoint_svc._next_seq("job-1") == 3

    def test_independent_per_job(self, checkpoint_svc: CheckpointService):
        assert checkpoint_svc._next_seq("job-1") == 1
        assert checkpoint_svc._next_seq("job-2") == 1
        assert checkpoint_svc._next_seq("job-1") == 2


class TestCreate:
    @pytest.mark.asyncio()
    async def test_creates_tag(self, checkpoint_svc: CheckpointService, git_service):
        result = await checkpoint_svc.create("job-123456789012", "save before rm", cwd="/work")
        assert result.startswith("cp/job-12345678/1")
        git_service.tag.assert_awaited_once()
        call_args = git_service.tag.call_args
        assert call_args[0][0].startswith("cp/")
        assert call_args[1]["message"] == "save before rm"
        assert call_args[1]["cwd"] == "/work"

    @pytest.mark.asyncio()
    async def test_create_fallback_on_tag_failure(self, checkpoint_svc: CheckpointService, git_service):
        git_service.tag.side_effect = Exception("tag failed")
        git_service.rev_parse.return_value = "head-sha"
        result = await checkpoint_svc.create("job-123456789012", "save", cwd="/work")
        assert result == "head-sha"

    @pytest.mark.asyncio()
    async def test_create_fallback_both_fail(self, checkpoint_svc: CheckpointService, git_service):
        git_service.tag.side_effect = Exception("tag failed")
        git_service.rev_parse.side_effect = Exception("rev_parse failed")
        result = await checkpoint_svc.create("job-123456789012", "save", cwd="/work")
        assert result == ""


class TestRollback:
    @pytest.mark.asyncio()
    async def test_rollback_empty_ref(self, checkpoint_svc: CheckpointService):
        result = await checkpoint_svc.rollback("", cwd="/work")
        assert result is False

    @pytest.mark.asyncio()
    async def test_rollback_same_as_head(self, checkpoint_svc: CheckpointService, git_service):
        git_service.rev_parse.return_value = "abc123"
        result = await checkpoint_svc.rollback("abc123", cwd="/work")
        assert result is True

    @pytest.mark.asyncio()
    async def test_rollback_reverts(self, checkpoint_svc: CheckpointService, git_service):
        git_service.rev_parse.return_value = "head456"
        result = await checkpoint_svc.rollback("abc123", cwd="/work")
        assert result is True
        # Should call revert and commit
        calls = git_service.run_git.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == "revert"
        assert calls[1][0][0] == "commit"
