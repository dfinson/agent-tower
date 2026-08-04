"""Tests for the idempotent re-enrichment path (reenrich.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.events import EventKind, new_event
from backend.services.events.reenrich import (
    _REENRICH_MARKER_KIND,
    _job_locks,
    reenrich_job_events,
)


@pytest.fixture(autouse=True)
def _clear_locks():
    """Clear per-job locks between tests."""
    _job_locks.clear()
    yield
    _job_locks.clear()


@pytest.fixture
def mock_session_factory():
    """Create a mock async session factory that returns an async context manager."""
    session = AsyncMock()

    # Make the factory return an async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = ctx
    return factory


class TestReenrichIdempotency:
    @pytest.mark.asyncio
    async def test_skips_when_marker_exists(self, mock_session_factory):
        """Re-enrichment is skipped when the marker event already exists."""
        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(
                return_value=[
                    new_event(
                        session_id="j1",
                        kind=_REENRICH_MARKER_KIND,
                        payload={"updated_count": 5},
                    )
                ]
            )

            result = await reenrich_job_events("j1", mock_session_factory)
            assert result == 0

    @pytest.mark.asyncio
    async def test_force_deletes_and_reinserts_marker(self, mock_session_factory):
        """force=True deletes old marker and inserts a fresh one with correct count."""
        marker = new_event(
            session_id="j1",
            kind=_REENRICH_MARKER_KIND,
            payload={"updated_count": 5},
        )
        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[marker])
            repo.list_all_events_by_job = AsyncMock(return_value=[])
            repo.delete_event = AsyncMock()

            result = await reenrich_job_events("j1", mock_session_factory, force=True)
            assert result == 0
            # Should delete existing marker
            repo.delete_event.assert_called_once_with(marker.id)

    @pytest.mark.asyncio
    async def test_no_events_returns_zero(self, mock_session_factory):
        """Empty job returns 0."""
        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(return_value=[])

            result = await reenrich_job_events("j1", mock_session_factory)
            assert result == 0


class TestReenrichConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_double_replay(self, mock_session_factory):
        """Second concurrent call returns 0 immediately (lock held)."""
        # Simulate a slow reenrich by holding the lock manually
        from backend.services.events.reenrich import _get_job_lock

        lock = _get_job_lock("j1")
        await lock.acquire()

        # Second call should detect lock is held and return 0 immediately
        result = await reenrich_job_events("j1", mock_session_factory)
        assert result == 0

        lock.release()

    @pytest.mark.asyncio
    async def test_lock_cleaned_up_after_completion(self, mock_session_factory):
        """Per-job lock is removed from _job_locks after reenrich completes."""
        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(return_value=[])

            await reenrich_job_events("j1", mock_session_factory)
            # Lock should be cleaned up — no unbounded accumulation
            assert "j1" not in _job_locks

    @pytest.mark.asyncio
    async def test_marker_events_excluded_from_replay(self, mock_session_factory):
        """Marker events in the stream are skipped during re-enrichment."""
        marker_event = new_event(
            session_id="j1",
            kind=_REENRICH_MARKER_KIND,
            payload={"updated_count": 3},
        )
        normal_event = new_event(
            session_id="j1",
            kind=EventKind.message_user,
            payload={"content": "hello"},
        )

        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            # Return both marker and normal events
            repo.list_all_events_by_job = AsyncMock(return_value=[marker_event, normal_event])
            repo.update_metadata = AsyncMock()

            with patch("backend.services.events.reenrich.TFEnricher") as mock_enricher_cls:
                enricher = mock_enricher_cls.return_value
                enricher.process = MagicMock(return_value=None)
                enricher.flush = MagicMock(return_value=[])

                await reenrich_job_events("j1", mock_session_factory)

                # Enricher.process should only be called with the normal event
                # (marker is skipped)
                enricher.process.assert_called_once_with(normal_event)


class TestReenrichBatching:
    @pytest.mark.asyncio
    async def test_multi_batch_processing(self, mock_session_factory):
        """Events are loaded in batches — verifies pagination works."""
        from backend.services.events.reenrich import _BATCH_SIZE

        # Create events for 2 batches
        events_batch_1 = [
            new_event(session_id="j1", kind=EventKind.message_user, payload={"content": f"msg-{i}"})
            for i in range(_BATCH_SIZE)
        ]
        events_batch_2 = [
            new_event(session_id="j1", kind=EventKind.message_user, payload={"content": f"msg-{i}"}) for i in range(10)
        ]

        call_count = 0

        async def _mock_list_all(job_id, *, limit=None, offset=0):
            nonlocal call_count
            call_count += 1
            if offset == 0:
                return events_batch_1
            elif offset == _BATCH_SIZE:
                return events_batch_2
            return []

        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(side_effect=_mock_list_all)
            repo.update_metadata = AsyncMock()

            with patch("backend.services.events.reenrich.TFEnricher") as mock_enricher_cls:
                enricher = mock_enricher_cls.return_value
                enricher.process = MagicMock(return_value=None)
                enricher.flush = MagicMock(return_value=[])

                await reenrich_job_events("j1", mock_session_factory)

                # Should have called list_all_events_by_job at least 2 times
                # (batch 1, batch 2, and possibly a final empty check)
                assert call_count >= 2
                # Enricher.process should have been called for all events
                assert enricher.process.call_count == _BATCH_SIZE + 10


class _InPlaceMutatingEnricher:
    """Faithful stand-in for a hypothetical TraceForge that enriches by mutating
    the event's metadata IN PLACE and returning the SAME event object.

    This aliases the input and the result (``result is event`` and
    ``result.metadata is event.metadata``), which is exactly the shape that
    defeats a naive live ``e.metadata != event.metadata`` comparison — the two
    sides are the same object, so ``!=`` is always False and the write is
    silently skipped. reenrich must instead compare against a snapshot captured
    *before* ``process`` and still persist the change.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.processed: list[str] = []

    def process(self, event):  # noqa: ANN001, ANN201
        self.processed.append(event.id)
        # Enrich by replacing metadata on the SAME event object (in place).
        enriched_md = event.metadata.model_copy(update={"tool_display": "shell"})
        object.__setattr__(event, "metadata", enriched_md)
        return event

    def flush(self):  # noqa: ANN201
        return []


