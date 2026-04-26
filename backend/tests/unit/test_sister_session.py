"""Tests for backend.services.sister_session — session pool, lifecycle, metrics.

Covers SisterSession (wrapper), SisterSessionManager pool management,
warm/adopt/release lifecycle, metrics, and orphan cleanup.
"""

from __future__ import annotations

import asyncio
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.sister_session import (
    SisterSession,
    SisterSessionManager,
    _UTILITY_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CompletionResult = namedtuple("_CompletionResult", ["text", "input_tokens", "output_tokens", "cost_usd"])


def _mock_adapter(text: str = "ok", latency: float = 0.0) -> MagicMock:
    """Return a mock adapter whose complete() returns a result namedtuple."""
    adapter = MagicMock()
    adapter.complete = AsyncMock(
        return_value=_CompletionResult(text=text, input_tokens=10, output_tokens=5, cost_usd=0.001)
    )
    return adapter


def _make_manager(adapter=None, pool_size: int = 2) -> SisterSessionManager:
    """Create a SisterSessionManager with a mock adapter."""
    if adapter is None:
        adapter = _mock_adapter()
    mgr = SisterSessionManager(adapter, model="test-model", pool_size=pool_size)
    return mgr


# ===================================================================
# SisterSession wrapper
# ===================================================================


class TestSisterSession:
    @pytest.mark.asyncio
    async def test_first_call_prepends_system_prompt(self) -> None:
        adapter = _mock_adapter()
        session = SisterSession(adapter)
        await session.complete("hello")
        call_args = adapter.complete.call_args[0][0]
        assert _UTILITY_SYSTEM_PROMPT in call_args
        assert "hello" in call_args

    @pytest.mark.asyncio
    async def test_second_call_no_system_prompt(self) -> None:
        adapter = _mock_adapter()
        session = SisterSession(adapter)
        await session.complete("first")
        adapter.complete.reset_mock()
        await session.complete("second")
        call_args = adapter.complete.call_args[0][0]
        assert _UTILITY_SYSTEM_PROMPT not in call_args
        assert call_args == "second"

    @pytest.mark.asyncio
    async def test_metrics_updated(self) -> None:
        adapter = _mock_adapter()
        session = SisterSession(adapter)
        await session.complete("test")
        assert session.call_count == 1
        assert session.total_input_tokens == 10
        assert session.total_output_tokens == 5
        assert session.total_cost_usd == 0.001
        assert session.last_call_at is not None
        assert session.total_latency_ms > 0

    @pytest.mark.asyncio
    async def test_timeout_retries_once(self) -> None:
        adapter = MagicMock()
        call_count = 0

        async def flaky_complete(prompt: str) -> _CompletionResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(10)  # will be cancelled by timeout
            return _CompletionResult(text="ok", input_tokens=1, output_tokens=1, cost_usd=0)

        adapter.complete = flaky_complete
        session = SisterSession(adapter)
        result = await session.complete("test", timeout=0.05)
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_exhausted_raises(self) -> None:
        adapter = MagicMock()

        async def slow_complete(prompt: str) -> _CompletionResult:
            await asyncio.sleep(10)
            return _CompletionResult(text="ok", input_tokens=0, output_tokens=0, cost_usd=0)

        adapter.complete = slow_complete
        session = SisterSession(adapter)
        with pytest.raises(TimeoutError):
            await session.complete("test", timeout=0.05)

    def test_reset_metrics(self) -> None:
        adapter = _mock_adapter()
        session = SisterSession(adapter)
        session.call_count = 5
        session.total_latency_ms = 100.0
        session.total_input_tokens = 50
        session.total_output_tokens = 25
        session.total_cost_usd = 0.01
        session.last_call_at = 123.0

        session._reset_metrics()

        assert session.call_count == 0
        assert session.total_latency_ms == 0.0
        assert session.total_input_tokens == 0
        assert session.total_output_tokens == 0
        assert session.total_cost_usd == 0.0
        assert session.last_call_at is None


# ===================================================================
# SisterSessionManager — pool management
# ===================================================================


class TestPool:
    def test_pool_seeded_on_init(self) -> None:
        mgr = _make_manager(pool_size=3)
        # Pool is not seeded until start() — _fill_pool is lazy
        mgr._fill_pool()
        assert len(mgr._pool) == 3

    def test_pop_or_create_from_pool(self) -> None:
        mgr = _make_manager(pool_size=2)
        mgr._fill_pool()
        session = mgr._pop_or_create()
        assert isinstance(session, SisterSession)
        # Pool was refilled after pop
        assert len(mgr._pool) == 2

    def test_pop_or_create_empty_pool(self) -> None:
        mgr = _make_manager(pool_size=0)
        session = mgr._pop_or_create()
        assert isinstance(session, SisterSession)


# ===================================================================
# Warm / Adopt / Release lifecycle
# ===================================================================


class TestWarmLifecycle:
    @pytest.mark.asyncio
    async def test_warm_returns_token(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        token = await mgr.warm()
        assert isinstance(token, str)
        assert len(token) > 0
        assert token in mgr._warm

    @pytest.mark.asyncio
    async def test_release_returns_to_pool(self) -> None:
        mgr = _make_manager(pool_size=2)
        mgr._fill_pool()
        token = await mgr.warm()
        initial_pool_size = len(mgr._pool)
        found = await mgr.release(token)
        assert found is True
        assert token not in mgr._warm
        # Session recycled back to pool
        assert len(mgr._pool) >= initial_pool_size

    @pytest.mark.asyncio
    async def test_release_unknown_token(self) -> None:
        mgr = _make_manager()
        found = await mgr.release("nonexistent-token")
        assert found is False

    @pytest.mark.asyncio
    async def test_adopt_binds_to_job(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        token = await mgr.warm()
        await mgr.adopt(token, "job-1")
        assert "job-1" in mgr._jobs
        assert token not in mgr._warm

    @pytest.mark.asyncio
    async def test_adopt_missing_token_creates_new(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        await mgr.adopt("expired-token", "job-2")
        assert "job-2" in mgr._jobs

    @pytest.mark.asyncio
    async def test_create_for_job(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        await mgr.create_for_job("job-3")
        assert "job-3" in mgr._jobs

    @pytest.mark.asyncio
    async def test_get_returns_session(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        await mgr.create_for_job("job-4")
        session = mgr.get("job-4")
        assert isinstance(session, SisterSession)

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self) -> None:
        mgr = _make_manager()
        assert mgr.get("nonexistent") is None


# ===================================================================
# Close and metrics
# ===================================================================


class TestCloseAndMetrics:
    @pytest.mark.asyncio
    async def test_close_job_removes_binding(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        await mgr.create_for_job("j1")
        await mgr.close_job("j1")
        assert "j1" not in mgr._jobs

    @pytest.mark.asyncio
    async def test_close_job_preserves_metrics(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        await mgr.create_for_job("j1")
        session = mgr.get("j1")
        session.call_count = 3
        session.total_latency_ms = 150.0
        session.total_input_tokens = 30
        session.total_output_tokens = 15
        session.total_cost_usd = 0.005

        await mgr.close_job("j1")

        assert "j1" in mgr._closed_jobs
        snapshot = mgr._closed_jobs["j1"]
        assert snapshot["callCount"] == 3
        assert snapshot["inputTokens"] == 30
        assert mgr._global_call_count == 3
        assert mgr._global_cost_usd == 0.005

    @pytest.mark.asyncio
    async def test_close_job_nonexistent_noop(self) -> None:
        mgr = _make_manager()
        await mgr.close_job("nope")  # should not raise

    @pytest.mark.asyncio
    async def test_get_metrics_structure(self) -> None:
        mgr = _make_manager(pool_size=2)
        mgr._fill_pool()
        await mgr.create_for_job("j1")
        metrics = mgr.get_metrics()
        assert "global" in metrics
        assert "jobs" in metrics
        assert "totalCalls" in metrics["global"]
        assert "activeJobs" in metrics["global"]
        assert "poolSize" in metrics["global"]

    @pytest.mark.asyncio
    async def test_closed_jobs_capped(self) -> None:
        mgr = _make_manager()
        mgr._fill_pool()
        # Create and close many jobs to test LRU eviction
        from backend.services.sister_session import _CLOSED_JOBS_MAX

        for i in range(_CLOSED_JOBS_MAX + 10):
            await mgr.create_for_job(f"j-{i}")
            session = mgr.get(f"j-{i}")
            session.call_count = 1
            session.total_latency_ms = 1.0
            await mgr.close_job(f"j-{i}")

        assert len(mgr._closed_jobs) <= _CLOSED_JOBS_MAX


# ===================================================================
# Shutdown
# ===================================================================


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_clears_state(self) -> None:
        adapter = _mock_adapter()
        mgr = _make_manager(adapter=adapter)
        # Patch the fast completer's close
        mgr._fast_completer.close = AsyncMock()
        mgr._fill_pool()
        await mgr.create_for_job("j1")
        token = await mgr.warm()

        await mgr.shutdown()

        assert len(mgr._pool) == 0
        assert len(mgr._warm) == 0
        assert len(mgr._jobs) == 0
        mgr._fast_completer.close.assert_awaited_once()


# ===================================================================
# Model property
# ===================================================================


class TestModel:
    def test_model_property(self) -> None:
        mgr = _make_manager()
        assert mgr.model == "test-model"
