"""Chat service — owns ``ChatRow`` lifecycle.

AD-12 / NFR8: a Chat is a persistent, purely conversational entity with
zero git footprint. This module must never import ``GitService`` or any
git-touching module — that is a structural, not behavioral, guarantee.
Read-only repo context (if ever needed by a later story) must go through
existing workspace read tools, never a git write path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.models.domain import Chat

if TYPE_CHECKING:
    from backend.persistence.chat_repo import ChatRepository


class ChatService:
    """Manages the lifecycle of persistent, git-free chats."""

    def __init__(self, repo: ChatRepository) -> None:
        self._repo = repo

    async def create_chat(self, *, title: str, project_id: str | None = None) -> Chat:
        """Create a new Chat.

        ``project_id`` defaults to whatever the caller passes — the API
        layer resolves this from UI context (a Project's id if started
        from within one, ``None`` from global nav) — and is always
        user-overridable at creation time.
        """
        now = datetime.now(UTC)
        chat = Chat(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=title,
            created_at=now,
            last_message_at=now,
            status="open",
        )
        return await self._repo.create(chat)

    async def get_chat(self, chat_id: str) -> Chat | None:
        """Get a single chat by ID."""
        return await self._repo.get(chat_id)

    async def list_chats(self) -> list[Chat]:
        """List all chats."""
        return await self._repo.list_all()
