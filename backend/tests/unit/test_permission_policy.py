"""Tests for is_git_reset_hard (backend.services.permission_policy)."""

from __future__ import annotations

import pytest

from backend.services.permission_policy import is_git_reset_hard


class TestIsGitResetHard:
    """is_git_reset_hard must detect all common git reset --hard patterns."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git reset --hard",
            "git reset --hard HEAD",
            "git reset --hard HEAD~1",
            "git reset --hard origin/main",
            "git reset HEAD --hard",
            "  git reset --hard  ",
            "cd /repo && git reset --hard HEAD",
            "git fetch origin && git reset --hard origin/main",
            "GIT reset --hard HEAD",  # case-insensitive
        ],
    )
    def test_detects_git_reset_hard(self, cmd: str) -> None:
        assert is_git_reset_hard(cmd), f"Expected detection for: {cmd!r}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "git reset HEAD",
            "git reset --soft HEAD",
            "git reset --mixed HEAD",
            "git status",
            "git checkout -- .",
            # quoted strings — the text is not a live command invocation
            "echo 'git reset --hard' is dangerous",
            'git commit -m "Document hard-gated commands (git reset --hard, merge, rebase)"',
            "git commit -m 'fix: mention git reset --hard in docs'",
            "grep 'hard' file.txt",
            "git reset",
        ],
    )
    def test_ignores_non_hard_reset(self, cmd: str) -> None:
        assert not is_git_reset_hard(cmd), f"Expected no detection for: {cmd!r}"
