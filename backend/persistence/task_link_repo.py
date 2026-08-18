"""TaskLink persistence — the sole store for ingested/assigned task nodes (Story 4.2, AD-9)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from backend.models.db import TaskLinkRow
from backend.models.domain import TaskLink, TaskLinkState
from backend.persistence.repository import BaseRepository


class TaskLinkRepository(BaseRepository):
    """Database access for TaskLink records.

    Upserts are matched by ``(project_id, repo_path, story_node_id)`` — never
    a bare ``story_node_id``, since that is only unique within one repo
    (AD-9). Manually-assigned TaskLinks (``story_node_id`` null,
    ``tracker_ticket_ref`` set — Story 4.3, not yet implemented) are always
    inserted fresh since there is no natural upsert key for them here.
    """

    @staticmethod
    def _to_domain(row: TaskLinkRow) -> TaskLink:
        return TaskLink(
            id=row.id,
            project_id=row.project_id,
            repo_path=row.repo_path,
            story_node_id=row.story_node_id,
            depends_on=json.loads(row.depends_on) if row.depends_on else [],
            chain_root_id=row.chain_root_id or row.id,
            state=TaskLinkState(row.state),
            job_id=row.job_id,
            tracker_link_id=row.tracker_link_id,
            tracker_ticket_ref=row.tracker_ticket_ref,
            prompt_override=row.prompt_override,
            epic_id=row.epic_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create_manual(
        self,
        *,
        project_id: str,
        repo_path: str,
        tracker_link_id: str | None = None,
        tracker_ticket_ref: str,
        prompt_override: str,
    ) -> TaskLink:
        """Insert a fresh manually-assigned TaskLink without story backing."""
        now = datetime.now(UTC)
        row = TaskLinkRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            repo_path=repo_path,
            story_node_id=None,
            depends_on="[]",
            chain_root_id="",
            state=TaskLinkState.ready,
            job_id=None,
            tracker_link_id=tracker_link_id,
            tracker_ticket_ref=tracker_ticket_ref,
            prompt_override=prompt_override,
            epic_id=None,
            created_at=now,
            updated_at=now,
        )
        row.chain_root_id = row.id
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    async def upsert_many(
        self,
        project_id: str,
        entries: list[dict[str, object]],
    ) -> list[TaskLink]:
        """Upsert a batch of ingested TaskLinks for a Project.

        Each entry must contain ``repo_path``, ``story_node_id``,
        ``depends_on`` (list[str]), and optionally ``epic_id``. Matched by
        ``(project_id, repo_path, story_node_id)``; re-ingestion never
        creates duplicate rows.
        """
        now = datetime.now(UTC)
        results: list[TaskLink] = []
        for entry in entries:
            repo_path = str(entry["repo_path"])
            raw_story_node_id = entry.get("story_node_id")
            story_node_id = str(raw_story_node_id) if raw_story_node_id is not None else None
            depends_on = entry.get("depends_on", [])
            raw_epic_id = entry.get("epic_id")
            epic_id = str(raw_epic_id) if raw_epic_id is not None else None

            stmt = select(TaskLinkRow).where(
                TaskLinkRow.project_id == project_id,
                TaskLinkRow.repo_path == repo_path,
                TaskLinkRow.story_node_id == story_node_id,
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                row = TaskLinkRow(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    repo_path=repo_path,
                    story_node_id=story_node_id,
                    depends_on=json.dumps(depends_on),
                    chain_root_id="",
                    state=TaskLinkState.ready if not depends_on else TaskLinkState.waiting,
                    epic_id=epic_id,
                    created_at=now,
                    updated_at=now,
                )
                row.chain_root_id = row.id
                self._session.add(row)
            else:
                row.depends_on = json.dumps(depends_on)
                row.epic_id = epic_id
                if row.job_id is None and row.state in {
                    TaskLinkState.waiting,
                    TaskLinkState.ready,
                }:
                    row.state = TaskLinkState.ready if not depends_on else TaskLinkState.waiting
                row.updated_at = now

            await self._session.flush()
            results.append(self._to_domain(row))

        # A chain is the connected component formed by dependency edges. Use
        # the earliest root node's persisted ID as a stable identity shared by
        # every branch and successor in that component.
        all_result = await self._session.execute(
            select(TaskLinkRow).where(TaskLinkRow.project_id == project_id)
        )
        all_rows = list(all_result.scalars().all())
        by_key = {
            f"{row.repo_path}::{row.story_node_id}": row
            for row in all_rows
            if row.story_node_id is not None
        }
        adjacency: dict[str, set[str]] = {row.id: set() for row in all_rows}
        by_id = {row.id: row for row in all_rows}
        for row in all_rows:
            for dep_key in json.loads(row.depends_on or "[]"):
                dependency = by_key.get(dep_key)
                if dependency is not None:
                    adjacency[row.id].add(dependency.id)
                    adjacency[dependency.id].add(row.id)

        visited: set[str] = set()
        for row in all_rows:
            if row.id in visited:
                continue
            stack = [row.id]
            component: list[TaskLinkRow] = []
            while stack:
                current_id = stack.pop()
                if current_id in visited:
                    continue
                visited.add(current_id)
                component.append(by_id[current_id])
                stack.extend(adjacency[current_id] - visited)
            component_ids = {item.id for item in component}
            roots = [
                item
                for item in component
                if not any(
                    (dependency := by_key.get(dep_key)) is not None
                    and dependency.id in component_ids
                    for dep_key in json.loads(item.depends_on or "[]")
                )
            ]
            chain_root_id = min(item.id for item in roots or component)
            for item in component:
                item.chain_root_id = chain_root_id
        await self._session.flush()

        refreshed_by_id = {row.id: self._to_domain(row) for row in all_rows}
        return [refreshed_by_id[result.id] for result in results]

    async def list_by_project(self, project_id: str) -> list[TaskLink]:
        """List every TaskLink for a Project, ordered by creation time."""
        stmt = select(TaskLinkRow).where(TaskLinkRow.project_id == project_id).order_by(TaskLinkRow.created_at)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get(self, task_link_id: str) -> TaskLink | None:
        """Retrieve a single TaskLink by ID, or ``None`` if not found (Story 5.3)."""
        stmt = select(TaskLinkRow).where(TaskLinkRow.id == task_link_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_job_id(self, job_id: str) -> TaskLink | None:
        """Find the TaskLink whose ``job_id`` matches, or ``None`` if none does."""
        stmt = select(TaskLinkRow).where(TaskLinkRow.job_id == job_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def set_job_id(self, task_link_id: str, job_id: str) -> TaskLink | None:
        """Set ``job_id`` on a TaskLink, guarded against double-spawn (Story 4.5, AC #3).

        Implemented as a conditional ``UPDATE ... WHERE job_id IS NULL`` (not a
        read-then-write) so it is safe even if two sibling dependencies complete
        near-simultaneously and both trigger a spawn attempt for the same
        dependent TaskLink — only the first write wins, the second observes
        zero rows affected and returns ``None``.
        """
        stmt = (
            update(TaskLinkRow)
            .where(TaskLinkRow.id == task_link_id, TaskLinkRow.job_id.is_(None))
            .values(job_id=job_id, updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if result.rowcount == 0:  # type: ignore[attr-defined]  # CursorResult.rowcount not in generic stub
            return None

        fetch_stmt = select(TaskLinkRow).where(TaskLinkRow.id == task_link_id)
        fetched = await self._session.execute(fetch_stmt)
        row = fetched.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def claim_ready(self, task_link_id: str) -> TaskLink | None:
        """Atomically claim a ready, unlinked TaskLink before creating its Job."""
        stmt = (
            update(TaskLinkRow)
            .where(
                TaskLinkRow.id == task_link_id,
                TaskLinkRow.state == TaskLinkState.ready,
                TaskLinkRow.job_id.is_(None),
            )
            .values(state=TaskLinkState.running, updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get(task_link_id)

    async def attach_claimed_job(
        self,
        task_link_id: str,
        job_id: str,
        *,
        state: TaskLinkState = TaskLinkState.running,
    ) -> TaskLink | None:
        """Attach a Job only to the caller's already-claimed TaskLink."""
        stmt = (
            update(TaskLinkRow)
            .where(
                TaskLinkRow.id == task_link_id,
                TaskLinkRow.state == TaskLinkState.running,
                TaskLinkRow.job_id.is_(None),
            )
            .values(job_id=job_id, state=state, updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get(task_link_id)

    async def set_state(self, task_link_id: str, state: TaskLinkState) -> TaskLink | None:
        """Persist one explicit TaskLink lifecycle transition."""
        stmt = (
            update(TaskLinkRow)
            .where(TaskLinkRow.id == task_link_id)
            .values(state=state, updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get(task_link_id)
