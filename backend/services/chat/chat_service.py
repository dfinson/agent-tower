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

from backend.models.domain import Chat, ChatMessage, JobSpec

if TYPE_CHECKING:
    from backend.models.domain import Job
    from backend.persistence.chat_repo import ChatRepository
    from backend.services.job.job_service import JobService


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

    async def add_message(self, chat_id: str, *, role: str, content: str) -> ChatMessage | None:
        """Append a message to a Chat's transcript.

        Returns ``None`` if the chat does not exist. Bumps
        ``ChatRow.last_message_at`` as a side effect of persistence.
        """
        chat = await self._repo.get(chat_id)
        if chat is None:
            return None
        message = ChatMessage(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role=role,
            content=content,
            created_at=datetime.now(UTC),
        )
        return await self._repo.add_message(message)

    async def build_transcript(self, chat_id: str) -> str | None:
        """Concatenate a Chat's messages, role-prefixed, in transcript order.

        Returns ``None`` if the chat does not exist. An empty transcript
        (a chat with no messages yet) is returned as ``""``, not an error —
        launching a Job from a fresh Chat is still valid.
        """
        chat = await self._repo.get(chat_id)
        if chat is None:
            return None
        messages = await self._repo.list_messages(chat_id)
        return "\n".join(f"{m.role}: {m.content}" for m in messages)

    async def launch_job(
        self,
        chat_id: str,
        job_service: JobService,
        *,
        repo: str,
        base_ref: str | None = None,
        branch: str | None = None,
        model: str | None = None,
        sdk: str | None = None,
    ) -> Job | None:
        """Launch a new Job seeded from this Chat's transcript (AD-12/CAP-12, Story 5.2).

        Delegates job/worktree/branch creation entirely to ``JobService``
        (the same job-creation function AD-10 uses for ``spawn_task``) —
        this module never provisions git state itself. Returns ``None`` if
        the chat does not exist.

        The Chat itself is never consumed or transformed: it remains
        ``"open"`` and can launch further, independent Jobs later. If its
        ``project_id`` is still null, it is settled from ``repo`` at this
        call (no ``ProjectRow``/Project registry exists yet in this
        codebase, so ``project_id`` remains a plain nullable string).
        """
        chat = await self._repo.get(chat_id)
        if chat is None:
            return None

        transcript = await self.build_transcript(chat_id)
        assert transcript is not None  # chat existence already checked above

        spec = JobSpec(
            repo=repo,
            prompt=transcript,
            base_ref=base_ref,
            branch=branch,
            model=model,
            sdk=sdk,
        )
        job = await job_service.create_job(spec)

        if chat.project_id is None:
            await self._repo.set_project_id(chat_id, repo)

        return job

