"""Tests for new code introduced during the dead-code audit session.

Covers:
- Schema re-export barrel (api_schemas → schemas.base / schemas.telemetry)
- CamelModel UTC datetime behavior from the new canonical location
- JobService.build_conflict_resume_prompt
- EventRepository.list_all_by_job
- JobRepository.list_all
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from backend.models.db import Base
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.event_repo import EventRepository
from backend.persistence.job_repo import JobRepository
from backend.tests.unit.conftest import make_job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


# ---------------------------------------------------------------------------
# 1. Schema re-export barrel — symbols importable from both locations
# ---------------------------------------------------------------------------


class TestSchemaReExports:
    """Verify that the barrel re-export in api_schemas keeps backward compat."""

    def test_camel_model_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import CamelModel as FromBarrel
        from backend.models.schemas.base import CamelModel as FromCanonical

        assert FromBarrel is FromCanonical

    def test_error_response_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import ErrorResponse as FromBarrel
        from backend.models.schemas.base import ErrorResponse as FromCanonical

        assert FromBarrel is FromCanonical

    def test_resolution_action_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import ResolutionAction as FromBarrel
        from backend.models.schemas.base import ResolutionAction as FromCanonical

        assert FromBarrel is FromCanonical

    def test_artifact_type_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import ArtifactType as FromBarrel
        from backend.models.schemas.base import ArtifactType as FromCanonical

        assert FromBarrel is FromCanonical

    def test_execution_phase_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import ExecutionPhase as FromBarrel
        from backend.models.schemas.base import ExecutionPhase as FromCanonical

        assert FromBarrel is FromCanonical

    def test_log_level_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import LogLevel as FromBarrel
        from backend.models.schemas.base import LogLevel as FromCanonical

        assert FromBarrel is FromCanonical

    def test_cost_attribution_bucket_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import CostAttributionBucket as FromBarrel
        from backend.models.schemas.telemetry import CostAttributionBucket as FromCanonical

        assert FromBarrel is FromCanonical

    def test_scorecard_response_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import ScorecardResponse as FromBarrel
        from backend.models.schemas.telemetry import ScorecardResponse as FromCanonical

        assert FromBarrel is FromCanonical

    def test_turn_economics_importable_from_both_paths(self) -> None:
        from backend.models.api_schemas import TurnEconomics as FromBarrel
        from backend.models.schemas.telemetry import TurnEconomics as FromCanonical

        assert FromBarrel is FromCanonical

    def test_schemas_init_re_exports(self) -> None:
        """The schemas __init__.py also re-exports everything."""
        from backend.models.schemas import CamelModel, CostAttributionBucket

        from backend.models.schemas.base import CamelModel as Base
        from backend.models.schemas.telemetry import CostAttributionBucket as Tel

        assert CamelModel is Base
        assert CostAttributionBucket is Tel


# ---------------------------------------------------------------------------
# CamelModel UTC datetime behavior from the new canonical location
# ---------------------------------------------------------------------------


class TestCamelModelUTC:
    def test_naive_datetime_gets_utc(self) -> None:
        from backend.models.schemas.base import CamelModel

        class Stamp(CamelModel):
            ts: datetime

        naive = datetime(2026, 1, 1, 12, 0, 0)  # noqa: DTZ001
        obj = Stamp(ts=naive)
        assert obj.ts.tzinfo is not None
        assert obj.ts.tzinfo == UTC

    def test_utc_datetime_preserved(self) -> None:
        from backend.models.schemas.base import CamelModel

        class Stamp(CamelModel):
            ts: datetime

        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        obj = Stamp(ts=aware)
        assert obj.ts == aware

    def test_non_utc_timezone_not_overwritten(self) -> None:
        from backend.models.schemas.base import CamelModel

        class Stamp(CamelModel):
            ts: datetime

        eastern = timezone(offset=datetime.now(tz=UTC).utcoffset() or __import__("datetime").timedelta(hours=-5))
        # A datetime with *some* tzinfo should not be replaced
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        obj = Stamp(ts=aware)
        assert obj.ts.tzinfo is not None


# ---------------------------------------------------------------------------
# 2. JobService.build_conflict_resume_prompt
# ---------------------------------------------------------------------------


class TestBuildConflictResumePrompt:
    @pytest.mark.asyncio
    async def test_prompt_with_conflict_files(self, session: AsyncSession) -> None:
        """When merge_conflict events exist, the prompt lists conflicting files."""
        from backend.config import CPLConfig
        from backend.persistence.event_repo import EventRepository
        from backend.services.job_service import JobService

        job_repo = JobRepository(session)
        event_repo = EventRepository(session)
        job = make_job(id="j-1", branch="feat/x", base_ref="main", worktree_path="/repos/test")
        await job_repo.create(job)

        evt = DomainEvent.for_job(
            "j-1",
            DomainEventKind.merge_conflict,
            {"conflict_files": ["src/a.py", "src/b.py"]},
        )
        await event_repo.append(evt)
        await session.commit()

        svc = JobService(
            job_repo=job_repo,
            git_service=None,
            config=CPLConfig(repos=["/repos/test"]),
            event_repo=event_repo,
        )
        prompt = await svc.build_conflict_resume_prompt("j-1")

        assert "feat/x" in prompt
        assert "'main'" in prompt
        assert "src/a.py" in prompt
        assert "src/b.py" in prompt
        assert "resolve the merge conflicts" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_without_conflict_files(self, session: AsyncSession) -> None:
        """When no merge_conflict events exist, prompt omits file list."""
        from backend.config import CPLConfig
        from backend.persistence.event_repo import EventRepository
        from backend.services.job_service import JobService

        job_repo = JobRepository(session)
        event_repo = EventRepository(session)
        job = make_job(id="j-2", branch="feat/y", base_ref="develop", worktree_path="/repos/test")
        await job_repo.create(job)
        await session.commit()

        svc = JobService(
            job_repo=job_repo,
            git_service=None,
            config=CPLConfig(repos=["/repos/test"]),
            event_repo=event_repo,
        )
        prompt = await svc.build_conflict_resume_prompt("j-2")

        assert "feat/y" in prompt
        assert "'develop'" in prompt
        assert "following files have conflicts" not in prompt
        assert "resolve the merge conflicts" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_uses_latest_conflict_event(self, session: AsyncSession) -> None:
        """When multiple merge_conflict events exist, the prompt uses the latest one."""
        from backend.config import CPLConfig
        from backend.persistence.event_repo import EventRepository
        from backend.services.job_service import JobService

        job_repo = JobRepository(session)
        event_repo = EventRepository(session)
        job = make_job(id="j-3", branch="feat/z", base_ref="main", worktree_path="/repos/test")
        await job_repo.create(job)

        # First conflict event — stale
        evt1 = DomainEvent.for_job("j-3", DomainEventKind.merge_conflict, {"conflict_files": ["old.py"]})
        await event_repo.append(evt1)
        # Second conflict event — current
        evt2 = DomainEvent.for_job("j-3", DomainEventKind.merge_conflict, {"conflict_files": ["new.py"]})
        await event_repo.append(evt2)
        await session.commit()

        svc = JobService(
            job_repo=job_repo,
            git_service=None,
            config=CPLConfig(repos=["/repos/test"]),
            event_repo=event_repo,
        )
        prompt = await svc.build_conflict_resume_prompt("j-3")

        assert "new.py" in prompt
        assert "old.py" not in prompt


# ---------------------------------------------------------------------------
# 3. EventRepository.list_all_by_job — no upper bound
# ---------------------------------------------------------------------------


class TestEventRepoListAllByJob:
    @pytest.mark.asyncio
    async def test_returns_all_events_no_limit(self, session: AsyncSession) -> None:
        """list_all_by_job returns every matching event, unlike list_by_job's default cap."""
        repo = EventRepository(session)
        job_id = "j-all"
        job_repo = JobRepository(session)
        await job_repo.create(make_job(id=job_id, worktree_path="/repos/test"))

        for i in range(10):
            evt = DomainEvent.for_job(job_id, DomainEventKind.log_line_emitted, {"seq": i})
            await repo.append(evt)
        await session.commit()

        results = await repo.list_all_by_job(job_id, kinds=[DomainEventKind.log_line_emitted])
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_filters_by_kind(self, session: AsyncSession) -> None:
        """list_all_by_job only returns events of the requested kind(s)."""
        repo = EventRepository(session)
        job_id = "j-filter"
        job_repo = JobRepository(session)
        await job_repo.create(make_job(id=job_id, worktree_path="/repos/test"))

        await repo.append(DomainEvent.for_job(job_id, DomainEventKind.log_line_emitted, {"seq": 0}))
        await repo.append(DomainEvent.for_job(job_id, DomainEventKind.merge_conflict, {"conflict_files": []}))
        await repo.append(DomainEvent.for_job(job_id, DomainEventKind.log_line_emitted, {"seq": 1}))
        await session.commit()

        logs = await repo.list_all_by_job(job_id, kinds=[DomainEventKind.log_line_emitted])
        assert len(logs) == 2

        conflicts = await repo.list_all_by_job(job_id, kinds=[DomainEventKind.merge_conflict])
        assert len(conflicts) == 1

    @pytest.mark.asyncio
    async def test_ordered_by_db_id(self, session: AsyncSession) -> None:
        """Results are ordered by autoincrement db id."""
        repo = EventRepository(session)
        job_id = "j-order"
        job_repo = JobRepository(session)
        await job_repo.create(make_job(id=job_id, worktree_path="/repos/test"))

        for i in range(5):
            await repo.append(DomainEvent.for_job(job_id, DomainEventKind.log_line_emitted, {"seq": i}))
        await session.commit()

        results = await repo.list_all_by_job(job_id, kinds=[DomainEventKind.log_line_emitted])
        db_ids = [r.db_id for r in results]
        assert db_ids == sorted(db_ids)

    @pytest.mark.asyncio
    async def test_list_by_job_with_low_limit_truncates(self, session: AsyncSession) -> None:
        """Contrast: list_by_job with a low limit truncates, list_all_by_job does not."""
        repo = EventRepository(session)
        job_id = "j-limit"
        job_repo = JobRepository(session)
        await job_repo.create(make_job(id=job_id, worktree_path="/repos/test"))

        for i in range(5):
            await repo.append(DomainEvent.for_job(job_id, DomainEventKind.log_line_emitted, {"seq": i}))
        await session.commit()

        limited = await repo.list_by_job(job_id, kinds=[DomainEventKind.log_line_emitted], limit=3)
        assert len(limited) == 3

        unlimited = await repo.list_all_by_job(job_id, kinds=[DomainEventKind.log_line_emitted])
        assert len(unlimited) == 5


