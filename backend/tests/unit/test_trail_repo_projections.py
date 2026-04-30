"""Tests for TrailNodeRepository projection methods used by downstream consumers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, TrailNodeRow
from backend.persistence.trail_repo import TrailNodeRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def repo(session_factory):
    return TrailNodeRepository(session_factory)


def _node(
    *,
    job_id: str = "job-1",
    seq: int,
    kind: str = "modify",
    agent_message: str | None = None,
    intent: str | None = None,
    files: list[str] | None = None,
) -> TrailNodeRow:
    return TrailNodeRow(
        id=f"node-{seq}",
        job_id=job_id,
        seq=seq,
        anchor_seq=seq,
        kind=kind,
        deterministic_kind=kind,
        phase="execution",
        timestamp=datetime(2026, 1, 1, 0, 0, seq, tzinfo=UTC),
        enrichment="pending",
        agent_message=agent_message,
        intent=intent,
        files=json.dumps(files, ensure_ascii=False) if files else None,
    )


# ---------------------------------------------------------------------------
# get_transcript_nodes
# ---------------------------------------------------------------------------


class TestGetTranscriptNodes:
    @pytest.mark.asyncio
    async def test_returns_nodes_with_agent_message(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=1, kind="modify", agent_message="I fixed it"),
            _node(seq=2, kind="shell", agent_message=None),  # no message
            _node(seq=3, kind="explore", agent_message="Reading file"),
        ])

        nodes = await repo.get_transcript_nodes("job-1")

        assert len(nodes) == 2
        assert nodes[0].agent_message == "I fixed it"
        assert nodes[1].agent_message == "Reading file"

    @pytest.mark.asyncio
    async def test_includes_request_nodes_with_intent(self, repo: TrailNodeRepository) -> None:
        """Request nodes (operator interactions) are included via intent field."""
        await repo.create_many([
            _node(seq=1, kind="modify", agent_message="Done"),
            _node(seq=2, kind="request", intent="Please fix the tests"),
            _node(seq=3, kind="request", intent=None),  # no intent — excluded
        ])

        nodes = await repo.get_transcript_nodes("job-1")

        assert len(nodes) == 2
        assert nodes[0].kind == "modify"
        assert nodes[1].kind == "request"
        assert nodes[1].intent == "Please fix the tests"

    @pytest.mark.asyncio
    async def test_respects_limit(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=i, kind="modify", agent_message=f"msg-{i}")
            for i in range(1, 6)
        ])

        nodes = await repo.get_transcript_nodes("job-1", limit=3)
        assert len(nodes) == 3

    @pytest.mark.asyncio
    async def test_empty_job(self, repo: TrailNodeRepository) -> None:
        nodes = await repo.get_transcript_nodes("nonexistent")
        assert nodes == []

    @pytest.mark.asyncio
    async def test_ordered_by_anchor_seq_then_seq(self, repo: TrailNodeRepository) -> None:
        # Create nodes with non-sequential anchor_seq
        n1 = _node(seq=3, kind="modify", agent_message="third")
        n1.anchor_seq = 1
        n2 = _node(seq=1, kind="modify", agent_message="first")
        n2.anchor_seq = 2
        await repo.create_many([n1, n2])

        nodes = await repo.get_transcript_nodes("job-1")
        assert nodes[0].agent_message == "third"  # anchor_seq=1 first
        assert nodes[1].agent_message == "first"  # anchor_seq=2 second


# ---------------------------------------------------------------------------
# get_file_changes_by_step
# ---------------------------------------------------------------------------


class TestGetFileChangesByStep:
    @pytest.mark.asyncio
    async def test_returns_nodes_with_files(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=1, kind="modify", files=["src/a.py"]),
            _node(seq=2, kind="shell", files=None),  # no files
            _node(seq=3, kind="explore", files=["src/b.py"]),
        ])

        nodes = await repo.get_file_changes_by_step("job-1")

        assert len(nodes) == 2
        assert json.loads(nodes[0].files) == ["src/a.py"]
        assert json.loads(nodes[1].files) == ["src/b.py"]

    @pytest.mark.asyncio
    async def test_excludes_non_step_kinds(self, repo: TrailNodeRepository) -> None:
        """Only modify/shell/explore kinds are returned."""
        await repo.create_many([
            _node(seq=1, kind="modify", files=["a.py"]),
            _node(seq=2, kind="goal", files=["b.py"]),  # goal — excluded
            _node(seq=3, kind="request", files=["c.py"]),  # request — excluded
            _node(seq=4, kind="summarize", files=["d.py"]),  # summarize — excluded
        ])

        nodes = await repo.get_file_changes_by_step("job-1")
        assert len(nodes) == 1
        assert nodes[0].id == "node-1"

    @pytest.mark.asyncio
    async def test_empty_job(self, repo: TrailNodeRepository) -> None:
        nodes = await repo.get_file_changes_by_step("nonexistent")
        assert nodes == []


# ---------------------------------------------------------------------------
# get_latest_step_boundary
# ---------------------------------------------------------------------------


class TestGetLatestStepBoundary:
    @pytest.mark.asyncio
    async def test_returns_most_recent(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=1, kind="modify", files=["a.py"]),
            _node(seq=2, kind="modify", files=["b.py"]),
            _node(seq=3, kind="shell", files=["c.py"]),
        ])

        node = await repo.get_latest_step_boundary("job-1")

        assert node is not None
        assert node.seq == 3

    @pytest.mark.asyncio
    async def test_skips_nodes_without_files(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=1, kind="modify", files=["a.py"]),
            _node(seq=2, kind="modify", files=None),  # no files
        ])

        node = await repo.get_latest_step_boundary("job-1")
        assert node is not None
        assert node.seq == 1

    @pytest.mark.asyncio
    async def test_empty_job(self, repo: TrailNodeRepository) -> None:
        node = await repo.get_latest_step_boundary("nonexistent")
        assert node is None


# ---------------------------------------------------------------------------
# get_all_changed_files
# ---------------------------------------------------------------------------


class TestGetAllChangedFiles:
    @pytest.mark.asyncio
    async def test_unions_files_across_steps(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=1, kind="modify", files=["src/a.py", "src/b.py"]),
            _node(seq=2, kind="shell", files=["src/b.py", "src/c.py"]),
        ])

        result = await repo.get_all_changed_files("job-1")

        assert result == ["src/a.py", "src/b.py", "src/c.py"]

    @pytest.mark.asyncio
    async def test_handles_dict_format(self, repo: TrailNodeRepository) -> None:
        """Handles both string and dict file formats."""
        await repo.create_many([
            _node(seq=1, kind="modify", files=None),
        ])
        # Manually set files to dict format
        async with repo._session_factory() as session:
            from sqlalchemy import update
            await session.execute(
                update(TrailNodeRow)
                .where(TrailNodeRow.id == "node-1")
                .values(files=json.dumps([{"path": "x.py"}, {"path": "y.py"}]))
            )
            await session.commit()

        result = await repo.get_all_changed_files("job-1")
        assert result == ["x.py", "y.py"]

    @pytest.mark.asyncio
    async def test_empty_job(self, repo: TrailNodeRepository) -> None:
        result = await repo.get_all_changed_files("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_output(self, repo: TrailNodeRepository) -> None:
        await repo.create_many([
            _node(seq=1, kind="modify", files=["z.py", "a.py", "m.py"]),
        ])

        result = await repo.get_all_changed_files("job-1")
        assert result == ["a.py", "m.py", "z.py"]
