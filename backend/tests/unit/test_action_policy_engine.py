"""Tests for the action policy engine — cost rules, mid-job reload, cross-platform regex."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.events import DomainEvent, DomainEventKind
from backend.services.action_policy.batcher import ApprovalBatcher
from backend.services.action_policy.classifier import (
    Action,
    ActionKind,
    CostContext,
    Preset,
    RepoPolicy,
    Tier,
    _apply_cost_promotion,
    _safe_regex_search,
    classify,
)
from backend.services.event_bus import EventBus


# ---------------------------------------------------------------------------
# _apply_cost_promotion
# ---------------------------------------------------------------------------


class TestApplyCostPromotion:
    """Unit tests for cost rule tier promotion logic."""

    def test_no_rules_returns_current_tier(self) -> None:
        assert _apply_cost_promotion(Tier.observe, [], CostContext(job_spend_usd=100.0)) == Tier.observe

    def test_threshold_not_met_no_promotion(self) -> None:
        rules = [{"threshold_value": 10.0, "promote_to": "gate"}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=5.0)) == Tier.observe

    def test_threshold_met_promotes_to_gate(self) -> None:
        rules = [{"threshold_value": 10.0, "promote_to": "gate"}]
        result = _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=10.0))
        assert result == Tier.gate

    def test_threshold_met_promotes_to_checkpoint(self) -> None:
        rules = [{"threshold_value": 5.0, "promote_to": "checkpoint"}]
        result = _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=5.0))
        assert result == Tier.checkpoint

    def test_never_demotes(self) -> None:
        """A cost rule for checkpoint should not demote from gate."""
        rules = [{"threshold_value": 1.0, "promote_to": "checkpoint"}]
        result = _apply_cost_promotion(Tier.gate, rules, CostContext(job_spend_usd=100.0))
        assert result == Tier.gate

    def test_highest_promotion_wins(self) -> None:
        rules = [
            {"threshold_value": 5.0, "promote_to": "checkpoint"},
            {"threshold_value": 10.0, "promote_to": "gate"},
        ]
        result = _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=15.0))
        assert result == Tier.gate

    def test_none_threshold_skipped(self) -> None:
        rules = [{"threshold_value": None, "promote_to": "gate"}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=100.0)) == Tier.observe

    def test_none_promote_to_skipped(self) -> None:
        rules = [{"threshold_value": 1.0, "promote_to": None}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=100.0)) == Tier.observe

    def test_invalid_promote_to_skipped(self) -> None:
        rules = [{"threshold_value": 1.0, "promote_to": "nonexistent_tier"}]
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=100.0)) == Tier.observe

    def test_zero_threshold_triggers_on_any_spend(self) -> None:
        rules = [{"threshold_value": 0.0, "promote_to": "checkpoint"}]
        result = _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=0.0))
        assert result == Tier.checkpoint

    def test_exact_threshold_boundary(self) -> None:
        rules = [{"threshold_value": 5.0, "promote_to": "gate"}]
        # Exactly at threshold
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=5.0)) == Tier.gate
        # Just below
        assert _apply_cost_promotion(Tier.observe, rules, CostContext(job_spend_usd=4.99)) == Tier.observe


# ---------------------------------------------------------------------------
# classify with cost context
# ---------------------------------------------------------------------------


class TestClassifyWithCostContext:
    """Integration tests for classify() with cost rule promotion."""

    @staticmethod
    def _policy_with_cost_rules(rules: list[dict[str, Any]]) -> RepoPolicy:
        return RepoPolicy(preset=Preset.autonomous, cost_rules=rules)

    def test_classify_without_cost_context(self) -> None:
        policy = self._policy_with_cost_rules([{"threshold_value": 0.0, "promote_to": "gate"}])
        action = Action(kind=ActionKind.file, path="a.py")
        result = classify(action, policy, cost=None)
        # Autonomous preset + contained file → observe, no cost promotion without context
        assert result.tier == Tier.observe

    def test_classify_with_cost_context_promotes(self) -> None:
        policy = self._policy_with_cost_rules([{"threshold_value": 5.0, "promote_to": "gate"}])
        action = Action(kind=ActionKind.file, path="a.py")
        result = classify(action, policy, cost=CostContext(job_spend_usd=10.0))
        assert result.tier == Tier.gate
        assert "cost promotion" in result.reason

    def test_classify_cost_does_not_override_explicit_rule_upward(self) -> None:
        """Cost rules run after explicit rules but can still promote upward."""
        policy = RepoPolicy(
            preset=Preset.autonomous,
            path_rules=[{"path_pattern": "*.py", "tier": "observe"}],
            cost_rules=[{"threshold_value": 1.0, "promote_to": "gate"}],
        )
        action = Action(kind=ActionKind.file, path="a.py")
        result = classify(action, policy, cost=CostContext(job_spend_usd=5.0))
        # Explicit rule says observe, but cost rule promotes to gate
        assert result.tier == Tier.gate


# ---------------------------------------------------------------------------
# _safe_regex_search (cross-platform)
# ---------------------------------------------------------------------------


class TestSafeRegexSearch:
    def test_simple_match(self) -> None:
        assert _safe_regex_search(r"foo", "foobar") is True

    def test_simple_no_match(self) -> None:
        assert _safe_regex_search(r"baz", "foobar") is False

    def test_invalid_regex_returns_false(self) -> None:
        assert _safe_regex_search(r"[invalid", "test") is False

    def test_complex_pattern(self) -> None:
        assert _safe_regex_search(r"^git\s+push", "git push origin main") is True

    def test_empty_pattern_matches(self) -> None:
        assert _safe_regex_search(r"", "anything") is True

    def test_empty_text_no_match(self) -> None:
        assert _safe_regex_search(r"something", "") is False


# ---------------------------------------------------------------------------
# ApprovalBatcher.set_batch_window
# ---------------------------------------------------------------------------


class TestBatcherSetWindow:
    def test_set_batch_window_updates_value(self) -> None:
        bus = EventBus()
        batcher = ApprovalBatcher(event_bus=bus, batch_window_seconds=5.0)
        assert batcher._batch_window == 5.0
        batcher.set_batch_window(10.0)
        assert batcher._batch_window == 10.0

    def test_set_batch_window_affects_new_batches(self) -> None:
        bus = EventBus()
        batcher = ApprovalBatcher(event_bus=bus, batch_window_seconds=5.0)
        batcher.set_batch_window(2.0)
        assert batcher._batch_window == 2.0


# ---------------------------------------------------------------------------
# _get_cost_context
# ---------------------------------------------------------------------------


class TestGetCostContext:
    """Tests for BaseAgentAdapter._get_cost_context."""

    @pytest.mark.asyncio
    async def test_returns_cost_context_with_spend(self) -> None:
        from backend.services.base_adapter import BaseAgentAdapter

        adapter = _make_adapter_with_db_session()
        summary = {"total_cost_usd": 12.5}

        with patch(
            "backend.persistence.telemetry_summary_repo.TelemetrySummaryRepository.get",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            result = await adapter._get_cost_context("job-1")
        assert result is not None
        assert result.job_spend_usd == 12.5

    @pytest.mark.asyncio
    async def test_returns_cost_context_with_zero_spend(self) -> None:
        from backend.services.base_adapter import BaseAgentAdapter

        adapter = _make_adapter_with_db_session()
        summary = {"total_cost_usd": 0.0}

        with patch(
            "backend.persistence.telemetry_summary_repo.TelemetrySummaryRepository.get",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            result = await adapter._get_cost_context("job-1")
        # 0.0 is a valid cost — should NOT return None
        assert result is not None
        assert result.job_spend_usd == 0.0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_summary(self) -> None:
        from backend.services.base_adapter import BaseAgentAdapter

        adapter = _make_adapter_with_db_session()

        with patch(
            "backend.persistence.telemetry_summary_repo.TelemetrySummaryRepository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await adapter._get_cost_context("job-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self) -> None:
        from sqlalchemy.exc import DBAPIError

        from backend.services.base_adapter import BaseAgentAdapter

        adapter = _make_adapter_with_db_session()

        with patch(
            "backend.persistence.telemetry_summary_repo.TelemetrySummaryRepository.get",
            new_callable=AsyncMock,
            side_effect=DBAPIError("", "", Exception()),
        ):
            result = await adapter._get_cost_context("job-1")
        assert result is None


# ---------------------------------------------------------------------------
# _on_policy_settings_changed
# ---------------------------------------------------------------------------


class TestOnPolicySettingsChanged:
    """Tests for RuntimeService._on_policy_settings_changed."""

    @pytest.mark.asyncio
    async def test_ignores_non_policy_events(self) -> None:
        svc = _make_runtime_service()
        event = DomainEvent(
            event_id="e1",
            job_id="j1",
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.job_created,
            payload={},
        )
        # Should return without error
        await svc._on_policy_settings_changed(event)

    @pytest.mark.asyncio
    async def test_no_op_when_no_running_jobs(self) -> None:
        svc = _make_runtime_service()
        event = _make_policy_event()
        # Empty _policy_routers → should return without DB access
        await svc._on_policy_settings_changed(event)

    @pytest.mark.asyncio
    async def test_reloads_policy_for_running_jobs(self) -> None:
        svc = _make_runtime_service()

        # Set up a fake running job with policy
        mock_router = MagicMock()
        mock_router._trust = MagicMock()
        mock_router._trust.load = AsyncMock()
        svc._policy_routers["job-1"] = mock_router

        mock_batcher = MagicMock()
        svc._policy_batchers["job-1"] = mock_batcher

        mock_adapter = MagicMock()
        svc._adapter_registry._adapters = {"claude": mock_adapter}

        # Mock DB calls
        mock_session = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.get_config = AsyncMock(return_value={"preset": "strict", "batch_window_seconds": 3.0})
        mock_repo.list_path_rules = AsyncMock(return_value=[])
        mock_repo.list_action_rules = AsyncMock(return_value=[])
        mock_repo.list_cost_rules = AsyncMock(return_value=[])
        mock_repo.list_mcp_configs = AsyncMock(return_value=[])

        # Mock JobRepository for per-job preset lookup
        mock_job = MagicMock()
        mock_job.preset = "strict"
        mock_job_repo = MagicMock()
        mock_job_repo.get = AsyncMock(return_value=mock_job)

        with patch("backend.persistence.policy_repo.PolicyRepository", return_value=mock_repo), \
             patch("backend.persistence.job_repo.JobRepository", return_value=mock_job_repo):
            svc._session_factory = _make_session_factory(mock_session)
            event = _make_policy_event()
            await svc._on_policy_settings_changed(event)

        # Trust store reloaded
        mock_router._trust.load.assert_awaited_once()
        # Batcher window updated
        mock_batcher.set_batch_window.assert_called_once_with(3.0)
        # Adapter policy updated
        mock_adapter.update_repo_policy.assert_called_once()
        call_args = mock_adapter.update_repo_policy.call_args
        assert call_args[0][0] == "job-1"  # job_id
        policy = call_args[0][1]
        assert policy.preset == Preset.strict

    @pytest.mark.asyncio
    async def test_skips_finished_jobs(self) -> None:
        svc = _make_runtime_service()

        # Job exists in routers at iteration start but removed mid-iteration
        mock_adapter = MagicMock()
        svc._adapter_registry._adapters = {"claude": mock_adapter}

        mock_repo = MagicMock()
        mock_repo.get_config = AsyncMock(return_value={"preset": "supervised", "batch_window_seconds": 5.0})
        mock_repo.list_path_rules = AsyncMock(return_value=[])
        mock_repo.list_action_rules = AsyncMock(return_value=[])
        mock_repo.list_cost_rules = AsyncMock(return_value=[])
        mock_repo.list_mcp_configs = AsyncMock(return_value=[])

        # Mock JobRepository for per-job preset lookup
        mock_job = MagicMock()
        mock_job.preset = "supervised"
        mock_job_repo = MagicMock()
        mock_job_repo.get = AsyncMock(return_value=mock_job)

        # Job is in routers when we take the snapshot...
        svc._policy_routers["job-1"] = MagicMock()

        mock_session = AsyncMock()
        with patch("backend.persistence.policy_repo.PolicyRepository", return_value=mock_repo), \
             patch("backend.persistence.job_repo.JobRepository", return_value=mock_job_repo):
            svc._session_factory = _make_session_factory(mock_session)
            # ...but remove it before the per-job loop runs
            # We simulate by patching __contains__ to return False
            svc._policy_routers.clear()
            event = _make_policy_event()
            await svc._on_policy_settings_changed(event)

        # No adapter update should have been called
        mock_adapter.update_repo_policy.assert_not_called()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy_event() -> DomainEvent:
    return DomainEvent(
        event_id="e-policy",
        job_id="",
        timestamp=datetime.now(UTC),
        kind=DomainEventKind.policy_settings_changed,
        payload={},
    )


def _make_session_factory(mock_session: AsyncMock) -> Any:
    """Create a mock async session factory."""
    factory = MagicMock()

    class _FakeCtx:
        async def __aenter__(self):
            return mock_session
        async def __aexit__(self, *args):
            pass

    factory.return_value = _FakeCtx()
    # Make it callable like async_sessionmaker
    factory.side_effect = None
    factory.__call__ = lambda self: _FakeCtx()
    return factory


def _make_adapter_with_db_session() -> Any:
    """Create a minimal BaseAgentAdapter-like object for testing _get_cost_context."""
    from contextlib import asynccontextmanager

    from backend.services.base_adapter import BaseAgentAdapter

    class _TestAdapter(BaseAgentAdapter):
        def __init__(self) -> None:
            # Bypass normal __init__
            self._event_bus = None
            self._approval_service = None
            self._session_factory_ref = MagicMock()
            self._policy_router = {}
            self._repo_policies = {}
            self._worktree_paths = {}

        def _db_session(self):
            @asynccontextmanager
            async def _ctx():
                yield MagicMock()
            return _ctx()

        async def create_session(self, *a: Any, **kw: Any) -> Any: ...
        async def send_message(self, *a: Any, **kw: Any) -> Any: ...
        async def abort_session(self, *a: Any, **kw: Any) -> Any: ...
        async def complete(self, *a: Any, **kw: Any) -> Any: ...
        async def stream_events(self, *a: Any, **kw: Any) -> Any: ...

    return _TestAdapter()


def _make_runtime_service() -> Any:
    """Create a minimal RuntimeService for testing event handlers."""
    from backend.services.runtime_service import RuntimeService

    svc = object.__new__(RuntimeService)
    svc._event_bus = EventBus()
    svc._policy_routers = {}
    svc._policy_batchers = {}
    svc._adapter_registry = MagicMock()
    svc._adapter_registry._adapters = {}
    svc._session_factory = MagicMock()
    return svc
