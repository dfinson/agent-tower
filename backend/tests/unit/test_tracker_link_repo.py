"""Unit tests for TrackerLinkRepository (Story 3.2, CAP-7/AD-6)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, CredentialRow, ProjectRow
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.tracker_link_repo import (
    TrackerLinkCredentialNotFoundError,
    TrackerLinkProjectNotFoundError,
    TrackerLinkRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    sa_event.listen(eng.sync_engine, "connect", _set_sqlite_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


async def _seed_project(session: AsyncSession, project_id: str = "proj-1") -> None:
    session.add(
        ProjectRow(
            id=project_id,
            name="Test Project",
            repo_paths="[]",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def _seed_credential(session: AsyncSession, credential_id: str = "cred-1") -> None:
    session.add(
        CredentialRow(
            id=credential_id,
            provider="github",
            label="GH",
            base_url="https://api.github.com",
            encrypted_secret="encrypted",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    await session.commit()


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_attaches_credential_to_project(self, session: AsyncSession) -> None:
        await _seed_project(session)
        await _seed_credential(session)
        repo = TrackerLinkRepository(session)

        result = await repo.create(
            link_id="link-1", project_id="proj-1", credential_id="cred-1", external_ref="ORG/board-1"
        )
        await session.commit()

        assert result["id"] == "link-1"
        assert result["project_id"] == "proj-1"
        assert result["credential_id"] == "cred-1"
        assert result["external_ref"] == "ORG/board-1"
        assert result["created_at"]

    @pytest.mark.asyncio
    async def test_create_raises_when_project_missing(self, session: AsyncSession) -> None:
        await _seed_credential(session)
        repo = TrackerLinkRepository(session)

        with pytest.raises(TrackerLinkProjectNotFoundError):
            await repo.create(
                link_id="link-1", project_id="does-not-exist", credential_id="cred-1", external_ref="ORG/board-1"
            )

    @pytest.mark.asyncio
    async def test_create_raises_when_credential_missing(self, session: AsyncSession) -> None:
        await _seed_project(session)
        repo = TrackerLinkRepository(session)

        with pytest.raises(TrackerLinkCredentialNotFoundError):
            await repo.create(
                link_id="link-1", project_id="proj-1", credential_id="does-not-exist", external_ref="ORG/board-1"
            )

    @pytest.mark.asyncio
    async def test_project_can_have_multiple_tracker_links(self, session: AsyncSession) -> None:
        await _seed_project(session)
        await _seed_credential(session, "cred-1")
        await _seed_credential(session, "cred-2")
        repo = TrackerLinkRepository(session)

        await repo.create(link_id="link-1", project_id="proj-1", credential_id="cred-1", external_ref="ORG/board-1")
        await repo.create(link_id="link-2", project_id="proj-1", credential_id="cred-2", external_ref="ORG/board-2")
        await session.commit()

        links = await repo.list_for_project("proj-1")
        assert len(links) == 2

    @pytest.mark.asyncio
    async def test_same_credential_can_attach_to_multiple_projects(self, session: AsyncSession) -> None:
        await _seed_project(session, "proj-1")
        await _seed_project(session, "proj-2")
        await _seed_credential(session)
        repo = TrackerLinkRepository(session)

        await repo.create(link_id="link-1", project_id="proj-1", credential_id="cred-1", external_ref="ORG/board-1")
        await repo.create(link_id="link-2", project_id="proj-2", credential_id="cred-1", external_ref="ORG/board-2")
        await session.commit()

        assert len(await repo.list_for_project("proj-1")) == 1
        assert len(await repo.list_for_project("proj-2")) == 1


class TestListForProject:
    @pytest.mark.asyncio
    async def test_list_returns_empty_for_project_with_no_links(self, session: AsyncSession) -> None:
        await _seed_project(session)
        repo = TrackerLinkRepository(session)

        assert await repo.list_for_project("proj-1") == []

    @pytest.mark.asyncio
    async def test_list_does_not_leak_links_between_projects(self, session: AsyncSession) -> None:
        await _seed_project(session, "proj-1")
        await _seed_project(session, "proj-2")
        await _seed_credential(session)
        repo = TrackerLinkRepository(session)

        await repo.create(link_id="link-1", project_id="proj-1", credential_id="cred-1", external_ref="ORG/board-1")
        await session.commit()

        assert len(await repo.list_for_project("proj-1")) == 1
        assert await repo.list_for_project("proj-2") == []
