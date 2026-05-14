"""Tests for action_policy.trust_store — grant matching logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.action_policy.trust_store import (
    TrustGrant,
    TrustStore,
    _grant_matches,
)


def _make_action(**kw):
    """Build a minimal Action-like object for testing grant matching."""
    from backend.services.action_policy.classifier import Action, ActionKind

    defaults = {
        "kind": ActionKind.shell,
        "path": None,
        "command": None,
        "mcp_server": None,
        "mcp_tool": None,
        "job_id": "j1",
    }
    defaults.update(kw)
    return Action(**defaults)


def _make_grant(**kw) -> TrustGrant:
    defaults = {
        "id": "g1",
        "kinds": {"shell"},
        "path_pattern": None,
        "excludes": [],
        "command_pattern": None,
        "mcp_server": None,
        "mcp_tool": None,
        "job_id": None,
        "expires_at": None,
    }
    defaults.update(kw)
    return TrustGrant(**defaults)


# ---------------------------------------------------------------------------
# _grant_matches
# ---------------------------------------------------------------------------


class TestGrantMatches:
    def test_basic_kind_match(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"shell"})
        action = _make_action(kind=ActionKind.shell)
        assert _grant_matches(grant, action) is True

    def test_kind_mismatch(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"write"})
        action = _make_action(kind=ActionKind.shell)
        assert _grant_matches(grant, action) is False

    def test_job_scope_match(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"shell"}, job_id="j1")
        action = _make_action(kind=ActionKind.shell, job_id="j1")
        assert _grant_matches(grant, action) is True

    def test_job_scope_mismatch(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"shell"}, job_id="j2")
        action = _make_action(kind=ActionKind.shell, job_id="j1")
        assert _grant_matches(grant, action) is False

    def test_path_pattern_match(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"write"}, path_pattern="src/*.py")
        action = _make_action(kind=ActionKind.file, path="src/main.py")
        assert _grant_matches(grant, action) is True

    def test_path_pattern_no_match(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"write"}, path_pattern="src/*.py")
        action = _make_action(kind=ActionKind.file, path="tests/main.py")
        assert _grant_matches(grant, action) is False

    def test_path_excludes(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"write"}, path_pattern="*", excludes=["*.secret"])
        action = _make_action(kind=ActionKind.file, path="config.secret")
        assert _grant_matches(grant, action) is False

    def test_command_pattern_match(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"shell"}, command_pattern=r"^git status$")
        action = _make_action(kind=ActionKind.shell, command="git status")
        assert _grant_matches(grant, action) is True

    def test_command_pattern_no_match(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"shell"}, command_pattern=r"^git status$")
        action = _make_action(kind=ActionKind.shell, command="git push")
        assert _grant_matches(grant, action) is False

    def test_mcp_server_scope(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"mcp"}, mcp_server="coderecon")
        action = _make_action(kind=ActionKind.mcp_tool, mcp_server="coderecon", mcp_tool="recon")
        assert _grant_matches(grant, action) is True

    def test_mcp_server_mismatch(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"mcp"}, mcp_server="coderecon")
        action = _make_action(kind=ActionKind.mcp_tool, mcp_server="other")
        assert _grant_matches(grant, action) is False

    def test_mcp_tool_scope(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"mcp"}, mcp_server="coderecon", mcp_tool="recon")
        action = _make_action(kind=ActionKind.mcp_tool, mcp_server="coderecon", mcp_tool="recon")
        assert _grant_matches(grant, action) is True

    def test_mcp_tool_mismatch(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"mcp"}, mcp_server="coderecon", mcp_tool="recon")
        action = _make_action(kind=ActionKind.mcp_tool, mcp_server="coderecon", mcp_tool="other_tool")
        assert _grant_matches(grant, action) is False

    def test_no_path_returns_false_with_path_pattern(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        grant = _make_grant(kinds={"write"}, path_pattern="*.py")
        action = _make_action(kind=ActionKind.file, path=None)
        assert _grant_matches(grant, action) is False


# ---------------------------------------------------------------------------
# TrustStore.covers
# ---------------------------------------------------------------------------


class TestTrustStoreCovers:
    def test_no_grants_returns_false(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        store = TrustStore.__new__(TrustStore)
        store._grants = {}
        action = _make_action(kind=ActionKind.shell)
        assert store.covers(action) is False

    def test_matching_grant_returns_true(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        store = TrustStore.__new__(TrustStore)
        grant = _make_grant(kinds={"shell"})
        store._grants = {grant.id: grant}
        action = _make_action(kind=ActionKind.shell)
        assert store.covers(action) is True

    def test_expired_grant_cleaned_up(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        store = TrustStore.__new__(TrustStore)
        grant = _make_grant(
            kinds={"shell"},
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        store._grants = {grant.id: grant}
        action = _make_action(kind=ActionKind.shell)
        assert store.covers(action) is False
        assert grant.id not in store._grants

    def test_active_grant_not_cleaned_up(self) -> None:
        from backend.services.action_policy.classifier import ActionKind

        store = TrustStore.__new__(TrustStore)
        grant = _make_grant(
            kinds={"shell"},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        store._grants = {grant.id: grant}
        action = _make_action(kind=ActionKind.shell)
        assert store.covers(action) is True
        assert grant.id in store._grants


# ---------------------------------------------------------------------------
# TrustStore.list_active
# ---------------------------------------------------------------------------


class TestTrustStoreListActive:
    def test_filters_expired(self) -> None:
        store = TrustStore.__new__(TrustStore)
        active = _make_grant(id="active", expires_at=datetime.now(UTC) + timedelta(hours=1))
        expired = _make_grant(id="expired", expires_at=datetime.now(UTC) - timedelta(hours=1))
        store._grants = {active.id: active, expired.id: expired}
        result = store.list_active()
        assert len(result) == 1
        assert result[0].id == "active"

    def test_no_expiry_included(self) -> None:
        store = TrustStore.__new__(TrustStore)
        grant = _make_grant(id="forever", expires_at=None)
        store._grants = {grant.id: grant}
        assert len(store.list_active()) == 1
