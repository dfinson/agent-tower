"""Shared FastAPI dependencies for route handlers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session() -> AsyncSession:
    """Yield a database session with commit/rollback lifecycle.

    This is a placeholder — the real async-generator dependency is wired
    via ``app.dependency_overrides`` during application startup in
    ``backend.lifespan``.
    """
    raise NotImplementedError("Session factory not wired")  # pragma: no cover
