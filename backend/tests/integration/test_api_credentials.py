"""Integration tests for the global Credential API (Story 3.1).

Exercises:
  GET    /api/settings/credentials
  GET    /api/settings/credentials/guidance
  POST   /api/settings/credentials
  DELETE /api/settings/credentials/{credential_id}
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backend.services.credentials import encryption

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _isolated_codeplane_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encryption, "get_codeplane_dir", lambda: tmp_path)


class TestListCredentials:
    @pytest.mark.asyncio
    async def test_empty_list_initially(self, client: AsyncClient) -> None:
        resp = await client.get("/api/settings/credentials")
        assert resp.status_code == 200
        assert resp.json() == {"credentials": []}


class TestProviderGuidance:
    @pytest.mark.asyncio
    async def test_returns_guidance_for_all_three_providers(self, client: AsyncClient) -> None:
        resp = await client.get("/api/settings/credentials/guidance")
        assert resp.status_code == 200
        guidance = resp.json()["guidance"]
        assert set(guidance) == {"github", "jira", "azure_devops"}
        for text in guidance.values():
            assert isinstance(text, str)
            assert text


class TestCreateCredential:
    @pytest.mark.asyncio
    async def test_create_returns_no_secret_field(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/credentials",
            json={
                "provider": "github",
                "label": "My GitHub Projects",
                "baseUrl": "https://api.github.com",
                "pat": "ghp_sentinel_value_should_never_appear",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["provider"] == "github"
        assert body["label"] == "My GitHub Projects"
        assert body["baseUrl"] == "https://api.github.com"
        assert "id" in body
        assert "createdAt" in body
        # No secret/pat field anywhere in the response body.
        assert "pat" not in body
        assert "secret" not in body
        assert "encryptedSecret" not in body

    @pytest.mark.asyncio
    async def test_created_credential_appears_in_list(self, client: AsyncClient) -> None:
        await client.post(
            "/api/settings/credentials",
            json={"provider": "jira", "label": "Jira", "baseUrl": "https://x.atlassian.net", "pat": "tok"},
        )
        resp = await client.get("/api/settings/credentials")
        creds = resp.json()["credentials"]
        assert len(creds) == 1
        assert creds[0]["provider"] == "jira"
        assert "pat" not in creds[0]

    @pytest.mark.asyncio
    async def test_rejects_unknown_provider(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/credentials",
            json={"provider": "bitbucket", "label": "x", "baseUrl": "https://x", "pat": "p"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_empty_pat(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/credentials",
            json={"provider": "github", "label": "x", "baseUrl": "https://x", "pat": ""},
        )
        assert resp.status_code == 422


class TestDeleteCredential:
    @pytest.mark.asyncio
    async def test_delete_succeeds_for_unreferenced_credential(self, client: AsyncClient) -> None:
        created = (
            await client.post(
                "/api/settings/credentials",
                json={"provider": "azure_devops", "label": "ADO", "baseUrl": "https://dev.azure.com/org", "pat": "p"},
            )
        ).json()

        resp = await client.delete(f"/api/settings/credentials/{created['id']}")
        assert resp.status_code == 204

        listed = (await client.get("/api/settings/credentials")).json()["credentials"]
        assert listed == []

    @pytest.mark.asyncio
    async def test_delete_returns_404_for_unknown_id(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/settings/credentials/does-not-exist")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_blocked_while_referenced_by_tracker_link(
        self, client: AsyncClient, session_factory: object
    ) -> None:
        import uuid

        from backend.models.db import TrackerLinkRow

        created = (
            await client.post(
                "/api/settings/credentials",
                json={"provider": "github", "label": "GH", "baseUrl": "https://api.github.com", "pat": "p"},
            )
        ).json()

        async with session_factory() as session:  # type: ignore[operator]
            session.add(
                TrackerLinkRow(
                    id=str(uuid.uuid4()),
                    project_id="proj-1",
                    credential_id=created["id"],
                    external_ref="ORG/1",
                    created_at="2026-01-01T00:00:00Z",
                )
            )
            await session.commit()

        resp = await client.delete(f"/api/settings/credentials/{created['id']}")
        assert resp.status_code == 409

        # Still present.
        listed = (await client.get("/api/settings/credentials")).json()["credentials"]
        assert len(listed) == 1
