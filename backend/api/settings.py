"""Settings management endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import (
    DEFAULT_SELF_REVIEW_PROMPT,
    DEFAULT_VERIFY_PROMPT,
    CPLConfig,
    load_config,
    register_repo,
    save_config,
    unregister_repo,
)
from backend.models.api_schemas import (
    BrowseDirectoryResponse,
    BrowseEntry,
    CleanupWorktreesResponse,
    CreateRepoRequest,
    CreateRepoResponse,
    PlatformStatusListResponse,
    PlatformStatusResponse,
    RegisterRepoRequest,
    RegisterRepoResponse,
    RepoCostSummary,
    RepoDetailResponse,
    RepoHealthResponse,
    RepoJobSummary,
    RepoListResponse,
    RepoMemoryPreview,
    RepoSummaryResponse,
    SDKInfoResponse,
    SDKListResponse,
    SettingsResponse,
    UpdateSettingsRequest,
)
from backend.models.db import JobRow
from backend.services.coderecon_service import CodeReconService
from backend.services.git_service import GitError, GitService
from backend.services.platform_adapter import PlatformRegistry, detect_platform

router = APIRouter(tags=["settings"], route_class=DishkaRoute)


def _config_to_response(config: CPLConfig) -> SettingsResponse:
    return SettingsResponse(
        max_concurrent_jobs=config.runtime.max_concurrent_jobs,
        auto_push=config.completion.auto_push,
        cleanup_worktree=config.completion.cleanup_worktree,
        delete_branch_after_merge=config.completion.delete_branch_after_merge,
        artifact_retention_days=config.retention.artifact_retention_days,
        max_artifact_size_mb=config.retention.max_artifact_size_mb,
        auto_archive_days=config.retention.auto_archive_days,
        verify=config.verification.verify,
        self_review=config.verification.self_review,
        max_turns=config.verification.max_turns,
        verify_prompt=config.verification.verify_prompt or DEFAULT_VERIFY_PROMPT,
        self_review_prompt=config.verification.self_review_prompt or DEFAULT_SELF_REVIEW_PROMPT,
    )


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    config: FromDishka[CPLConfig],
) -> SettingsResponse:
    """Get current settings as structured data."""
    return _config_to_response(config)


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    body: UpdateSettingsRequest,
) -> SettingsResponse:
    """Update settings. Only provided fields are changed."""
    config = load_config()
    updates = body.model_dump(exclude_none=True)

    # Declarative mapping: request field → (config section, config attribute)
    _FIELD_MAP: dict[str, tuple[str, str]] = {  # noqa: N806
        "max_concurrent_jobs": ("runtime", "max_concurrent_jobs"),
        "auto_push": ("completion", "auto_push"),
        "cleanup_worktree": ("completion", "cleanup_worktree"),
        "delete_branch_after_merge": ("completion", "delete_branch_after_merge"),
        "artifact_retention_days": ("retention", "artifact_retention_days"),
        "max_artifact_size_mb": ("retention", "max_artifact_size_mb"),
        "auto_archive_days": ("retention", "auto_archive_days"),
        "verify": ("verification", "verify"),
        "self_review": ("verification", "self_review"),
        "max_turns": ("verification", "max_turns"),
        "verify_prompt": ("verification", "verify_prompt"),
        "self_review_prompt": ("verification", "self_review_prompt"),
    }

    for field, (section, attr) in _FIELD_MAP.items():
        if field in updates:
            setattr(getattr(config, section), attr, updates[field])

    save_config(config)
    return _config_to_response(config)


@router.get("/settings/repos", response_model=RepoListResponse)
def list_repos(
    config: FromDishka[CPLConfig],
) -> RepoListResponse:
    """List registered repository paths."""
    return RepoListResponse(items=config.repos)


@router.get("/settings/repos/{repo_path:path}/health", response_model=RepoHealthResponse)
async def get_repo_health(
    repo_path: str,
    config: FromDishka[CPLConfig],
    coderecon: FromDishka[CodeReconService],
) -> RepoHealthResponse:
    """Structural health status for a repository (§6.2)."""
    log = structlog.get_logger()
    resolved = str(Path(repo_path).expanduser().resolve())
    if resolved not in config.repos:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_path}' is not registered.")

    if not coderecon.available:
        return RepoHealthResponse(repo=resolved)

    try:
        repo_name = await asyncio.wait_for(coderecon.ensure_repo_indexed(resolved), timeout=30.0)
    except TimeoutError:
        log.warning("repo_health.index_timeout", repo=resolved)
        return RepoHealthResponse(repo=resolved, index_status="timeout")
    except Exception:
        log.warning("repo_health.index_failed", repo=resolved, exc_info=True)
        return RepoHealthResponse(repo=resolved, index_status="error")

    # Gather health metrics
    symbol_count = 0
    file_count = 0
    last_sha = None
    community_count = 0
    cycle_count = 0

    try:
        status = await coderecon.repo_status(repo_name)
        if status:
            symbol_count = status.get("symbol_count", 0)
            file_count = status.get("file_count", 0)
            last_sha = status.get("last_indexed_sha")
    except Exception:
        log.debug("repo_health.status_failed", repo=resolved, exc_info=True)

    try:
        communities = await coderecon.graph_communities(repo_name, worktree="main")
        community_count = len(communities.communities) if communities.communities else 0
    except Exception:
        log.debug("repo_health.communities_failed", repo=resolved, exc_info=True)

    try:
        cycles = await coderecon.graph_cycles(repo_name, worktree="main")
        cycle_count = len(cycles.cycles) if cycles.cycles else 0
    except Exception:
        log.debug("repo_health.cycles_failed", repo=resolved, exc_info=True)

    return RepoHealthResponse(
        repo=resolved,
        available=True,
        index_status="ready",
        symbol_count=symbol_count,
        file_count=file_count,
        last_indexed_sha=last_sha,
        community_count=community_count,
        cycle_count=cycle_count,
    )


@router.get("/settings/repos/{repo_path:path}/summary", response_model=RepoSummaryResponse)
async def get_repo_summary(
    repo_path: str,
    config: FromDishka[CPLConfig],
    git_service: FromDishka[GitService],
    coderecon: FromDishka[CodeReconService],
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> RepoSummaryResponse:
    """Aggregated dashboard overview for a single repository."""
    from backend.services.memory.workspace import read_memory_detail

    log = structlog.get_logger()

    resolved = str(Path(repo_path).expanduser().resolve())
    if resolved not in config.repos:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_path}' is not registered.")

    # --- Git info ---
    origin_url: str | None = None
    base_branch: str | None = None
    current_branch: str | None = None
    with contextlib.suppress(GitError):
        raw_url = await git_service.get_origin_url(resolved)
        if raw_url:
            origin_url = GitService.strip_url_credentials(raw_url)
    with contextlib.suppress(GitError):
        base_branch = await git_service.get_default_branch(resolved)
    with contextlib.suppress(GitError):
        current_branch = await git_service.get_current_branch(cwd=resolved)

    platform = detect_platform(origin_url)

    # --- Recent jobs (from DB) ---
    recent_jobs: list[RepoJobSummary] = []
    active_job_count = 0
    cost_summary = RepoCostSummary()
    try:
        async with sf() as session:
            rows = (
                (
                    await session.execute(
                        select(JobRow).where(JobRow.repo == resolved).order_by(JobRow.created_at.desc()).limit(5)
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                recent_jobs.append(
                    RepoJobSummary(
                        id=r.id,
                        title=r.title,
                        state=r.state,
                        created_at=r.created_at,
                        completed_at=r.completed_at,
                        total_cost_usd=None,  # cost lives in spans, not job row
                        model=r.model,
                    )
                )
            active_count_result = await session.execute(
                select(JobRow.id)
                .where(JobRow.repo == resolved)
                .where(JobRow.state.in_(("running", "preparing", "paused")))
            )
            active_job_count = len(active_count_result.scalars().all())
    except Exception:
        log.warning("repo_summary.jobs_query_failed", repo=resolved, exc_info=True)

    # --- Memory preview (filesystem, no DB needed) ---
    memory_preview = RepoMemoryPreview()
    try:
        detail = read_memory_detail(resolved)
        decisions = detail.get("decisions", "")
        wisdom_text = detail.get("wisdom", "")
        archive_text = detail.get("archive", "")
        memory_preview = RepoMemoryPreview(
            has_memory=bool(decisions or wisdom_text),
            decisions_chars=len(decisions),
            wisdom_chars=len(wisdom_text),
            archive_chars=len(archive_text),
            decisions_preview=decisions[:200],
            wisdom_preview=wisdom_text[:200],
        )
    except Exception:
        log.warning("repo_summary.memory_read_failed", repo=resolved, exc_info=True)

    # --- Health (best-effort) ---
    health: RepoHealthResponse | None = None
    if coderecon.available:
        try:
            repo_name = await asyncio.wait_for(coderecon.ensure_repo_indexed(resolved), timeout=30.0)
            h_symbol_count = 0
            h_file_count = 0
            h_last_sha = None
            h_community_count = 0
            h_cycle_count = 0

            try:
                status = await coderecon.repo_status(repo_name)
                if status:
                    h_symbol_count = status.get("symbol_count", 0)
                    h_file_count = status.get("file_count", 0)
                    h_last_sha = status.get("last_indexed_sha")
            except Exception:
                log.debug("repo_summary.health_status_failed", repo=resolved, exc_info=True)

            try:
                communities = await coderecon.graph_communities(repo_name, worktree="main")
                h_community_count = len(communities.communities) if communities.communities else 0
            except Exception:
                log.debug("repo_summary.communities_failed", repo=resolved, exc_info=True)

            try:
                cycles = await coderecon.graph_cycles(repo_name, worktree="main")
                h_cycle_count = len(cycles.cycles) if cycles.cycles else 0
            except Exception:
                log.debug("repo_summary.cycles_failed", repo=resolved, exc_info=True)

            health = RepoHealthResponse(
                repo=resolved,
                available=True,
                index_status="ready",
                symbol_count=h_symbol_count,
                file_count=h_file_count,
                last_indexed_sha=h_last_sha,
                community_count=h_community_count,
                cycle_count=h_cycle_count,
            )
        except TimeoutError:
            log.warning("repo_summary.index_timeout", repo=resolved)
            health = RepoHealthResponse(repo=resolved, index_status="timeout")
        except Exception:
            log.warning("repo_summary.index_failed", repo=resolved, exc_info=True)
            health = RepoHealthResponse(repo=resolved, index_status="error")

    return RepoSummaryResponse(
        path=resolved,
        origin_url=origin_url,
        base_branch=base_branch,
        current_branch=current_branch,
        platform=platform,
        recent_jobs=recent_jobs,
        active_job_count=active_job_count,
        cost=cost_summary,
        memory=memory_preview,
        health=health,
    )


# NOTE: This catch-all route MUST be registered AFTER more specific
# /health and /summary routes, because {repo_path:path} is greedy
# and would otherwise consume the suffix as part of repo_path.
@router.get("/settings/repos/{repo_path:path}", response_model=RepoDetailResponse)
async def get_repo_detail(
    repo_path: str,
    config: FromDishka[CPLConfig],
    git_service: FromDishka[GitService],
) -> RepoDetailResponse:
    """Get detailed config for a single registered repository."""
    resolved = str(Path(repo_path).expanduser().resolve())
    if resolved not in config.repos:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_path}' is not registered.")

    origin_url: str | None = None
    base_branch: str | None = None
    current_branch: str | None = None
    with contextlib.suppress(GitError):
        raw_url = await git_service.get_origin_url(resolved)
        if raw_url:
            origin_url = GitService.strip_url_credentials(raw_url)
    with contextlib.suppress(GitError):
        base_branch = await git_service.get_default_branch(resolved)
    with contextlib.suppress(GitError):
        current_branch = await git_service.get_current_branch(cwd=resolved)

    return RepoDetailResponse(
        path=resolved,
        origin_url=origin_url,
        base_branch=base_branch,
        current_branch=current_branch,
        platform=detect_platform(origin_url),
    )


@router.post("/settings/repos", response_model=RegisterRepoResponse, status_code=201)
async def register_repo_endpoint(
    body: RegisterRepoRequest,
    config: FromDishka[CPLConfig],
    git_service: FromDishka[GitService],
    coderecon: FromDishka[CodeReconService],
) -> RegisterRepoResponse:
    """Register a repository (local path or remote URL)."""
    source = body.source

    if GitService.is_remote_url(source):
        if not body.clone_to:
            raise HTTPException(
                status_code=400,
                detail="clone_to path is required when registering a remote URL",
            )
        clone_dir = str(Path(body.clone_to).expanduser().resolve())
        if Path(clone_dir).exists():
            raise HTTPException(
                status_code=409,
                detail=f"Clone directory already exists: {clone_dir}",
            )
        try:
            cloned_path = await git_service.clone_repo(source, clone_dir)
        except GitError as exc:
            structlog.get_logger().warning("clone_failed", source=source, exc_info=exc)
            raise HTTPException(status_code=400, detail="Clone failed") from exc
        register_repo(config, cloned_path)
        if coderecon.available:
            asyncio.create_task(coderecon.ensure_repo_indexed(cloned_path))
        return RegisterRepoResponse(path=cloned_path, source=source, cloned=True)

    # Local path
    resolved = str(Path(source).expanduser().resolve())
    is_valid = await git_service.validate_repo(resolved)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Not a valid git repository: {source}",
        )
    register_repo(config, resolved)
    if coderecon.available:
        asyncio.create_task(coderecon.ensure_repo_indexed(resolved))
    return RegisterRepoResponse(path=resolved, source=source, cloned=False)


@router.post("/settings/repos/create", response_model=CreateRepoResponse, status_code=201)
async def create_repo_endpoint(
    body: CreateRepoRequest,
    config: FromDishka[CPLConfig],
    git_service: FromDishka[GitService],
    coderecon: FromDishka[CodeReconService],
) -> CreateRepoResponse:
    """Create a new git repository and register it."""
    resolved = Path(body.path).expanduser().resolve()
    if body.name:
        resolved = resolved / body.name

    if (resolved / ".git").is_dir():
        raise HTTPException(status_code=409, detail=f"A git repository already exists at {resolved}")

    try:
        repo_path = await git_service.init_repo(str(resolved))
    except GitError as exc:
        structlog.get_logger().warning("repo_create_failed", path=str(resolved), exc_info=exc)
        raise HTTPException(status_code=400, detail="Failed to create repository") from exc

    register_repo(config, repo_path)
    if coderecon.available:
        asyncio.create_task(coderecon.ensure_repo_indexed(repo_path))
    return CreateRepoResponse(path=repo_path, name=resolved.name)


@router.delete("/settings/repos/{repo_path:path}", status_code=204)
def unregister_repo_endpoint(
    repo_path: str,
    config: FromDishka[CPLConfig],
) -> None:
    """Remove a repository from the allowlist."""
    try:
        unregister_repo(config, repo_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Repository not found in allowlist") from exc


@router.post("/settings/cleanup-worktrees", response_model=CleanupWorktreesResponse)
async def cleanup_worktrees(
    config: FromDishka[CPLConfig],
    git_service: FromDishka[GitService],
) -> CleanupWorktreesResponse:
    """Clean up completed job worktrees for all registered repos."""
    total = 0
    for repo in config.repos:
        try:
            count = await git_service.cleanup_worktrees(repo)
            total += count
        except GitError:
            structlog.get_logger().warning("cleanup_worktrees_failed", repo=repo)
    return CleanupWorktreesResponse(removed=total)


@router.get("/settings/browse", response_model=BrowseDirectoryResponse)
def browse_directories(
    path: str = "~",
) -> BrowseDirectoryResponse:
    """List directories at a given path for the repo browser.

    Returns subdirectories and indicates which are git repos.
    """
    try:
        base = Path(path).expanduser().resolve()
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Invalid path") from exc

    if not base.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    # Security: don't traverse above user's home
    home = Path.home().resolve()
    if not base.is_relative_to(home):
        raise HTTPException(status_code=403, detail="Access denied")

    entries: list[BrowseEntry] = []
    try:
        # Use os.scandir for performance: DirEntry.is_dir() uses cached
        # d_type from readdir instead of issuing a separate stat() per entry.
        with os.scandir(base) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                except OSError:
                    continue
                is_git = os.path.isdir(os.path.join(entry.path, ".git"))
                entries.append(
                    BrowseEntry(
                        name=entry.name,
                        path=entry.path,
                        is_git_repo=is_git,
                    )
                )
        entries.sort(key=lambda e: e.name.lower())
    except PermissionError:
        structlog.get_logger(__name__).warning(
            "browse_directory_permission_denied",
            path=str(base),
            exc_info=True,
        )

    return BrowseDirectoryResponse(
        current=str(base),
        parent=str(base.parent) if base != home else None,
        items=entries,
    )


# --- Platform status ---


@router.get("/platforms/status", response_model=PlatformStatusListResponse)
async def get_platform_status(
    platform_registry: FromDishka[PlatformRegistry],
) -> PlatformStatusListResponse:
    """Check auth status for all detected git hosting platforms."""
    statuses = await platform_registry.check_all()
    return PlatformStatusListResponse(
        items=[
            PlatformStatusResponse(
                platform=s.platform,
                authenticated=s.authenticated,
                user=s.user,
                error=s.error,
            )
            for s in statuses
        ]
    )


# --- SDK status ---


_SDK_DISPLAY_NAMES: dict[str, str] = {
    "copilot": "GitHub Copilot",
    "claude": "Claude Code",
}


@router.get("/sdks", response_model=SDKListResponse)
async def list_sdks() -> SDKListResponse:
    """List available agent SDKs, installation status, and auth status."""
    import asyncio

    from backend.models.domain import AgentSDK
    from backend.services.setup.checks import check_agent_auth, check_agent_cli

    config = load_config()
    default_sdk = config.runtime.default_sdk

    items: list[SDKInfoResponse] = []
    for sdk in AgentSDK:
        cli = check_agent_cli(sdk.value)
        if not cli.ready:
            items.append(
                SDKInfoResponse(
                    id=sdk.value,
                    name=_SDK_DISPLAY_NAMES.get(sdk.value, sdk.value),
                    enabled=False,
                    status="not_installed",
                    authenticated=None,
                    hint=cli.hint,
                )
            )
            continue

        # Run auth check in a thread to avoid blocking the event loop on subprocess.
        auth = await asyncio.to_thread(check_agent_auth, sdk.value)

        if auth.authenticated is True:
            status = "ready"
            enabled = True
            hint = ""
        elif auth.authenticated is False:
            status = "not_configured"
            enabled = False
            hint = auth.hint
        else:
            # Unknown auth — allow selection but surface a hint
            status = "ready"
            enabled = True
            hint = auth.hint or "Auth status could not be verified"

        items.append(
            SDKInfoResponse(
                id=sdk.value,
                name=_SDK_DISPLAY_NAMES.get(sdk.value, sdk.value),
                enabled=enabled,
                status=status,
                authenticated=auth.authenticated,
                hint=hint,
            )
        )

    return SDKListResponse(default=default_sdk, sdks=items)