class TestReenrichMutationSafety:
    """Point 2: the change check is robust to in-place metadata mutation and the
    updated/marker count stays accurate."""

    @pytest.mark.asyncio
    async def test_in_place_mutation_still_persists_metadata(self, mock_session_factory):
        """An in-place-mutating enricher must NOT cause a silently-skipped write.

        Proves the snapshot-before-process fix: metadata is persisted and the
        returned updated count (which is written into the marker) is correct.
        """
        event = new_event(
            session_id="j1",
            kind=EventKind.tool_call_completed,
            payload={"tool_name": "bash", "tool_call_id": "tc-1"},
        )
        # Precondition: the original metadata has no tool_display, so enrichment
        # (tool_display="shell") is a genuine, detectable change.
        assert event.metadata.tool_display is None

        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(side_effect=[[event], []])
            repo.update_metadata = AsyncMock()

            with patch("backend.services.events.reenrich.TFEnricher", _InPlaceMutatingEnricher):
                updated = await reenrich_job_events("j1", mock_session_factory)

            # Metadata was persisted despite input/result aliasing.
            repo.update_metadata.assert_awaited_once()
            _, kwargs = repo.update_metadata.await_args
            assert kwargs["event_id"] == event.id
            assert kwargs["metadata"].tool_display == "shell"
            # Marker/return count reflects exactly one write.
            assert updated == 1

    @pytest.mark.asyncio
    async def test_no_change_writes_nothing(self, mock_session_factory):
        """When enrichment yields no net metadata change, no write occurs and the
        count stays zero (avoid unnecessary writes)."""

        class _NoOpEnricher:
            def __init__(self, *a, **k) -> None:
                pass

            def process(self, event):  # noqa: ANN001, ANN201
                # Return the event unchanged (no metadata delta).
                return event

            def flush(self):  # noqa: ANN201
                return []

        event = new_event(session_id="j1", kind=EventKind.message_user, payload={"content": "hi"})

        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(side_effect=[[event], []])
            repo.update_metadata = AsyncMock()

            with patch("backend.services.events.reenrich.TFEnricher", _NoOpEnricher):
                updated = await reenrich_job_events("j1", mock_session_factory)

            repo.update_metadata.assert_not_awaited()
            assert updated == 0

    @pytest.mark.asyncio
    async def test_real_enricher_persists_enriched_metadata(self, mock_session_factory):
        """End-to-end with the REAL TF 0.1.5 enricher: a classifiable tool-start is
        buffered then flushed as an enriched orphan whose metadata is persisted."""
        event = new_event(
            session_id="j1",
            kind=EventKind.tool_call_started,
            payload={"tool_name": "bash", "tool_call_id": "tc-1", "arguments": '{"command": "ls -la"}'},
        )
        assert event.metadata.classification is None  # not yet enriched

        with patch("backend.persistence.event_repo.EventRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(side_effect=[[event], []])
            repo.update_metadata = AsyncMock()

            # No TFEnricher patch — uses the real enricher.
            updated = await reenrich_job_events("j1", mock_session_factory)

        repo.update_metadata.assert_awaited()
        _, kwargs = repo.update_metadata.await_args
        assert kwargs["event_id"] == event.id
        assert kwargs["metadata"].classification is not None
        assert updated >= 1
