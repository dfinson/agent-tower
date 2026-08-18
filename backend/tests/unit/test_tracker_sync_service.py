from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from backend.models.db import Base, CredentialRow, ProjectRow, TrackerLinkRow
from backend.persistence.credential_repo import CredentialRepository
from backend.persistence.tracker_summary_repo import TrackerSummaryRepository
from backend.services.tracker_adapter import TrackerAdapterError, TrackerTicket
from backend.services.tracker_sync_service import (
    TRACKER_POLL_INTERVAL_SECONDS,
    TrackerLinkNotFoundError,
    TrackerSyncService,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    value = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with value.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield value
    await value.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_link(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: str,
    link_id: str,
    external_ref: str,
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        if await session.get(ProjectRow, project_id) is None:
            session.add(
                ProjectRow(
                    id=project_id,
                    name=project_id,
                    repo_paths="[]",
                    created_at=now,
                    updated_at=now,
                )
            )
        credential_id = f"cred-{link_id}"
        session.add(
            CredentialRow(
                id=credential_id,
                provider="github",
                label=credential_id,
                base_url="https://api.github.com",
                encrypted_secret="encrypted",
                created_at=now.isoformat(),
            )
        )
        session.add(
            TrackerLinkRow(
                id=link_id,
                project_id=project_id,
                credential_id=credential_id,
                external_ref=external_ref,
                created_at=now.isoformat(),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_summary_repository_upserts_success_and_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_link(session_factory, project_id="proj-1", link_id="link-1", external_ref="acme/1")
    async with session_factory() as session:
        repo = TrackerSummaryRepository(session)
        saved = await repo.record_success(
            "link-1",
            [TrackerTicket(id="1", title="Ticket", status="Open", url=None)],
        )
        await session.commit()

    assert saved["tickets"][0]["title"] == "Ticket"
    assert saved["last_error"] is None

    async with session_factory() as session:
        repo = TrackerSummaryRepository(session)
        failed = await repo.record_error("link-1", "provider unavailable")
        await session.commit()

    assert failed["tickets"][0]["title"] == "Ticket"
    assert failed["last_error"] == "provider unavailable"
    assert failed["last_synced_at"] == saved["last_synced_at"]


@pytest.mark.asyncio
async def test_refresh_link_is_project_scoped(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_link(session_factory, project_id="proj-1", link_id="link-1", external_ref="acme/1")
    monkeypatch.setattr(CredentialRepository, "resolve_secret", AsyncMock(return_value="token"))
    adapter = AsyncMock()
    service = TrackerSyncService(
        session_factory=session_factory,
        adapters={"github": adapter},
    )

    with pytest.raises(TrackerLinkNotFoundError):
        await service.refresh_link(project_id="proj-2", link_id="link-1")

    adapter.fetch_tickets.assert_not_awaited()


@pytest.mark.asyncio
async def test_test_link_calls_provider_before_attachment(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_link(
        session_factory,
        project_id="proj-1",
        link_id="link-1",
        external_ref="acme/1",
    )
    monkeypatch.setattr(
        CredentialRepository,
        "resolve_secret",
        AsyncMock(return_value="token"),
    )
    adapter = AsyncMock()
    service = TrackerSyncService(
        session_factory=session_factory,
        adapters={"github": adapter},
    )

    await service.test_link(
        credential_id="cred-link-1",
        external_ref="acme/7",
    )

    adapter.test_connection.assert_awaited_once_with(
        base_url="https://api.github.com",
        external_ref="acme/7",
        token="token",
    )


@pytest.mark.asyncio
async def test_refresh_all_isolates_link_failures(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_link(session_factory, project_id="proj-1", link_id="link-1", external_ref="fail")
    await _seed_link(session_factory, project_id="proj-1", link_id="link-2", external_ref="acme/2")
    monkeypatch.setattr(CredentialRepository, "resolve_secret", AsyncMock(return_value="token"))

    async def fetch_tickets(*, external_ref: str, **_: str) -> list[TrackerTicket]:
        if external_ref == "fail":
            raise TrackerAdapterError("provider unavailable")
        return [TrackerTicket(id="2", title="Second", status="Open", url=None)]

    adapter = AsyncMock()
    adapter.fetch_tickets.side_effect = fetch_tickets
    service = TrackerSyncService(
        session_factory=session_factory,
        adapters={"github": adapter},
    )

    await service.refresh_all()

    async with session_factory() as session:
        repo = TrackerSummaryRepository(session)
        failed = await repo.get("link-1")
        succeeded = await repo.get("link-2")
    assert failed is not None and failed["last_error"] == "provider unavailable"
    assert succeeded is not None and succeeded["tickets"][0]["title"] == "Second"


@pytest.mark.asyncio
async def test_poller_uses_fixed_sixty_second_cadence(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TrackerSyncService(
        session_factory=session_factory,
        adapters={},
    )
    observed_timeout: float | None = None

    async def capture_timeout(awaitable: object, *, timeout: float) -> None:
        nonlocal observed_timeout
        observed_timeout = timeout
        service._stopping = True
        service._wake.set()
        await awaitable  # type: ignore[misc]

    monkeypatch.setattr(asyncio, "wait_for", capture_timeout)

    await service._poll_loop()

    assert TRACKER_POLL_INTERVAL_SECONDS == 60.0
    assert observed_timeout == 60.0


@pytest.mark.asyncio
async def test_stop_wakes_fixed_cadence_wait_promptly(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = TrackerSyncService(
        session_factory=session_factory,
        adapters={},
    )
    service.refresh_all = AsyncMock()
    service.start()
    await asyncio.sleep(0)

    await asyncio.wait_for(service.stop(), timeout=2.0)

    service.refresh_all.assert_not_awaited()
