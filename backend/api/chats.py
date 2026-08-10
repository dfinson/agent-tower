"""Chat CRUD endpoints — persistent, purely conversational chats (CAP-12/AD-12).

Thin routes only: validate input, delegate to ``ChatService``, return the
result. This router must never import ``GitService``.
"""

from __future__ import annotations

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.api_schemas import ChatListResponse, ChatResponse, CreateChatRequest
from backend.models.domain import Chat
from backend.services.chat.chat_service import ChatService

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
