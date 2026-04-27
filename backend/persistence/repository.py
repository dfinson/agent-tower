"""Base repository pattern."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Base class for repository pattern database access.

    Uses a shared request-scoped ``AsyncSession`` injected by the DI container.
    The session is committed/rolled-back by the DI provider after the request.

    Two session strategies exist in this persistence layer:

    * **Shared session** (this base class) — used by most repositories.
      Repositories share a single session per HTTP request, enabling
      transactional consistency across multiple repository calls.

    * **Session factory** (``StepRepository``, ``TrailNodeRepository``) —
      each operation creates and commits its own session via
      ``async_sessionmaker``.  Used for fire-and-forget writes that must
      persist independently of the request lifecycle (e.g. event-driven
      step tracking that runs outside a request context).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
