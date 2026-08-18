"""TrackerLink attach/list API (Story 3.2, CAP-7/AD-6).

Attach a global Credential to a Project along with an external
project/board reference. A Project may have more than one TrackerLink
(e.g. referencing two external boards), and any number of Projects may
attach the same Credential (Credential is global, not consumed
per-attachment).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import Response

from backend.models.schemas.base import CamelModel
from backend.persistence.tracker_link_repo import (
    TrackerLinkCredentialNotFoundError,
    TrackerLinkProjectNotFoundError,
    TrackerLinkRepository,
)
from backend.persistence.tracker_summary_repo import TrackerSummaryRepository
from backend.services.tracker_sync_service import (
    TrackerLinkNotFoundError,
    TrackerLinkValidationError,
    TrackerSyncError,
    TrackerSyncService,
)

router = APIRouter(prefix="/projects/{project_id}/tracker-links", tags=["tracker-links"], route_class=DishkaRoute)
log = structlog.get_logger()


class TrackerTicketResponse(CamelModel):
    id: str
    title: str
    status: str
    url: str | None = None


class TrackerSummaryResponse(CamelModel):
    tracker_link_id: str
    tickets: list[TrackerTicketResponse] = Field(default_factory=list)
    last_synced_at: str | None = None
    last_error: str | None = None


class TrackerLinkResponse(CamelModel):
    id: str
    project_id: str
    credential_id: str
    external_ref: str
    created_at: str
    summary: TrackerSummaryResponse | None = None


class TrackerLinkListResponse(CamelModel):
    tracker_links: list[TrackerLinkResponse] = Field(default_factory=list)


class CreateTrackerLinkRequest(CamelModel):
    credential_id: str = Field(min_length=1)
    external_ref: str = Field(min_length=1)


def _to_response(
    data: dict[str, Any],
    summary: dict[str, Any] | None = None,
) -> TrackerLinkResponse:
    return TrackerLinkResponse(**data, summary=TrackerSummaryResponse(**summary) if summary else None)


@router.get("", response_model=TrackerLinkListResponse)
async def list_tracker_links(
    project_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> TrackerLinkListResponse:
    async with sf() as session:
        repo = TrackerLinkRepository(session)
        rows = await repo.list_for_project(project_id)
        summaries = await TrackerSummaryRepository(session).list_for_project(project_id)
    return TrackerLinkListResponse(
        tracker_links=[_to_response(row, summaries.get(row["id"])) for row in rows]
    )


@router.post("", response_model=TrackerLinkResponse, status_code=201)
async def create_tracker_link(
    project_id: str,
    body: CreateTrackerLinkRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    tracker_sync_service: FromDishka[TrackerSyncService],
) -> TrackerLinkResponse:
    link_id = str(uuid.uuid4())
    async with sf() as session:
        repo = TrackerLinkRepository(session)
        try:
            result = await repo.create(
                link_id=link_id,
                project_id=project_id,
                credential_id=body.credential_id,
                external_ref=body.external_ref,
            )
        except TrackerLinkProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TrackerLinkCredentialNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            await tracker_sync_service.test_link(
                credential_id=body.credential_id,
                external_ref=body.external_ref,
            )
        except TrackerLinkValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TrackerSyncError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        await session.commit()
    log.info("tracker_link.created", tracker_link_id=link_id, project_id=project_id, credential_id=body.credential_id)
    return _to_response(result)


@router.delete(
    "/{link_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
)
async def detach_tracker_link(
    project_id: str,
    link_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> None:
    async with sf() as session:
        deleted = await TrackerLinkRepository(session).delete_for_project(
            project_id=project_id,
            link_id=link_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"TrackerLink '{link_id}' does not exist in Project '{project_id}'",
            )
        await session.commit()
    log.info("tracker_link.detached", tracker_link_id=link_id, project_id=project_id)


@router.post(
    "/{link_id}/refresh",
    response_model=TrackerSummaryResponse,
)
async def refresh_tracker_link(
    project_id: str,
    link_id: str,
    tracker_sync_service: FromDishka[TrackerSyncService],
) -> TrackerSummaryResponse:
    try:
        summary = await tracker_sync_service.refresh_link(
            project_id=project_id,
            link_id=link_id,
        )
    except TrackerLinkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrackerSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TrackerSummaryResponse(**summary)
