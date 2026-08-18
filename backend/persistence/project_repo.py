"""Project persistence — the sole store for repo-path membership (AD-5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from backend.models.db import JobRow, ProjectRow, TaskLinkRow, TrackerLinkRow
from backend.models.domain import Project, ProjectMembershipImpact
from backend.persistence.repository import BaseRepository

if TYPE_CHECKING:
    import builtins


class RepoJobCounts:
    """Job status bucket counts + last activity timestamp for one repo path.

    Bucket boundaries mirror the frontend classifier
    (``frontend/src/store/selectors.ts``): active = preparing/queued/running;
    awaiting = waiting_for_approval/review/unresolved completed; failed = failed.
    """

    __slots__ = ("active", "awaiting", "failed", "last_activity")

    def __init__(self) -> None:
        self.active = 0
        self.awaiting = 0
        self.failed = 0
        self.last_activity: datetime | None = None


class ProjectRepository(BaseRepository):
    """Database access for Project records."""

    @staticmethod
    def _to_domain(row: ProjectRow) -> Project:
        return Project(
            id=row.id,
            name=row.name,
            repo_paths=json.loads(row.repo_paths) if row.repo_paths else [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create(self, project_id: str, name: str, repo_paths: builtins.list[str]) -> Project:
        """Insert a new Project row."""
        now = datetime.now(UTC)
        row = ProjectRow(
            id=project_id,
            name=name,
            repo_paths=json.dumps(repo_paths),
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    async def get(self, project_id: str) -> Project | None:
        """Get a single Project by ID."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list(self) -> builtins.list[Project]:
        """List all Projects, ordered by creation time."""
        stmt = select(ProjectRow).order_by(ProjectRow.created_at)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def find_by_repo_path(self, repo_path: str) -> Project | None:
        """Return the Project that owns ``repo_path``, if any."""
        for project in await self.list():
            if repo_path in project.repo_paths:
                return project
        return None

    async def list_all_repo_paths(self, exclude_project_id: str | None = None) -> dict[str, str]:
        """Return a mapping of ``repo_path -> project_id`` across all Projects.

        Used by the service layer to enforce NFR5 (a repo belongs to at most
        one explicit Project). ``exclude_project_id`` omits a given Project's
        own rows, so updating a Project's own repo membership doesn't
        conflict with itself.
        """
        stmt = select(ProjectRow)
        if exclude_project_id is not None:
            stmt = stmt.where(ProjectRow.id != exclude_project_id)
        result = await self._session.execute(stmt)
        mapping: dict[str, str] = {}
        for row in result.scalars().all():
            for path in json.loads(row.repo_paths) if row.repo_paths else []:
                mapping[path] = row.id
        return mapping

    async def update(
        self,
        project_id: str,
        name: str | None = None,
        repo_paths: builtins.list[str] | None = None,
    ) -> Project | None:
        """Update a Project's name and/or repo membership. Returns None if not found."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if name is not None:
            row.name = name
        if repo_paths is not None:
            row.repo_paths = json.dumps(repo_paths)
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_domain(row)

    async def membership_impact(
        self,
        project_id: str,
        removed_repo_paths: builtins.list[str],
    ) -> ProjectMembershipImpact:
        """Count work that would be affected by removing member repositories."""
        if not removed_repo_paths:
            return ProjectMembershipImpact()

        active_states = ("preparing", "queued", "running", "waiting_for_approval", "review")
        active_jobs = await self._session.scalar(
            select(func.count())
            .select_from(JobRow)
            .where(JobRow.repo.in_(removed_repo_paths), JobRow.state.in_(active_states))
        )
        all_jobs = await self._session.scalar(
            select(func.count()).select_from(JobRow).where(JobRow.repo.in_(removed_repo_paths))
        )
        task_links = await self._session.scalar(
            select(func.count())
            .select_from(TaskLinkRow)
            .where(TaskLinkRow.project_id == project_id, TaskLinkRow.repo_path.in_(removed_repo_paths))
        )
        tracker_links = await self._session.scalar(
            select(func.count()).select_from(TrackerLinkRow).where(TrackerLinkRow.project_id == project_id)
        )
        active_count = int(active_jobs or 0)
        return ProjectMembershipImpact(
            active_job_count=active_count,
            historical_job_count=max(0, int(all_jobs or 0) - active_count),
            task_link_count=int(task_links or 0),
            tracker_link_count=int(tracker_links or 0),
        )

    async def job_counts_by_repo(self, repo_paths: builtins.list[str]) -> dict[str, RepoJobCounts]:
        """Bucket job status counts + last-activity per repo path, in a single query.

        Used by ``ProjectService.summary_all`` (Story 2.2 / CAP-2) to build the
        batch Projects Overview summary without N sequential per-Project
        queries. Repos with no jobs simply have no entry in the returned dict.
        """
        if not repo_paths:
            return {}

        stmt = select(JobRow.repo, JobRow.state, JobRow.resolution, JobRow.updated_at).where(
            JobRow.repo.in_(repo_paths)
        )
        result = await self._session.execute(stmt)

        counts: dict[str, RepoJobCounts] = {}
        for repo, state, resolution, updated_at in result.all():
            bucket = counts.setdefault(repo, RepoJobCounts())
            if state in ("preparing", "queued", "running"):
                bucket.active += 1
            elif state in ("waiting_for_approval", "review") or (
                state == "completed" and (not resolution or resolution == "unresolved")
            ):
                bucket.awaiting += 1
            elif state == "failed":
                bucket.failed += 1
            if bucket.last_activity is None or updated_at > bucket.last_activity:
                bucket.last_activity = updated_at
        return counts
