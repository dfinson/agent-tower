"""Sidecar template CRUD and LLM-assisted generation endpoints."""

from __future__ import annotations

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError

from backend.models.api_schemas import (
    CreateSidecarTemplateRequest,
    GenerateSidecarRequest,
    GenerateSidecarResponse,
    SidecarTemplateListResponse,
    SidecarTemplateResponse,
    UpdateSidecarTemplateRequest,
)
from backend.services.sidecar_template_service import SidecarTemplateService

log = structlog.get_logger()

router = APIRouter(tags=["sidecar-templates"], route_class=DishkaRoute)


def _to_response(template) -> SidecarTemplateResponse:
    return SidecarTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        definition_json=template.definition_json,
        created_at=template.created_at,
        last_used_at=template.last_used_at,
    )


@router.get("/sidecar-templates", response_model=SidecarTemplateListResponse)
async def list_sidecar_templates(
    service: FromDishka[SidecarTemplateService],
) -> SidecarTemplateListResponse:
    """List all saved sidecar templates."""
    templates = await service.list_templates()
    return SidecarTemplateListResponse(items=[_to_response(t) for t in templates])


@router.get("/sidecar-templates/{template_id}", response_model=SidecarTemplateResponse)
async def get_sidecar_template(
    template_id: str,
    service: FromDishka[SidecarTemplateService],
) -> SidecarTemplateResponse:
    """Get a single sidecar template by ID."""
    template = await service.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Sidecar template not found")
    return _to_response(template)


@router.post("/sidecar-templates", response_model=SidecarTemplateResponse, status_code=201)
async def create_sidecar_template(
    body: CreateSidecarTemplateRequest,
    service: FromDishka[SidecarTemplateService],
) -> SidecarTemplateResponse:
    """Create a new sidecar template."""
    try:
        template = await service.create_template(
            name=body.name,
            description=body.description,
            definition_json=body.definition_json,
        )
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A template with this name already exists") from exc
    return _to_response(template)


@router.put("/sidecar-templates/{template_id}", response_model=SidecarTemplateResponse)
async def update_sidecar_template(
    template_id: str,
    body: UpdateSidecarTemplateRequest,
    service: FromDishka[SidecarTemplateService],
) -> SidecarTemplateResponse:
    """Update an existing sidecar template."""
    try:
        template = await service.update_template(
            template_id,
            name=body.name,
            description=body.description,
            definition_json=body.definition_json,
        )
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A template with this name already exists") from exc
    if template is None:
        raise HTTPException(status_code=404, detail="Sidecar template not found")
    return _to_response(template)


@router.delete("/sidecar-templates/{template_id}", status_code=204)
async def delete_sidecar_template(
    template_id: str,
    service: FromDishka[SidecarTemplateService],
) -> None:
    """Delete a sidecar template."""
    removed = await service.delete_template(template_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Sidecar template not found")


@router.post("/sidecar-templates/generate", response_model=GenerateSidecarResponse)
async def generate_sidecar_definition(
    body: GenerateSidecarRequest,
    service: FromDishka[SidecarTemplateService],
) -> GenerateSidecarResponse:
    """Generate a sidecar definition from a natural language description."""
    try:
        definition = await service.generate_definition(body.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ConnectionError, TimeoutError, OSError) as exc:
        log.warning("sidecar_generate_failed", exc_info=exc)
        raise HTTPException(status_code=503, detail="Failed to generate sidecar definition") from exc
    return GenerateSidecarResponse(definition=definition)
