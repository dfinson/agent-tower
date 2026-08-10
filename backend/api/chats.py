"""Chat CRUD endpoints — persistent, purely conversational chats (CAP-12/AD-12).

Thin routes only: validate input, delegate to ``ChatService``, return the
result. This router must never import ``GitService``.
"""

from __future__ import annotations

import asyncio

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.api_schemas import (
    AddChatMessageRequest,
    ChatListResponse,
    ChatMessageResponse,
    ChatResponse,
    CreateChatRequest,
    CreateJobResponse,
    LaunchJobFromChatRequest,
)
from backend.models.domain import Chat, ChatMessage, JobState
from backend.services.chat.chat_service import ChatService
from backend.services.job.job_service import JobService
from backend.services.runtime import RuntimeService

log = structlog.get_logger()

router = APIRouter(tags=["chats"], route_class=DishkaRoute)


def _to_response(chat: Chat) -> ChatResponse:
    return ChatResponse(
        id=chat.id,
        project_id=chat.project_id,
        title=chat.title,
        created_at=chat.created_at,
        last_message_at=chat.last_message_at,
        status=chat.status,
    )


def _message_to_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        chat_id=message.chat_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )


def _job_to_create_response(job) -> CreateJobResponse:  # noqa: ANN001
    return CreateJobResponse(
        id=job.id,
        state=job.state,
        title=job.title,
        branch=job.branch,
        worktree_path=job.worktree_path,
        sdk=job.sdk,
        created_at=job.created_at,
    )


@router.post("/chats", response_model=ChatResponse, status_code=201)
async def create_chat(
    body: CreateChatRequest,
    service: FromDishka[ChatService],
    session: FromDishka[AsyncSession],
) -> ChatResponse:
    """Start a new Chat. ``project_id`` defaults from caller context and is user-overridable."""
    chat = await service.create_chat(title=body.title, project_id=body.project_id)
    await session.commit()
    return _to_response(chat)


@router.get("/chats", response_model=ChatListResponse)
async def list_chats(
    service: FromDishka[ChatService],
) -> ChatListResponse:
    """List all chats."""
    chats = await service.list_chats()
    return ChatListResponse(items=[_to_response(c) for c in chats])


@router.get("/chats/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: str,
    service: FromDishka[ChatService],
) -> ChatResponse:
    """Get a single chat by ID."""
    chat = await service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return _to_response(chat)


@router.post("/chats/{chat_id}/messages", response_model=ChatMessageResponse, status_code=201)
async def add_chat_message(
    chat_id: str,
    body: AddChatMessageRequest,
    service: FromDishka[ChatService],
    session: FromDishka[AsyncSession],
) -> ChatMessageResponse:
    """Append a message to a Chat's transcript."""
    message = await service.add_message(chat_id, role=body.role, content=body.content)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    await session.commit()
    return _message_to_response(message)


@router.post("/chats/{chat_id}/launch-job", response_model=CreateJobResponse, status_code=201)
async def launch_job_from_chat(
    chat_id: str,
    body: LaunchJobFromChatRequest,
    service: FromDishka[ChatService],
    job_service: FromDishka[JobService],
    runtime_service: FromDishka[RuntimeService],
    session: FromDishka[AsyncSession],
) -> CreateJobResponse:
    """Launch a new Job from this Chat, seeded from its transcript (CAP-12/AD-12).

    Provisions a worktree/branch for the first time at this call — the
    Chat itself remains open and unconsumed, and can launch further,
    independent Jobs later (Story 5.2).
    """
    job = await service.launch_job(
        chat_id,
        job_service,
        repo=body.repo,
        base_ref=body.base_ref,
        branch=body.branch,
        model=body.model,
        sdk=body.sdk,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Commit so the job row is visible to the background setup task (separate session).
    await session.commit()

    if job.state != JobState.failed:

        async def _setup_and_start() -> None:
            try:
                await runtime_service.setup_and_start(job)
            except Exception:
                log.error("background_job_setup_failed", job_id=job.id, exc_info=True)

        asyncio.create_task(_setup_and_start(), name=f"setup-{job.id}")

    return _job_to_create_response(job)

