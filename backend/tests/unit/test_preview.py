"""Tests for the preview proxy endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.preview import router
from backend.di import PreviewHttpClient


@pytest.fixture()
def preview_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture()
def app(preview_client: AsyncMock) -> FastAPI:
    """Minimal FastAPI app with the preview router and a mock DI override."""
    from dishka import make_async_container, Provider, Scope, provide
    from dishka.integrations.fastapi import setup_dishka

    class TestProvider(Provider):
        scope = Scope.REQUEST

        @provide
        def client(self) -> PreviewHttpClient:
            return PreviewHttpClient(preview_client)

    app = FastAPI()
    app.include_router(router, prefix="/api")
    container = make_async_container(TestProvider())
    setup_dishka(container, app)
    return app


class TestPreviewProxy:
    @pytest.mark.anyio()
    async def test_port_below_1024_rejected(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/preview/80/index.html")
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    @pytest.mark.anyio()
    async def test_port_above_65535_rejected(self, app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/preview/70000/index.html")
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    @pytest.mark.anyio()
    async def test_successful_proxy(self, app: FastAPI, preview_client: AsyncMock) -> None:
        upstream = httpx.Response(
            200,
            content=b"<html>OK</html>",
            headers={"content-type": "text/html"},
        )
        preview_client.request.return_value = upstream

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/preview/3000/index.html")

        assert resp.status_code == 200
        assert resp.text == "<html>OK</html>"
        preview_client.request.assert_called_once()

    @pytest.mark.anyio()
    async def test_upstream_connection_error_returns_502(self, app: FastAPI, preview_client: AsyncMock) -> None:
        preview_client.request.side_effect = httpx.ConnectError("refused")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/preview/3000/")

        assert resp.status_code == 502
        assert "Cannot connect" in resp.json()["detail"]

    @pytest.mark.anyio()
    async def test_query_string_forwarded(self, app: FastAPI, preview_client: AsyncMock) -> None:
        upstream = httpx.Response(200, content=b"ok")
        preview_client.request.return_value = upstream

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/api/preview/8080/path?foo=bar&baz=1")

        call_args = preview_client.request.call_args
        assert "foo=bar" in call_args.kwargs["url"]

    @pytest.mark.anyio()
    async def test_blocked_headers_not_forwarded(self, app: FastAPI, preview_client: AsyncMock) -> None:
        upstream = httpx.Response(200, content=b"ok")
        preview_client.request.return_value = upstream

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get(
                "/api/preview/3000/",
                headers={"x-forwarded-for": "evil", "x-real-ip": "evil"},
            )

        call_args = preview_client.request.call_args
        forwarded = call_args.kwargs.get("headers", {})
        assert "x-forwarded-for" not in forwarded
        assert "x-real-ip" not in forwarded
