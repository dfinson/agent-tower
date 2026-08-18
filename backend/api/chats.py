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
    AttachChatToChainRequest,
    ChatChainStatusResponse,
    ChatListResponse,
    ChatMessageResponse,
    ChatResponse,
    ChatTurnResponse,
    CreateChatRequest,
    CreateJobResponse,
    LaunchJobFromChatRequest,
)
from backend.models.domain import Chat, ChatMessage, Job, JobState
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
        task_link_id=chat.task_link_id,
    )


def _message_to_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        chat_id=message.chat_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )


def _job_to_create_response(job: Job) -> CreateJobResponse:
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
    project_id: str | None = None,
) -> ChatListResponse:
    """List all chats."""
    chats = await service.list_chats(project_id=project_id)
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


@router.get("/chats/{chat_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_messages(
    chat_id: str,
    service: FromDishka[ChatService],
) -> list[ChatMessageResponse]:
    """Return the append-only transcript for a Chat."""
    if await service.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await service.list_messages(chat_id)
    return [_message_to_response(message) for message in messages]


@router.post("/chats/{chat_id}/turns", response_model=ChatTurnResponse)
async def send_chat_turn(
    chat_id: str,
    body: AddChatMessageRequest,
    service: FromDishka[ChatService],
    session: FromDishka[AsyncSession],
) -> ChatTurnResponse:
    """Persist a user message and return its assistant completion or failure state."""
    user_message = await service.begin_turn(chat_id, content=body.content)
    if user_message is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    # The provider may take an arbitrary amount of time or fail. Make the
    # user's message durable and visible to other sessions before awaiting it.
    await session.commit()
    result = await service.complete_turn(chat_id, user_message=user_message)
    if result.assistant_message is not None:
        await session.commit()
    return ChatTurnResponse(
        user_message=_message_to_response(result.user_message),
        assistant_message=(
            _message_to_response(result.assistant_message)
            if result.assistant_message is not None
            else None
        ),
        state=result.state,
        error=result.error,
    )


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


@router.post("/chats/{chat_id}/attach-chain", response_model=ChatResponse)
async def attach_chat_to_chain(
    chat_id: str,
    body: AttachChatToChainRequest,
    service: FromDishka[ChatService],
    session: FromDishka[AsyncSession],
) -> ChatResponse:
    """Attach a Chat to a Task Recipe chain via its entry TaskLink (Story 5.3).

    Settles ``project_id`` from the TaskLink's Project if it was still
    null. A pure linking operation — never touches ``GitService`` or
    creates a Job. Raises 404 (via ``TaskLinkNotFoundError``'s global
    handler) if the TaskLink does not exist.
    """
    chat = await service.attach_to_chain(chat_id, body.task_link_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    await session.commit()
    return _to_response(chat)


@router.post("/chats/{chat_id}/detach-chain", response_model=ChatResponse)
async def detach_chat_from_chain(
    chat_id: str,
    service: FromDishka[ChatService],
    session: FromDishka[AsyncSession],
) -> ChatResponse:
    """Detach a Chat from its Task Recipe chain (Story 5.3).

    The chain continues to run exactly as before; only the Chat's link to
    it is cleared, and the Chat remains open.
    """
    chat = await service.detach_from_chain(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    await session.commit()
    return _to_response(chat)


@router.get("/chats/{chat_id}/chain-status", response_model=ChatChainStatusResponse)
async def get_chat_chain_status(
    chat_id: str,
    service: FromDishka[ChatService],
) -> ChatChainStatusResponse:
    """Read-only narration snapshot of a Chat's attached chain (Story 5.3, AC 2).

    Purely reflects existing TaskLink/Job state via read-only polling —
    never calls ``GitService`` or any job-creation function. 404s if the
    chat does not exist or has nothing attached.
    """
    status = await service.get_chain_status(chat_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Chat not found or has no attached chain")
    return ChatChainStatusResponse(
        task_link_id=status.task_link_id,
        story_node_id=status.story_node_id,
        repo_path=status.repo_path,
        job_id=status.job_id,
        job_state=status.job_state,
    )
