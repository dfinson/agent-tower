"""Integration tests for the chats API endpoints.

Exercises:
  POST /api/chats
  GET  /api/chats
  GET  /api/chats/{id}
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
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
