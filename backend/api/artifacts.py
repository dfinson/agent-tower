"""Artifact retrieval endpoints."""

from __future__ import annotations

from pathlib import Path

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.models.api_schemas import ArtifactListResponse, ArtifactResponse
from backend.services.artifact_service import ArtifactService, get_artifacts_base

router = APIRouter(tags=["artifacts"], route_class=DishkaRoute)


@router.get("/jobs/{job_id}/artifacts", response_model=ArtifactListResponse)
async def list_artifacts(
    job_id: str,
    svc: FromDishka[ArtifactService],
) -> ArtifactListResponse:
    """List all artifacts for a job."""
    artifacts = await svc.list_for_job(job_id)

    items = [
        ArtifactResponse(
            id=a.id,
            job_id=a.job_id,
            name=a.name,
            type=a.type,
            mime_type=a.mime_type,
            size_bytes=a.size_bytes,
            phase=a.phase,
            created_at=a.created_at,
        )
        for a in artifacts
    ]
    return ArtifactListResponse(items=items)


@router.get("/artifacts/{artifact_id}", response_class=FileResponse)
async def download_artifact(
    artifact_id: str,
    svc: FromDishka[ArtifactService],
) -> FileResponse:
    """Download an artifact file."""
    artifact = await svc.get(artifact_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    disk_path = Path(artifact.disk_path).resolve()
    # Validate artifact path is within the expected artifacts directory
    if not disk_path.is_relative_to(get_artifacts_base().resolve()):
        raise HTTPException(status_code=403, detail="Artifact path outside allowed directory")
    if not disk_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file missing from disk")

    return FileResponse(
        path=str(disk_path),
        media_type=artifact.mime_type,
        filename=artifact.name,
    )
