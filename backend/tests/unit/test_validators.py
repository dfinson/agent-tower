"""Tests for backend.validators — shared validation patterns."""

from __future__ import annotations

import pytest

from backend.validators import BRANCH_RE, REF_PATTERN, WORKTREE_RE


class TestRefPattern:
    @pytest.mark.parametrize(
        "ref",
        [
            "main",
            "feature/branch",
            "v1.0.0",
            "refs/heads/main",
            "a/b/c/d",
            "fix-123",
            "HEAD",
        ],
    )
    def test_valid_refs(self, ref):
        assert REF_PATTERN.match(ref) is not None

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            "branch name",
            "feat:branch",
            "a~b",
        ],
    )
    def test_invalid_refs(self, ref):
        assert REF_PATTERN.match(ref) is None


class TestBranchRe:
    @pytest.mark.parametrize(
        "branch",
        [
            "feat/add-login",
            "fix/bug-123",
            "chore/update-deps",
            "docs/readme-update",
            "test/add-coverage",
        ],
    )
    def test_valid_branches(self, branch):
        assert BRANCH_RE.match(branch) is not None

    @pytest.mark.parametrize(
        "branch",
        [
            "main",
            "feature/branch",
            "feat/",
            "feat/A-uppercase",
            "feat/-start-dash",
        ],
    )
    def test_invalid_branches(self, branch):
        assert BRANCH_RE.match(branch) is None


class TestWorktreeRe:
    @pytest.mark.parametrize(
        "name",
        [
            "my-worktree",
            "abc",
            "a-b-c-d",
            "123-test-456",
        ],
    )
    def test_valid_worktrees(self, name):
        assert WORKTREE_RE.match(name) is not None

    @pytest.mark.parametrize(
        "name",
        [
            "ab",  # too short
            "-bad",
            "bad-",
            "UPPERCASE",
            "",
        ],
    )
    def test_invalid_worktrees(self, name):
        assert WORKTREE_RE.match(name) is None