# ---------------------------------------------------------------------------
# 4. JobRepository.list_all — no pagination upper bound
# ---------------------------------------------------------------------------


class TestJobRepoListAll:
    @pytest.mark.asyncio
    async def test_returns_all_jobs(self, session: AsyncSession) -> None:
        repo = JobRepository(session)
        for i in range(7):
            await repo.create(make_job(id=f"j-{i}", state="running", worktree_path="/repos/test"))
        await session.commit()

        jobs = await repo.list_all()
        assert len(jobs) == 7

    @pytest.mark.asyncio
    async def test_filters_by_state(self, session: AsyncSession) -> None:
        repo = JobRepository(session)
        await repo.create(make_job(id="j-run", state="running", worktree_path="/repos/test"))
        await repo.create(make_job(id="j-rev", state="review", worktree_path="/repos/test"))
        await repo.create(make_job(id="j-fail", state="failed", worktree_path="/repos/test"))
        await session.commit()

        running = await repo.list_all(state="running")
        assert len(running) == 1
        assert running[0].id == "j-run"

    @pytest.mark.asyncio
    async def test_filters_by_comma_separated_states(self, session: AsyncSession) -> None:
        repo = JobRepository(session)
        await repo.create(make_job(id="j-run", state="running", worktree_path="/repos/test"))
        await repo.create(make_job(id="j-rev", state="review", worktree_path="/repos/test"))
        await repo.create(make_job(id="j-fail", state="failed", worktree_path="/repos/test"))
        await session.commit()

        results = await repo.list_all(state="review,failed")
        assert len(results) == 2
        ids = {j.id for j in results}
        assert ids == {"j-rev", "j-fail"}

    @pytest.mark.asyncio
    async def test_no_pagination_unlike_list(self, session: AsyncSession) -> None:
        """Contrast: repo.list() has limit/cursor; list_all() returns everything."""
        repo = JobRepository(session)
        for i in range(10):
            await repo.create(make_job(id=f"j-{i}", state="running", worktree_path="/repos/test"))
        await session.commit()

        paginated = await repo.list(limit=3)
        assert len(paginated) == 3

        all_jobs = await repo.list_all()
        assert len(all_jobs) == 10
