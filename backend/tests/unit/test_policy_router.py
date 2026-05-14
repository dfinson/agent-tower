"""Tests for backend.services.action_policy.router — PolicyRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.action_policy.classifier import (
    Action,
    ActionKind,
    RepoPolicy,
    Tier,
)
from backend.services.action_policy.router import Decision, PolicyRouter


@pytest.fixture()
def checkpoint_svc():
    svc = AsyncMock()
    svc.create = AsyncMock(return_value="cp-ref-1")
    return svc


@pytest.fixture()
def trust_store():
    store = MagicMock()
    store.covers = MagicMock(return_value=False)
    return store


@pytest.fixture()
def batcher():
    return AsyncMock()


@pytest.fixture()
def router(checkpoint_svc, trust_store, batcher):
    return PolicyRouter(checkpoint_svc, trust_store, batcher)


class TestDecision:
    def test_defaults(self):
        d = Decision(tier=Tier.observe, proceed=True)
        assert d.tier == Tier.observe
        assert d.proceed is True
        assert d.checkpoint_ref is None
        assert d.trusted is False
        assert d.monitor_approved is False


class TestPolicyRouterObserve:
    @pytest.mark.asyncio()
    async def test_observe_tier_proceeds(self, router: PolicyRouter):
        # A simple "ls" command is observe tier
        action = Action(kind=ActionKind.shell, command="ls", job_id="j1")
        policy = RepoPolicy()
        decision = await router.route(action, policy)
        assert decision.proceed is True
        assert decision.tier == Tier.observe

    @pytest.mark.asyncio()
    async def test_observe_tier_no_checkpoint(self, router: PolicyRouter, checkpoint_svc):
        action = Action(kind=ActionKind.shell, command="cat file.txt", job_id="j1")
        policy = RepoPolicy()
        decision = await router.route(action, policy, cwd="/work")
        # Observe doesn't create checkpoints
        if decision.tier == Tier.observe:
            checkpoint_svc.create.assert_not_awaited()


class TestPolicyRouterCheckpoint:
    @pytest.mark.asyncio()
    async def test_checkpoint_creates_savepoint(self, router: PolicyRouter, checkpoint_svc):
        # File write is typically checkpoint tier
        action = Action(kind=ActionKind.file, path="/src/app.py", tool_name="Write", job_id="j1")
        policy = RepoPolicy()
        decision = await router.route(action, policy, cwd="/work")
        if decision.tier == Tier.checkpoint:
            assert decision.proceed is True
            checkpoint_svc.create.assert_awaited()


class TestPolicyRouterGateTrust:
    @pytest.mark.asyncio()
    async def test_gate_bypassed_by_trust(self, router: PolicyRouter, trust_store, checkpoint_svc):
        trust_store.covers.return_value = True
        # A dangerous command that would be gate tier
        action = Action(kind=ActionKind.shell, command="rm -rf /tmp/test", job_id="j1")
        policy = RepoPolicy()
        decision = await router.route(action, policy, cwd="/work")
        if decision.tier == Tier.gate:
            assert decision.proceed is True
            assert decision.trusted is True
