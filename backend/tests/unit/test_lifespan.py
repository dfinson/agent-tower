from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from backend.lifespan import _RESTART_REQUEST_ID_ENV, _persist_event_with_retry, _publish_restart_readiness
from backend.models.events import EventKind, SessionEvent, new_event

if TYPE_CHECKING:
    from pathlib import Path


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
        if exc_type is not None:
            await self._session.rollback()
        else:
            await self._session.commit()
        return None


def _make_event() -> SessionEvent:
    return new_event(
        event_id="evt-1",
        session_id="job-1",
        timestamp=datetime.now(UTC),
        kind=EventKind.job_state_changed,
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

        async def append(self, event: SessionEvent) -> None:
            nonlocal append_attempts
            append_attempts += 1
            if append_attempts == 1:
                raise OperationalError("INSERT", {}, Exception("database is locked"))

    monkeypatch.setattr("backend.lifespan.EventRepository", _FakeRepo)

    # Bypass the global write lock in tests by patching serialized_write
    # to just yield a session directly from the factory.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_serialized_write(sf: Any):
        async with sf() as session:
            yield session

    with patch("backend.lifespan.serialized_write", _fake_serialized_write):
        await _persist_event_with_retry(
            event=_make_event(),
            session_factory=_session_factory,
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

        async def append(self, event: SessionEvent) -> None:
            raise OperationalError("INSERT", {}, Exception("disk I/O error"))

    monkeypatch.setattr("backend.lifespan.EventRepository", _FakeRepo)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_serialized_write(sf: Any):
        async with sf() as session:
            yield session

    with patch("backend.lifespan.serialized_write", _fake_serialized_write):  # noqa: SIM117
        with pytest.raises(OperationalError, match="disk I/O error"):
            await _persist_event_with_retry(
                event=_make_event(),
                session_factory=_session_factory,
                retry_delay_s=0,
            )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Restart readiness marker (SPEC.md CAP-5)
# ---------------------------------------------------------------------------
#
# ``backend.services.dev_restart.restart_protocol`` is a real, committed
# dependency (integration session 3fd0b7af-27ee-4346-9098-911b5350a34c), so
# these tests exercise the real ``get_request_paths``/``write_json_atomic``
# against an isolated ``CODEPLANE_HOME`` rather than injecting a fake module —
# matching the fixture pattern used in ``test_restart_protocol.py``.


@pytest.fixture(autouse=True)
def _isolated_codeplane_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CODEPLANE_HOME at a throwaway directory for every test in this file."""
    monkeypatch.setenv("CODEPLANE_HOME", str(tmp_path))
    import backend.config as config_module

    monkeypatch.setattr(config_module, "_codeplane_dir", None)
    return tmp_path


def _read_ready_marker(tmp_path: Path, request_id: str) -> dict[str, Any]:
    import json

    path = tmp_path / "dev-restart" / f"{request_id}.ready.json"
    assert path.exists(), f"expected ready marker at {path}"
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _ready_marker_path(tmp_path: Path, request_id: str) -> Path:
    return tmp_path / "dev-restart" / f"{request_id}.ready.json"


@pytest.mark.asyncio
async def test_publish_restart_readiness_writes_locked_marker_shape(tmp_path: Path) -> None:
    import asyncio
    import os

    recovery_task = asyncio.create_task(asyncio.sleep(0))
    remote_task = asyncio.create_task(asyncio.sleep(0))

    await _publish_restart_readiness("req-abc123", recovery_task, remote_task)

    payload = _read_ready_marker(tmp_path, "req-abc123")
    # Locked wire contract: exactly these three camelCase keys, nothing else
    # (no diagnostics, no secrets — see ARCHITECTURE-SPINE.md AD-12).
    assert set(payload.keys()) == {"requestId", "pid", "writtenAt"}
    assert payload["requestId"] == "req-abc123"
    assert payload["pid"] == os.getpid()
    # writtenAt must parse as an ISO-8601 UTC timestamp
    datetime.fromisoformat(payload["writtenAt"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_publish_restart_readiness_orders_recovery_then_remote_before_write(
    tmp_path: Path,
) -> None:
    import asyncio

    order: list[str] = []

    async def _recovery() -> None:
        await asyncio.sleep(0.02)
        order.append("recovery")

    async def _remote_check() -> None:
        await asyncio.sleep(0.05)
        order.append("remote")

    recovery_task = asyncio.create_task(_recovery())
    remote_task = asyncio.create_task(_remote_check())

    await _publish_restart_readiness("req-order", recovery_task, remote_task)
    order.append("write")

    assert order == ["recovery", "remote", "write"]
    assert _ready_marker_path(tmp_path, "req-order").exists()


@pytest.mark.asyncio
async def test_publish_restart_readiness_does_not_write_marker_if_recovery_raises(
    tmp_path: Path,
) -> None:
    import asyncio

    async def _failing_recovery() -> None:
        raise RuntimeError("db unavailable")

    recovery_task = asyncio.create_task(_failing_recovery())
    remote_task = asyncio.create_task(asyncio.sleep(0))

    # A failed startup recovery must propagate — no broad failure-tolerance
    # catch that publishes readiness anyway (coordinated with the
    # restart-protocol integration session).
    with pytest.raises(RuntimeError, match="db unavailable"):
        await _publish_restart_readiness("req-recovery-fail", recovery_task, remote_task)

    assert not _ready_marker_path(tmp_path, "req-recovery-fail").exists()


@pytest.mark.asyncio
async def test_publish_restart_readiness_does_not_write_marker_if_remote_check_raises(
    tmp_path: Any,
) -> None:
    import asyncio

    async def _failing_remote_check() -> None:
        raise RuntimeError("cloudflare access not detected")

    recovery_task = asyncio.create_task(asyncio.sleep(0))
    remote_task = asyncio.create_task(_failing_remote_check())

    # A failed deferred remote validation is a real "not ready" outcome —
    # the marker distinguishes "startup + remote validation both succeeded"
    # from anything else, so it must be withheld here too.
    with pytest.raises(RuntimeError, match="cloudflare access not detected"):
        await _publish_restart_readiness("req-remote-fail", recovery_task, remote_task)

    assert not _ready_marker_path(tmp_path, "req-remote-fail").exists()


@pytest.mark.asyncio
async def test_publish_restart_readiness_does_not_write_marker_if_recovery_cancelled(
    tmp_path: Any,
) -> None:
    import asyncio

    async def _hanging_recovery() -> None:
        await asyncio.sleep(10)

    recovery_task = asyncio.create_task(_hanging_recovery())
    remote_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)  # let the recovery task actually start
    recovery_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await _publish_restart_readiness("req-recovery-cancelled", recovery_task, remote_task)

    assert not _ready_marker_path(tmp_path, "req-recovery-cancelled").exists()


@pytest.mark.asyncio
async def test_publish_restart_readiness_without_remote_check_task(tmp_path: Any) -> None:
    import asyncio

    recovery_task = asyncio.create_task(asyncio.sleep(0))

    # Non-Cloudflare / no-tunnel startups schedule no remote-validation task.
    await _publish_restart_readiness("req-no-remote", recovery_task, None)

    payload = _read_ready_marker(tmp_path, "req-no-remote")
    assert payload["requestId"] == "req-no-remote"


def test_restart_request_id_env_name_is_stable() -> None:
    # Locks the env-var name the restart helper actually sets on the
    # replacement process before exec (confirmed from the real, pushed
    # ``backend/services/dev_restart/restart_helper.py``:
    # ``env["CODEPLANE_RESTART_REQUEST_ID"] = request_id``).
    assert _RESTART_REQUEST_ID_ENV == "CODEPLANE_RESTART_REQUEST_ID"
