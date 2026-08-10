"""Integration tests for TaskLink ingestion endpoints (Story 4.2 / CAP-9).

Exercises:
  POST /api/settings/projects/{id}/ingest-tasks
  GET  /api/settings/projects/{id}/task-links
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient


def _write_bmad_story(repo_root: Path, filename: str, body: str = "# S\n") -> None:
    stories_dir = repo_root / "_bmad-output" / "implementation-artifacts"
    stories_dir.mkdir(parents=True, exist_ok=True)
    (stories_dir / filename).write_text(body, encoding="utf-8")


class TestIngestTasks:
    @pytest.mark.asyncio
    async def test_ingest_creates_task_links_for_member_repos(
        self, client: AsyncClient, tmp_path: Path
    ) -> None:
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "1-1-first.md")
        _write_bmad_story(repo_a, "1-2-second.md", "# S\n\n## Dependencies\n\n- 1-1-first\n")

        created = await client.post(
            "/api/settings/projects",
            json={"name": "Ingest Me", "repoPaths": [str(repo_a)]},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        resp = await client.post(f"/api/settings/projects/{project_id}/ingest-tasks")
        assert resp.status_code == 201
        items = resp.json()["items"]
        assert len(items) == 2
        by_node = {i["storyNodeId"]: i for i in items}
        assert by_node["1-1-first"]["epicId"] == "epic-1"
        assert by_node["1-2-second"]["dependsOn"][0].endswith("::1-1-first")

    @pytest.mark.asyncio
    async def test_reingest_upserts_not_duplicates(self, client: AsyncClient, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-b"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "2-1-task.md")

        created = await client.post(
            "/api/settings/projects",
            json={"name": "Reingest Me", "repoPaths": [str(repo_a)]},
        )
        project_id = created.json()["id"]

        first = await client.post(f"/api/settings/projects/{project_id}/ingest-tasks")
        second = await client.post(f"/api/settings/projects/{project_id}/ingest-tasks")

        assert len(first.json()["items"]) == 1
        assert len(second.json()["items"]) == 1
        assert first.json()["items"][0]["id"] == second.json()["items"][0]["id"]

    @pytest.mark.asyncio
    async def test_ingest_missing_project_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post("/api/settings/projects/does-not-exist/ingest-tasks")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ingest_never_writes_to_source_repo(self, client: AsyncClient, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-c"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "3-1-task.md")
        story_file = repo_a / "_bmad-output" / "implementation-artifacts" / "3-1-task.md"
        before = story_file.read_text(encoding="utf-8")

        created = await client.post(
            "/api/settings/projects",
            json={"name": "Read Only", "repoPaths": [str(repo_a)]},
        )
        project_id = created.json()["id"]
        await client.post(f"/api/settings/projects/{project_id}/ingest-tasks")

        assert story_file.read_text(encoding="utf-8") == before


class TestListTaskLinks:
    @pytest.mark.asyncio
    async def test_list_returns_ingested_task_links(self, client: AsyncClient, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-d"
        repo_a.mkdir()
        _write_bmad_story(repo_a, "5-1-task.md")

        created = await client.post(
            "/api/settings/projects",
            json={"name": "Listable", "repoPaths": [str(repo_a)]},
        )
        project_id = created.json()["id"]
        await client.post(f"/api/settings/projects/{project_id}/ingest-tasks")

        resp = await client.get(f"/api/settings/projects/{project_id}/task-links")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    @pytest.mark.asyncio
    async def test_list_before_ingest_is_empty(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/settings/projects",
            json={"name": "Empty Project", "repoPaths": ["/test/empty-proj"]},
        )
        project_id = created.json()["id"]

        resp = await client.get(f"/api/settings/projects/{project_id}/task-links")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @pytest.mark.asyncio
    async def test_list_missing_project_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/settings/projects/does-not-exist/task-links")
        assert resp.status_code == 404
