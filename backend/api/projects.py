"""Project management endpoints (Story 2.1 / CAP-6).

Thin routes: validate input, delegate to ``ProjectService``, return the
result. ``ProjectRow`` is the sole persistence entity for repo-path
membership (AD-5) — creating/editing a Project is the only way a repo path
is durably registered going forward.
"""

from __future__ import annotations

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from backend.models.api_schemas import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    UpdateProjectRequest,
)
from backend.models.domain import Project
from backend.services.project.project_service import ProjectService

router = APIRouter(tags=["projects"], route_class=DishkaRoute)


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        repo_paths=project.repo_paths,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.post("/settings/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    project_service: FromDishka[ProjectService],
) -> ProjectResponse:
    """Create a new Project, registering each repo path (AD-5)."""
    project = await project_service.create(name=body.name, repo_paths=body.repo_paths)
    return _to_response(project)


@router.get("/settings/projects", response_model=ProjectListResponse)
async def list_projects(
    project_service: FromDishka[ProjectService],
) -> ProjectListResponse:
    """List all registered Projects."""
    projects = await project_service.list()
    return ProjectListResponse(items=[_to_response(p) for p in projects])


@router.get("/settings/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    project_service: FromDishka[ProjectService],
) -> ProjectResponse:
    """Get a single Project by ID."""
    project = await project_service.get(project_id)
    return _to_response(project)


@router.patch("/settings/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    project_service: FromDishka[ProjectService],
) -> ProjectResponse:
    """Rename a Project and/or replace its repo membership."""
    project = await project_service.update(project_id, name=body.name, repo_paths=body.repo_paths)
    return _to_response(project)
