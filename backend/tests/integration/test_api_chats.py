"""Integration tests for the chats API endpoints.

Exercises:
  POST /api/chats
  GET  /api/chats
  GET  /api/chats/{id}
  POST /api/chats/{id}/messages
  POST /api/chats/{id}/launch-job
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from httpx import AsyncClient


class TestCreateChat:
    """POST /api/chats"""

    @pytest.mark.asyncio
    async def test_create_without_project_id_defaults_to_null(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.post("/api/chats", json={"title": "Thinking something through"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Thinking something through"
        assert data["projectId"] is None
        assert data["status"] == "open"
        assert data["id"]
        assert data["createdAt"]
        assert data["lastMessageAt"]

    @pytest.mark.asyncio
    async def test_create_with_project_id(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.post(
            "/api/chats",
            json={"title": "Project-scoped chat", "projectId": "proj-123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["projectId"] == "proj-123"

    @pytest.mark.asyncio
    async def test_create_requires_title(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.post("/api/chats", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_rejects_empty_title(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.post("/api/chats", json={"title": ""})
        assert resp.status_code == 422


class TestListChats:
    """GET /api/chats"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.get("/api/chats")
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    @pytest.mark.asyncio
    async def test_list_returns_created_chats(self, client: AsyncClient, app: FastAPI) -> None:
        await client.post("/api/chats", json={"title": "First"})
        await client.post("/api/chats", json={"title": "Second"})

        resp = await client.get("/api/chats")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        titles = {item["title"] for item in items}
        assert titles == {"First", "Second"}


class TestGetChat:
    """GET /api/chats/{id}"""

    @pytest.mark.asyncio
    async def test_get_existing_chat(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Findable"})
        chat_id = create_resp.json()["id"]

        resp = await client.get(f"/api/chats/{chat_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == chat_id
        assert resp.json()["title"] == "Findable"

    @pytest.mark.asyncio
    async def test_get_missing_chat_returns_404(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.get("/api/chats/does-not-exist")
        assert resp.status_code == 404


class TestAddChatMessage:
    """POST /api/chats/{id}/messages"""

    @pytest.mark.asyncio
    async def test_add_message_returns_201(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Thinking"})
        chat_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/chats/{chat_id}/messages",
            json={"role": "user", "content": "Let's figure out the login bug"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chatId"] == chat_id
        assert data["role"] == "user"
        assert data["content"] == "Let's figure out the login bug"
        assert data["id"]
        assert data["createdAt"]

    @pytest.mark.asyncio
    async def test_add_message_to_missing_chat_returns_404(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.post(
            "/api/chats/does-not-exist/messages",
            json={"role": "user", "content": "hi"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_message_requires_content(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Thinking"})
        chat_id = create_resp.json()["id"]

        resp = await client.post(f"/api/chats/{chat_id}/messages", json={"role": "user"})
        assert resp.status_code == 422


class TestLaunchJobFromChat:
    """POST /api/chats/{id}/launch-job"""

    @pytest.fixture(autouse=True)
    def _patch_git_for_launch(self, monkeypatch: pytest.MonkeyPatch, mock_git_service: AsyncMock) -> None:
        """Same pattern as test_api_jobs.py: launch-job provisions a real
        worktree/branch via GitService, so the module-level GitService
        class must resolve to the mock, not hit real git."""
        monkeypatch.setattr(
            "backend.services.git.git_service.GitService",
            lambda config: mock_git_service,
        )

    @pytest.mark.asyncio
    async def test_launch_job_creates_job_seeded_from_transcript(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Thinking it through"})
        chat_id = create_resp.json()["id"]
        await client.post(
            f"/api/chats/{chat_id}/messages",
            json={"role": "user", "content": "Please fix the login bug"},
        )

        resp = await client.post(
            f"/api/chats/{chat_id}/launch-job",
            json={"repo": "/test/repo"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"]
        assert data["state"] in ("preparing", "queued", "running")

    @pytest.mark.asyncio
    async def test_launch_job_leaves_chat_open_and_unchanged(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Thinking it through"})
        chat_id = create_resp.json()["id"]

        await client.post(f"/api/chats/{chat_id}/launch-job", json={"repo": "/test/repo"})

        get_resp = await client.get(f"/api/chats/{chat_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["status"] == "open"
        assert data["title"] == "Thinking it through"

    @pytest.mark.asyncio
    async def test_launch_job_twice_creates_two_independent_jobs(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Thinking it through"})
        chat_id = create_resp.json()["id"]

        resp_1 = await client.post(f"/api/chats/{chat_id}/launch-job", json={"repo": "/test/repo"})
        resp_2 = await client.post(f"/api/chats/{chat_id}/launch-job", json={"repo": "/test/repo"})

        assert resp_1.status_code == 201
        assert resp_2.status_code == 201
        assert resp_1.json()["id"] != resp_2.json()["id"]

    @pytest.mark.asyncio
    async def test_launch_job_settles_null_project_id(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "Global-nav chat"})
        chat_id = create_resp.json()["id"]
        assert create_resp.json()["projectId"] is None

        await client.post(f"/api/chats/{chat_id}/launch-job", json={"repo": "/test/repo"})

        get_resp = await client.get(f"/api/chats/{chat_id}")
        assert get_resp.json()["projectId"] == "/test/repo"

    @pytest.mark.asyncio
    async def test_launch_job_from_missing_chat_returns_404(self, client: AsyncClient, app: FastAPI) -> None:
        resp = await client.post(
            "/api/chats/does-not-exist/launch-job",
            json={"repo": "/test/repo"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_launch_job_requires_repo(self, client: AsyncClient, app: FastAPI) -> None:
        create_resp = await client.post("/api/chats", json={"title": "No repo"})
        chat_id = create_resp.json()["id"]

        resp = await client.post(f"/api/chats/{chat_id}/launch-job", json={})
        assert resp.status_code == 422
