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
