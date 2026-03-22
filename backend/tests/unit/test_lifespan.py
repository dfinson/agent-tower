from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from backend.lifespan import _persist_event_with_retry
from backend.models.events import DomainEvent, DomainEventKind


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _make_event() -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        job_id="job-1",
        timestamp=datetime.now(UTC),
        kind=DomainEventKind.job_state_changed,
        payload={"state": "running"},
    )


@pytest.mark.asyncio
async def test_persist_event_retries_sqlite_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[_FakeSession] = []
    append_attempts = 0

    def _session_factory() -> _FakeSessionContext:
        session = _FakeSession()
        sessions.append(session)
        return _FakeSessionContext(session)

    class _FakeRepo:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def append(self, event: DomainEvent) -> None:
            nonlocal append_attempts
            append_attempts += 1
            if append_attempts == 1:
                raise OperationalError("INSERT", {}, Exception("database is locked"))

    monkeypatch.setattr("backend.lifespan.EventRepository", _FakeRepo)

    await _persist_event_with_retry(
        event=_make_event(),
        session_factory=_session_factory,
        write_lock=asyncio.Lock(),
        retry_delay_s=0,
    )

    assert append_attempts == 2
    assert len(sessions) == 2
    sessions[0].rollback.assert_awaited_once()
    sessions[0].commit.assert_not_called()
    sessions[1].commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_event_does_not_retry_non_lock_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    def _session_factory() -> _FakeSessionContext:
        return _FakeSessionContext(session)

    class _FakeRepo:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def append(self, event: DomainEvent) -> None:
            raise OperationalError("INSERT", {}, Exception("disk I/O error"))

    monkeypatch.setattr("backend.lifespan.EventRepository", _FakeRepo)

    with pytest.raises(OperationalError, match="disk I/O error"):
        await _persist_event_with_retry(
            event=_make_event(),
            session_factory=_session_factory,
            write_lock=asyncio.Lock(),
            retry_delay_s=0,
        )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_called()
