"""Tests for action_policy.trust_store — grant matching and async persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.services.action_policy.classifier import Action
from backend.services.action_policy.trust_store import (
    TrustGrant,
    TrustStore,
    _grant_matches,
)


def _make_action(**kw: object) -> Action:
    """Build a minimal Action-like object for testing grant matching."""
    from backend.services.action_policy.classifier import ActionKind

    defaults: dict[str, object] = {
        "kind": ActionKind.shell,
        "path": None,
        "command": None,
        "mcp_server": None,
        "mcp_tool": None,
        "job_id": "j1",
    }
    defaults.update(kw)
    return Action(**defaults)  # type: ignore[arg-type]


def _make_grant(**kw: object) -> TrustGrant:
    defaults: dict[str, object] = {
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


# ---------------------------------------------------------------------------
# TrustStore.load (async)
# ---------------------------------------------------------------------------


def _fake_session_factory(rows: list[dict]) -> Any:
    """Build a mock async session factory that returns rows from PolicyRepository."""
    from unittest.mock import AsyncMock, MagicMock

    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)
    session_mock.commit = AsyncMock()

    factory = MagicMock(return_value=session_mock)

    return factory, session_mock, rows


@pytest.mark.asyncio
class TestTrustStoreLoad:
    async def test_load_active_grants(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        future_dt = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        rows = [
            {
                "id": "g1",
                "kinds": ["shell"],
                "path_pattern": None,
                "excludes": [],
                "command_pattern": None,
                "mcp_server": None,
                "mcp_tool": None,
                "job_id": "j1",
                "expires_at": future_dt,
                "reason": "test",
            },
        ]

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_trust_grants = AsyncMock(return_value=rows)
            await store.load()

        assert "g1" in store._grants
        assert store._grants["g1"].kinds == {"shell"}

    async def test_load_skips_expired(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        past_dt = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        rows = [
            {
                "id": "expired",
                "kinds": ["shell"],
                "expires_at": past_dt,
            },
        ]

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_trust_grants = AsyncMock(return_value=rows)
            await store.load()

        assert "expired" not in store._grants

    async def test_load_handles_invalid_expires_at(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        rows = [
            {
                "id": "bad-date",
                "kinds": ["shell"],
                "expires_at": "not-a-date",
            },
        ]

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_trust_grants = AsyncMock(return_value=rows)
            await store.load()

        # Invalid expires_at logged and grant still loaded (expires=None → active)
        assert "bad-date" in store._grants


# ---------------------------------------------------------------------------
# TrustStore.create (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTrustStoreCreate:
    async def test_create_persists_and_caches(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.create_trust_grant = AsyncMock()
            grant = await store.create(kinds={"shell"}, reason="test")

        assert grant.id in store._grants
        assert grant.kinds == {"shell"}
        assert grant.reason == "test"


# ---------------------------------------------------------------------------
# TrustStore.revoke (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTrustStoreRevoke:
    async def test_revoke_removes_from_db_and_cache(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        grant = _make_grant(id="g1")
        store._grants = {grant.id: grant}

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.delete_trust_grant = AsyncMock(return_value=True)
            deleted = await store.revoke("g1")

        assert deleted is True
        assert "g1" not in store._grants

    async def test_revoke_nonexistent(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.delete_trust_grant = AsyncMock(return_value=False)
            deleted = await store.revoke("nonexistent")

        assert deleted is False


# ---------------------------------------------------------------------------
# TrustStore.revoke_by_job (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTrustStoreRevokeByJob:
    async def test_revokes_job_scoped_grants(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        g1 = _make_grant(id="g1", job_id="j1")
        g2 = _make_grant(id="g2", job_id="j1")
        g3 = _make_grant(id="g3", job_id="j2")
        store._grants = {g1.id: g1, g2.id: g2, g3.id: g3}

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.delete_trust_grant = AsyncMock(return_value=True)
            count = await store.revoke_by_job("j1")

        assert count == 2
        assert "g1" not in store._grants
        assert "g2" not in store._grants
        assert "g3" in store._grants

    async def test_revoke_by_job_no_matches(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        count = await store.revoke_by_job("j99")
        assert count == 0


# ---------------------------------------------------------------------------
# TrustStore.create_from_action (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTrustStoreCreateFromAction:
    async def test_shell_action_creates_anchored_regex(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.services.action_policy.classifier import ActionKind

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        action = _make_action(kind=ActionKind.shell, command="git status")

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.create_trust_grant = AsyncMock()
            grant = await store.create_from_action(action, reason="user approved")

        assert grant.command_pattern == "^git\\ status$"
        assert grant.kinds == {"shell"}

    async def test_file_action_escapes_glob_chars(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.services.action_policy.classifier import ActionKind

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        action = _make_action(kind=ActionKind.file, path="src/[test]/*.py")

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.create_trust_grant = AsyncMock()
            grant = await store.create_from_action(action, reason="safe")

        # Glob metacharacters are escaped using [ch] patterns
        # src/[test]/*.py → src/[[]test[]]]/[*].py
        assert grant.path_pattern is not None
        assert grant.kinds == {"write"}

    async def test_mcp_action_creates_server_tool_scoped_grant(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.services.action_policy.classifier import ActionKind

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        action = _make_action(
            kind=ActionKind.mcp_tool,
            mcp_server="coderecon",
            mcp_tool="recon",
        )

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.create_trust_grant = AsyncMock()
            grant = await store.create_from_action(action)

        assert grant.mcp_server == "coderecon"
        assert grant.mcp_tool == "recon"
        assert grant.kinds == {"mcp"}

    async def test_create_from_action_with_ttl(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.services.action_policy.classifier import ActionKind

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=None)
        session_mock.commit = AsyncMock()
        factory = MagicMock(return_value=session_mock)

        store = TrustStore(factory)
        store._grants = {}

        action = _make_action(kind=ActionKind.shell, command="ls")

        with patch("backend.persistence.policy_repo.PolicyRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.create_trust_grant = AsyncMock()
            grant = await store.create_from_action(action, ttl_hours=2)

        assert grant.expires_at is not None
        remaining = (grant.expires_at - datetime.now(UTC)).total_seconds()
        assert remaining > 7000  # ~2 hours minus test execution time
