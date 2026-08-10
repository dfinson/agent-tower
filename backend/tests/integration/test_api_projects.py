"""Integration tests for the Project API endpoints (Story 2.1 / CAP-6).

Exercises:
  POST  /api/settings/projects
  GET   /api/settings/projects
  GET   /api/settings/projects/{id}
  PATCH /api/settings/projects/{id}
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


def _resolved(path: str) -> str:
    return str(Path(path).expanduser().resolve())



class TestCreateProject:
    @pytest.mark.asyncio
    async def test_create_single_repo_project(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/projects",
            json={"name": "My Project", "repoPaths": ["/test/repo"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Project"
        assert data["repoPaths"] == [_resolved("/test/repo")]
        assert "id" in data
        assert "createdAt" in data
        assert "updatedAt" in data

    @pytest.mark.asyncio
    async def test_create_multi_repo_project(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/projects",
            json={"name": "Multi Repo", "repoPaths": ["/test/repo-a", "/test/repo-b"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert sorted(data["repoPaths"]) == sorted([_resolved("/test/repo-a"), _resolved("/test/repo-b")])

    @pytest.mark.asyncio
    async def test_create_rejects_repo_already_assigned_to_another_project(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/settings/projects",
            json={"name": "First", "repoPaths": ["/test/shared-repo"]},
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/settings/projects",
            json={"name": "Second", "repoPaths": ["/test/shared-repo"]},
        )
        assert second.status_code == 409

    @pytest.mark.asyncio
    async def test_create_requires_name(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/projects",
            json={"name": "", "repoPaths": ["/test/repo"]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_requires_at_least_one_repo_path(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/settings/projects",
            json={"name": "No Repos", "repoPaths": []},
        )
        assert resp.status_code == 422


class TestListAndGetProject:
    @pytest.mark.asyncio
    async def test_list_returns_created_projects(self, client: AsyncClient) -> None:
        await client.post("/api/settings/projects", json={"name": "A", "repoPaths": ["/test/a"]})
        await client.post("/api/settings/projects", json={"name": "B", "repoPaths": ["/test/b"]})

        resp = await client.get("/api/settings/projects")
        assert resp.status_code == 200
        items = resp.json()["items"]
        names = {p["name"] for p in items}
        assert {"A", "B"}.issubset(names)

    @pytest.mark.asyncio
    async def test_get_existing_project(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/settings/projects",
            json={"name": "Fetchable", "repoPaths": ["/test/fetchable"]},
        )
        project_id = created.json()["id"]

        resp = await client.get(f"/api/settings/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Fetchable"

    @pytest.mark.asyncio
    async def test_get_missing_project_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/settings/projects/does-not-exist")
        assert resp.status_code == 404


class TestUpdateProject:
    @pytest.mark.asyncio
    async def test_rename_project(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/settings/projects",
            json={"name": "Old Name", "repoPaths": ["/test/rename"]},
        )
        project_id = created.json()["id"]

        resp = await client.patch(f"/api/settings/projects/{project_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Name"
        assert data["repoPaths"] == [_resolved("/test/rename")]

    @pytest.mark.asyncio
    async def test_add_repo_to_project(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/settings/projects",
            json={"name": "Growable", "repoPaths": ["/test/growable-a"]},
        )
        project_id = created.json()["id"]

        resp = await client.patch(
            f"/api/settings/projects/{project_id}",
            json={"repoPaths": ["/test/growable-a", "/test/growable-b"]},
        )
        assert resp.status_code == 200
        assert sorted(resp.json()["repoPaths"]) == sorted(
            [_resolved("/test/growable-a"), _resolved("/test/growable-b")]
        )

    @pytest.mark.asyncio
    async def test_remove_repo_from_project(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/settings/projects",
            json={"name": "Shrinkable", "repoPaths": ["/test/shrink-a", "/test/shrink-b"]},
        )
        project_id = created.json()["id"]

        resp = await client.patch(
            f"/api/settings/projects/{project_id}",
            json={"repoPaths": ["/test/shrink-a"]},
        )
        assert resp.status_code == 200
        assert resp.json()["repoPaths"] == [_resolved("/test/shrink-a")]

    @pytest.mark.asyncio
    async def test_update_rejects_repo_already_assigned_to_another_project(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/settings/projects",
            json={"name": "First", "repoPaths": ["/test/owned-by-first"]},
        )
        second = await client.post(
            "/api/settings/projects",
            json={"name": "Second", "repoPaths": ["/test/owned-by-second"]},
        )
        second_id = second.json()["id"]
        assert first.status_code == 201

        resp = await client.patch(
            f"/api/settings/projects/{second_id}",
            json={"repoPaths": ["/test/owned-by-second", "/test/owned-by-first"]},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_update_missing_project_returns_404(self, client: AsyncClient) -> None:
        resp = await client.patch("/api/settings/projects/does-not-exist", json={"name": "X"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_is_reflected_immediately_on_get(self, client: AsyncClient) -> None:
        """AC3: an edit is saved and reflected immediately on the Project resource."""
        created = await client.post(
            "/api/settings/projects",
            json={"name": "Reflect Me", "repoPaths": ["/test/reflect"]},
        )
        project_id = created.json()["id"]

        await client.patch(f"/api/settings/projects/{project_id}", json={"name": "Reflected"})

        resp = await client.get(f"/api/settings/projects/{project_id}")
        assert resp.json()["name"] == "Reflected"
