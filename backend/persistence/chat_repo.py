"""Chat persistence.

Owns all database access for ``ChatRow``. Following AD-12/NFR8, this
module must never import ``GitService`` or any git-touching module — a
Chat is structurally incapable of a git operation.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.models.db import ChatRow
from backend.models.domain import Chat
from backend.persistence.repository import BaseRepository


class ChatRepository(BaseRepository):
    """Database access for persistent, purely conversational chats."""

    @staticmethod
    def _to_domain(row: ChatRow) -> Chat:
        return Chat(
            id=row.id,
            project_id=row.project_id,
            title=row.title,
            created_at=row.created_at,
            last_message_at=row.last_message_at,
            status=row.status,
        )

    async def create(self, chat: Chat) -> Chat:
        """Insert a new chat."""
        row = ChatRow(
            id=chat.id,
            project_id=chat.project_id,
            title=chat.title,
            created_at=chat.created_at,
            last_message_at=chat.last_message_at,
            status=chat.status,
        )
        self._session.add(row)
        await self._session.flush()
        return chat

    async def get(self, chat_id: str) -> Chat | None:
        """Get a single chat by ID."""
        stmt = select(ChatRow).where(ChatRow.id == chat_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_all(self) -> list[Chat]:
        """List all chats, most recently active first."""
        stmt = select(ChatRow).order_by(ChatRow.last_message_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]
