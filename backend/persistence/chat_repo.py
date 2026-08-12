"""Chat persistence.

Owns all database access for ``ChatRow``. Following AD-12/NFR8, this
module must never import ``GitService`` or any git-touching module — a
Chat is structurally incapable of a git operation.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.models.db import ChatMessageRow, ChatRow
from backend.models.domain import Chat, ChatMessage
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
            task_link_id=row.task_link_id,
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
            task_link_id=chat.task_link_id,
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

    async def set_project_id(self, chat_id: str, project_id: str) -> None:
        """Settle a Chat's ``project_id`` (e.g. on first Job launch/chain attach)."""
        stmt = select(ChatRow).where(ChatRow.id == chat_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            row.project_id = project_id
            await self._session.flush()

    async def attach_to_chain(self, chat_id: str, task_link_id: str) -> Chat | None:
        """Link a Chat to a Task Recipe chain via its entry ``TaskLink`` (Story 5.3).

        Returns the updated ``Chat``, or ``None`` if the chat does not exist.
        """
        stmt = select(ChatRow).where(ChatRow.id == chat_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.task_link_id = task_link_id
        await self._session.flush()
        return self._to_domain(row)

    async def get_attached_open_chat_for_project(self, project_id: str) -> Chat | None:
        """Find an open Chat attached to a chain in this Project (Story 5.4).

        Attaching an open Chat to any TaskLink in a Project is what puts
        that Project's chains into "gated" mode (AC #2) — a detached or
        archived/closed Chat never gates. Returns the first match; a
        Project having more than one simultaneously-attached open Chat is
        not a case this schema needs to disambiguate for gating purposes.
        """
        stmt = select(ChatRow).where(
            ChatRow.project_id == project_id,
            ChatRow.task_link_id.is_not(None),
            ChatRow.status == "open",
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        return self._to_domain(row) if row is not None else None

    async def detach_from_chain(self, chat_id: str) -> Chat | None:
        """Clear a Chat's chain attachment (Story 5.3). The chain itself is untouched.

        Returns the updated ``Chat``, or ``None`` if the chat does not exist.
        """
        stmt = select(ChatRow).where(ChatRow.id == chat_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.task_link_id = None
        await self._session.flush()
        return self._to_domain(row)

    @staticmethod
    def _message_to_domain(row: ChatMessageRow) -> ChatMessage:
        return ChatMessage(
            id=row.id,
            chat_id=row.chat_id,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
        )

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        """Append a message to a Chat's transcript and bump ``last_message_at``."""
        row = ChatMessageRow(
            id=message.id,
            chat_id=message.chat_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )
        self._session.add(row)

        chat_stmt = select(ChatRow).where(ChatRow.id == message.chat_id)
        chat_result = await self._session.execute(chat_stmt)
        chat_row = chat_result.scalar_one_or_none()
        if chat_row is not None:
            chat_row.last_message_at = message.created_at

        await self._session.flush()
        return message

    async def list_messages(self, chat_id: str) -> list[ChatMessage]:
        """List a Chat's messages in transcript order (oldest first)."""
        stmt = select(ChatMessageRow).where(ChatMessageRow.chat_id == chat_id).order_by(ChatMessageRow.created_at.asc())
        result = await self._session.execute(stmt)
        return [self._message_to_domain(row) for row in result.scalars().all()]
