"""Test that the health endpoint returns a valid response."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.deps import get_db_session
from backend.main import create_app
from backend.models.db import Base

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
async def app() -> FastAPI:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    application = create_app(dev=True)

    async def _override() -> AsyncSession:  # type: ignore[misc]
        async with session_factory() as s:
            yield s  # type: ignore[misc]

    application.dependency_overrides[get_db_session] = _override
    return application


@pytest.mark.asyncio
async def test_health_returns_healthy(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["version"]
    assert "uptimeSeconds" in data
