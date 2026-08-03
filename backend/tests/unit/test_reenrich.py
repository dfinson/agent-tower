"""Tests for the idempotent re-enrichment path (reenrich.py)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from traceforge.types import EventMetadata

from backend.models.events import EventKind, new_event
from backend.services.events.reenrich import _REENRICH_MARKER_KIND, reenrich_job_events


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
        with patch("backend.persistence.event_repo.EventRepository") as MockRepo:
            repo = MockRepo.return_value
            # Marker exists
            repo.list_by_job = AsyncMock(return_value=[
                new_event(
                    session_id="j1",
                    kind=_REENRICH_MARKER_KIND,
                    payload={"updated_count": 5},
                )
            ])

            result = await reenrich_job_events("j1", mock_session_factory)
            assert result == 0

    @pytest.mark.asyncio
    async def test_force_ignores_marker(self, mock_session_factory):
        """force=True re-enriches even when marker exists."""
        with patch("backend.persistence.event_repo.EventRepository") as MockRepo:
            repo = MockRepo.return_value
            # No events to process
            repo.list_all_events_by_job = AsyncMock(return_value=[])

            result = await reenrich_job_events("j1", mock_session_factory, force=True)
            assert result == 0
            # Should not check for markers when force=True
            repo.list_by_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_events_returns_zero(self, mock_session_factory):
        """Empty job returns 0."""
        with patch("backend.persistence.event_repo.EventRepository") as MockRepo:
            repo = MockRepo.return_value
            repo.list_by_job = AsyncMock(return_value=[])
            repo.list_all_events_by_job = AsyncMock(return_value=[])

            result = await reenrich_job_events("j1", mock_session_factory)
            assert result == 0
