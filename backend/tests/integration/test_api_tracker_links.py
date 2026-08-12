"""Integration tests for the TrackerLink attach/list API (Story 3.2).

Exercises:
  POST /api/projects/{project_id}/tracker-links
  GET  /api/projects/{project_id}/tracker-links
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.services.credentials import encryption

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _isolated_codeplane_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encryption, "get_codeplane_dir", lambda: tmp_path)


async def _seed_project(session_factory: async_sessionmaker[AsyncSession], project_id: str = "proj-1") -> None:
    from datetime import UTC, datetime

    from backend.models.db import ProjectRow

    async with session_factory() as session:
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


async def _create_credential(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/settings/credentials",
        json={"provider": "github", "label": "GH", "baseUrl": "https://api.github.com", "pat": "p"},
    )
    return str(resp.json()["id"])


class TestCreateTrackerLink:
    @pytest.mark.asyncio
    async def test_attach_credential_to_project_creates_tracker_link(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory)
        credential_id = await _create_credential(client)

        resp = await client.post(
            "/api/projects/proj-1/tracker-links",
            json={"credentialId": credential_id, "externalRef": "ORG/board-1"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["projectId"] == "proj-1"
        assert body["credentialId"] == credential_id
        assert body["externalRef"] == "ORG/board-1"
        assert "id" in body
        assert "createdAt" in body

    @pytest.mark.asyncio
    async def test_project_can_have_more_than_one_tracker_link(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory)
        cred_1 = await _create_credential(client)
        cred_2_resp = await client.post(
            "/api/settings/credentials",
            json={"provider": "jira", "label": "Jira", "baseUrl": "https://x.atlassian.net", "pat": "tok"},
        )
        cred_2 = cred_2_resp.json()["id"]

        await client.post(
            "/api/projects/proj-1/tracker-links", json={"credentialId": cred_1, "externalRef": "ORG/board-1"}
        )
        await client.post(
            "/api/projects/proj-1/tracker-links", json={"credentialId": cred_2, "externalRef": "ORG/board-2"}
        )

        resp = await client.get("/api/projects/proj-1/tracker-links")
        assert resp.status_code == 200
        links = resp.json()["trackerLinks"]
        assert len(links) == 2

    @pytest.mark.asyncio
    async def test_same_credential_attaches_to_multiple_projects(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory, "proj-1")
        await _seed_project(session_factory, "proj-2")
        credential_id = await _create_credential(client)

        resp_1 = await client.post(
            "/api/projects/proj-1/tracker-links", json={"credentialId": credential_id, "externalRef": "ORG/board-1"}
        )
        resp_2 = await client.post(
            "/api/projects/proj-2/tracker-links", json={"credentialId": credential_id, "externalRef": "ORG/board-2"}
        )
        assert resp_1.status_code == 201
        assert resp_2.status_code == 201

    @pytest.mark.asyncio
    async def test_returns_404_when_project_does_not_exist(self, client: AsyncClient) -> None:
        credential_id = await _create_credential(client)

        resp = await client.post(
            "/api/projects/does-not-exist/tracker-links",
            json={"credentialId": credential_id, "externalRef": "ORG/board-1"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_when_credential_does_not_exist(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory)

        resp = await client.post(
            "/api/projects/proj-1/tracker-links",
            json={"credentialId": "does-not-exist", "externalRef": "ORG/board-1"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_empty_external_ref(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory)
        credential_id = await _create_credential(client)

        resp = await client.post(
            "/api/projects/proj-1/tracker-links", json={"credentialId": credential_id, "externalRef": ""}
        )
        assert resp.status_code == 422


class TestListTrackerLinks:
    @pytest.mark.asyncio
    async def test_empty_list_for_project_with_no_links(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory)

        resp = await client.get("/api/projects/proj-1/tracker-links")
        assert resp.status_code == 200
        assert resp.json() == {"trackerLinks": []}

    @pytest.mark.asyncio
    async def test_list_does_not_leak_across_projects(
        self, client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_project(session_factory, "proj-1")
        await _seed_project(session_factory, "proj-2")
        credential_id = await _create_credential(client)

        await client.post(
            "/api/projects/proj-1/tracker-links", json={"credentialId": credential_id, "externalRef": "ORG/board-1"}
        )

        resp = await client.get("/api/projects/proj-2/tracker-links")
        assert resp.json() == {"trackerLinks": []}
