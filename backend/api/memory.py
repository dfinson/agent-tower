"""Workspace memory API endpoints."""

from __future__ import annotations

from pathlib import Path

import structlog
from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import load_config
from backend.models.schemas.base import CamelModel
from backend.services.memory_compacter import MemoryCompacter
from backend.services.workspace_memory import (
    compact_decisions,
    read_memory_detail,
    read_memory_text,
    write_decisions,
    write_wisdom,
)

log = structlog.get_logger()

router = APIRouter(tags=["memory"], route_class=DishkaRoute)


# -- Schemas ----------------------------------------------------------------

class MemoryResponse(CamelModel):
    memory: str
    has_memory: bool


class MemoryDetailResponse(CamelModel):
    decisions: str
    wisdom: str
    archive: str
    has_memory: bool


# 512KB — generous limit for hand-edited text, prevents accidental or
# malicious multi-MB payloads from hitting disk.
_MAX_MEMORY_FIELD_BYTES = 512 * 1024


class UpdateMemoryRequest(BaseModel):
    decisions: str | None = None
    wisdom: str | None = None


class CompactResponse(CamelModel):
    compacted: bool


# -- Helpers ----------------------------------------------------------------

def _validate_repo(repo_path: str) -> str:
    """Resolve and validate the repo path is in the allowlist."""
    import glob as globmod

    resolved = str(Path(repo_path).expanduser().resolve())

    # Build allowlist (same logic as JobService._resolve_repos)
    fresh_repos = load_config().repos
    allowed: set[str] = set()
    for pattern in fresh_repos:
        expanded = Path(pattern).expanduser()
        if "*" in pattern or "?" in pattern:
            for match in globmod.glob(str(expanded), recursive=True):
                p = Path(match).resolve()
                if p.is_dir() and (p / ".git").exists():
                    allowed.add(str(p))
        else:
            allowed.add(str(expanded.resolve()))

    if resolved not in allowed:
        raise HTTPException(status_code=403, detail="Repository not in allowlist")
    return resolved


# -- Endpoints --------------------------------------------------------------


@router.get("/repos/{repo_path:path}/memory", response_model=MemoryResponse)
def get_memory(repo_path: str) -> MemoryResponse:
    """Read current workspace memory for a repository."""
    resolved = _validate_repo(repo_path)
    text = read_memory_text(resolved)
    return MemoryResponse(memory=text, has_memory=bool(text))


@router.get("/repos/{repo_path:path}/memory/detail", response_model=MemoryDetailResponse)
def get_memory_detail(repo_path: str) -> MemoryDetailResponse:
    """Read workspace memory with decisions, wisdom, and archive separated."""
    resolved = _validate_repo(repo_path)
    detail = read_memory_detail(resolved)
    has = bool(detail["decisions"] or detail["wisdom"] or detail["archive"])
    return MemoryDetailResponse(
        decisions=detail["decisions"],
        wisdom=detail["wisdom"],
        archive=detail["archive"],
        has_memory=has,
    )


@router.put("/repos/{repo_path:path}/memory", response_model=MemoryResponse)
def update_memory(repo_path: str, body: UpdateMemoryRequest) -> MemoryResponse:
    """Update workspace memory (decisions and/or wisdom)."""
    resolved = _validate_repo(repo_path)
    if body.decisions is not None:
        if len(body.decisions.encode("utf-8")) > _MAX_MEMORY_FIELD_BYTES:
            raise HTTPException(status_code=413, detail="Decisions field exceeds size limit")
        write_decisions(resolved, body.decisions)
    if body.wisdom is not None:
        if len(body.wisdom.encode("utf-8")) > _MAX_MEMORY_FIELD_BYTES:
            raise HTTPException(status_code=413, detail="Wisdom field exceeds size limit")
        write_wisdom(resolved, body.wisdom)
    text = read_memory_text(resolved)
    return MemoryResponse(memory=text, has_memory=bool(text))


@router.post("/repos/{repo_path:path}/memory/compact", response_model=CompactResponse)
async def compact_memory(
    repo_path: str,
    compacter: FromDishka[MemoryCompacter],
) -> CompactResponse:
    """Trigger compaction of old decisions into archive."""
    resolved = _validate_repo(repo_path)
    compacted = await compact_decisions(resolved, compacter)
    return CompactResponse(compacted=compacted)
