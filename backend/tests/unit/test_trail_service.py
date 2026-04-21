"""Tests for the agent audit trail service — deterministic skeleton + enrichment."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, TrailNodeRow
from backend.models.events import DomainEvent, DomainEventKind
from backend.persistence.trail_repo import TrailNodeRepository
from backend.services.event_bus import EventBus
from backend.services.trail_service import TrailService, _classify_step, _parse_enrichment_response


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
def trail_service(session_factory):
    event_bus = EventBus()
    return TrailService(session_factory=session_factory, event_bus=event_bus)


@pytest.fixture
def trail_repo(session_factory):
    return TrailNodeRepository(session_factory)


def _make_event(
    kind: DomainEventKind = DomainEventKind.job_state_changed,
    job_id: str = "job-1",
    payload: dict | None = None,
) -> DomainEvent:
    return DomainEvent(
        event_id=DomainEvent.make_event_id(),
        job_id=job_id,
        timestamp=datetime.now(UTC),
        kind=kind,
        payload=payload or {},
    )


def _job_started_event(job_id: str = "job-1") -> DomainEvent:
    """Create a job_state_changed event that triggers goal node creation."""
    return _make_event(
        DomainEventKind.job_state_changed,
        job_id=job_id,
        payload={"previous_state": "queued", "new_state": "running"},
    )


# ---------------------------------------------------------------------------
# classify_step unit tests
# ---------------------------------------------------------------------------


class TestClassifyStep:
    def test_files_written_returns_modify(self):
        assert _classify_step({"files_written": ["a.py"]}) == "modify"

    def test_sha_divergence_returns_modify(self):
        assert _classify_step({"start_sha": "aaa", "end_sha": "bbb"}) == "modify"

    def test_files_read_returns_explore(self):
        assert _classify_step({"files_read": ["a.py"]}) == "explore"

    def test_empty_returns_shell(self):
        assert _classify_step({}) == "shell"

    def test_same_sha_with_reads_returns_explore(self):
        assert _classify_step({"files_read": ["a.py"], "start_sha": "aaa", "end_sha": "aaa"}) == "explore"

    def test_writes_take_precedence_over_reads(self):
        assert _classify_step({"files_read": ["a.py"], "files_written": ["b.py"]}) == "modify"


# ---------------------------------------------------------------------------
# parse_enrichment_response tests
# ---------------------------------------------------------------------------


class TestParseEnrichmentResponse:
    def test_valid_json(self):
        data = _parse_enrichment_response('{"annotations": [], "semantic_nodes": []}')
        assert data == {"annotations": [], "semantic_nodes": []}

    def test_fenced_json(self):
        data = _parse_enrichment_response('```json\n{"annotations": []}\n```')
        assert data == {"annotations": []}

    def test_invalid_json_returns_none(self):
        assert _parse_enrichment_response("this is not json") is None

    def test_empty_returns_none(self):
        assert _parse_enrichment_response("") is None


# ---------------------------------------------------------------------------
# TrailService event handling (deterministic skeleton)
# ---------------------------------------------------------------------------


class TestTrailServiceGoalNode:
    async def test_job_started_creates_goal_node(self, trail_service, trail_repo):
        event = _job_started_event()
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        assert len(nodes) == 1
        assert nodes[0].kind == "goal"
        assert nodes[0].deterministic_kind == "goal"
        assert nodes[0].enrichment == "complete"
        assert nodes[0].seq == 1
        assert nodes[0].anchor_seq == 1
        assert nodes[0].parent_id is None

    async def test_goal_node_intent_empty_without_job_row(self, trail_service, trail_repo):
        """When the job row doesn't exist, intent falls back to empty."""
        event = _job_started_event()
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        # Intent is None or empty since we can't fetch the job row in test DB
        assert nodes[0].intent is None or nodes[0].intent == ""


class TestTrailServiceStepNodes:
    async def test_step_completed_modify(self, trail_service, trail_repo):
        # First create the job
        await trail_service.handle_event(_job_started_event())

        event = _make_event(
            DomainEventKind.step_completed,
            payload={
                "step_id": "step-1",
                "files_written": ["auth.py", "config.py"],
                "files_read": ["utils.py"],
                "start_sha": "aaa",
                "end_sha": "bbb",
            },
        )
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        assert len(nodes) == 2  # goal + modify
        step_node = nodes[1]
        assert step_node.kind == "modify"
        assert step_node.deterministic_kind == "modify"
        assert step_node.enrichment == "pending"
        assert step_node.seq == 2
        assert step_node.anchor_seq == 2
        assert step_node.parent_id == nodes[0].id  # parent is goal
        files = json.loads(step_node.files)
        assert "auth.py" in files
        assert "config.py" in files

    async def test_step_completed_explore(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())

        event = _make_event(
            DomainEventKind.step_completed,
            payload={"step_id": "step-1", "files_read": ["main.py"]},
        )
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        assert nodes[1].kind == "explore"

    async def test_step_completed_shell(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())

        event = _make_event(
            DomainEventKind.step_completed,
            payload={"step_id": "step-1"},
        )
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        assert nodes[1].kind == "shell"

    async def test_step_without_job_start_is_skipped(self, trail_service, trail_repo):
        """Steps for unknown jobs (started before trail service) are silently skipped."""
        event = _make_event(
            DomainEventKind.step_completed,
            job_id="unknown-job",
            payload={"step_id": "step-1"},
        )
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("unknown-job")
        assert len(nodes) == 0


class TestTrailServicePhaseNodes:
    async def test_phase_changed_creates_summarize(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())

        event = _make_event(
            DomainEventKind.execution_phase_changed,
            payload={"phase": "agent_reasoning"},
        )
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        assert len(nodes) == 2
        assert nodes[1].kind == "summarize"
        assert nodes[1].enrichment == "complete"
        assert nodes[1].intent == "Phase: agent_reasoning"
        assert nodes[1].anchor_seq == nodes[1].seq  # self-anchored


class TestTrailServiceTerminalNodes:
    async def test_job_completed_creates_terminal_summarize(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())

        event = _make_event(DomainEventKind.job_completed, payload={})
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        assert len(nodes) == 2
        terminal = nodes[1]
        assert terminal.kind == "summarize"
        assert terminal.phase == "terminal"
        assert terminal.intent == "Job completed"

    async def test_job_failed_creates_terminal_summarize(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())

        event = _make_event(DomainEventKind.job_failed, payload={"reason": "timeout"})
        await trail_service.handle_event(event)

        nodes = await trail_repo.get_by_job("job-1")
        terminal = nodes[1]
        assert terminal.intent == "Job failed"

    async def test_job_terminal_cleans_up_state(self, trail_service):
        await trail_service.handle_event(_job_started_event())
        assert "job-1" in trail_service._job_state

        await trail_service.handle_event(_make_event(DomainEventKind.job_completed))
        assert "job-1" not in trail_service._job_state


class TestTrailServiceApprovalNodes:
    async def test_approval_deferred_until_step_completes(self, trail_service, trail_repo):
        """Approval requested while step is active gets deferred."""
        await trail_service.handle_event(_job_started_event())
        # Start a step
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_started,
            payload={"step_id": "step-1", "step_number": 1},
        ))
        # Approval arrives mid-step
        await trail_service.handle_event(_make_event(
            DomainEventKind.approval_requested,
            payload={"description": "Need approval for deploy"},
        ))

        # Only goal node so far (approval is deferred)
        nodes = await trail_repo.get_by_job("job-1")
        assert len(nodes) == 1

        # Step completes — should flush the deferred approval
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_completed,
            payload={"step_id": "step-1", "files_read": ["a.py"]},
        ))

        nodes = await trail_repo.get_by_job("job-1")
        # goal + step + request
        assert len(nodes) == 3
        request_node = [n for n in nodes if n.kind == "request"][0]
        assert request_node.intent == "Need approval for deploy"
        assert request_node.enrichment == "complete"


class TestTrailServiceSequencing:
    async def test_seq_is_monotonic(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())
        for i in range(5):
            await trail_service.handle_event(_make_event(
                DomainEventKind.step_completed,
                payload={"step_id": f"step-{i}", "files_read": [f"f{i}.py"]},
            ))

        nodes = await trail_repo.get_by_job("job-1")
        seqs = [n.seq for n in nodes]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # all unique


# ---------------------------------------------------------------------------
# TrailNodeRepository tests
# ---------------------------------------------------------------------------


class TestTrailNodeRepository:
    async def test_create_and_get(self, trail_repo):
        node = TrailNodeRow(
            id="node-1",
            job_id="job-1",
            seq=1,
            anchor_seq=1,
            kind="goal",
            deterministic_kind="goal",
            timestamp=datetime.now(UTC),
            enrichment="complete",
            intent="Fix a bug",
        )
        await trail_repo.create(node)

        fetched = await trail_repo.get("node-1")
        assert fetched is not None
        assert fetched.kind == "goal"
        assert fetched.intent == "Fix a bug"

    async def test_get_by_job_display_order(self, trail_repo):
        """Nodes should be returned in (anchor_seq, seq) order."""
        base = datetime.now(UTC)
        # Create nodes with different anchor_seqs to test display ordering
        for seq, anchor in [(1, 1), (3, 1), (2, 2)]:
            await trail_repo.create(TrailNodeRow(
                id=f"node-{seq}",
                job_id="job-1",
                seq=seq,
                anchor_seq=anchor,
                kind="explore",
                deterministic_kind="explore",
                timestamp=base,
                enrichment="pending",
            ))

        nodes = await trail_repo.get_by_job("job-1")
        seqs = [(n.anchor_seq, n.seq) for n in nodes]
        assert seqs == sorted(seqs)

    async def test_kind_filtering(self, trail_repo):
        base = datetime.now(UTC)
        for i, kind in enumerate(["goal", "explore", "modify", "explore"]):
            await trail_repo.create(TrailNodeRow(
                id=f"node-{i}",
                job_id="job-1",
                seq=i + 1,
                anchor_seq=i + 1,
                kind=kind,
                timestamp=base,
                enrichment="complete",
            ))

        nodes = await trail_repo.get_by_job("job-1", kinds=["explore"])
        assert len(nodes) == 2
        assert all(n.kind == "explore" for n in nodes)

    async def test_after_seq_pagination(self, trail_repo):
        base = datetime.now(UTC)
        for i in range(5):
            await trail_repo.create(TrailNodeRow(
                id=f"node-{i}",
                job_id="job-1",
                seq=i + 1,
                anchor_seq=i + 1,
                kind="explore",
                timestamp=base,
                enrichment="pending",
            ))

        nodes = await trail_repo.get_by_job("job-1", after_seq=3)
        assert len(nodes) == 2
        assert nodes[0].seq == 4
        assert nodes[1].seq == 5

    async def test_pending_enrichment(self, trail_repo):
        base = datetime.now(UTC)
        for i, status in enumerate(["pending", "complete", "failed", "pending"]):
            await trail_repo.create(TrailNodeRow(
                id=f"node-{i}",
                job_id="job-1",
                seq=i + 1,
                anchor_seq=i + 1,
                kind="explore",
                timestamp=base,
                enrichment=status,
            ))

        pending = await trail_repo.get_pending_enrichment(limit=100)
        assert len(pending) == 3  # pending + failed

    async def test_update_enrichment(self, trail_repo):
        base = datetime.now(UTC)
        await trail_repo.create(TrailNodeRow(
            id="node-1",
            job_id="job-1",
            seq=1,
            anchor_seq=1,
            kind="shell",
            deterministic_kind="shell",
            timestamp=base,
            enrichment="pending",
        ))

        await trail_repo.update_enrichment(
            "node-1",
            kind="verify",
            intent="Ran test suite",
            rationale="Checking auth fixes work",
            outcome="All tests pass",
            tags=["testing"],
        )

        node = await trail_repo.get("node-1")
        assert node.kind == "verify"
        assert node.enrichment == "complete"
        assert node.intent == "Ran test suite"
        assert json.loads(node.tags) == ["testing"]

    async def test_max_seq(self, trail_repo):
        base = datetime.now(UTC)
        for i in range(3):
            await trail_repo.create(TrailNodeRow(
                id=f"node-{i}",
                job_id="job-1",
                seq=i + 1,
                anchor_seq=i + 1,
                kind="explore",
                timestamp=base,
                enrichment="pending",
            ))

        assert await trail_repo.max_seq("job-1") == 3
        assert await trail_repo.max_seq("nonexistent") == 0

    async def test_count_by_job(self, trail_repo):
        base = datetime.now(UTC)
        for i, status in enumerate(["complete", "pending", "complete"]):
            await trail_repo.create(TrailNodeRow(
                id=f"node-{i}",
                job_id="job-1",
                seq=i + 1,
                anchor_seq=i + 1,
                kind="explore",
                timestamp=base,
                enrichment=status,
            ))

        total, enriched = await trail_repo.count_by_job("job-1")
        assert total == 3
        assert enriched == 2


# ---------------------------------------------------------------------------
# TrailService query helpers
# ---------------------------------------------------------------------------


class TestTrailServiceQueries:
    async def test_get_trail_flat(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_completed,
            payload={"step_id": "step-1", "files_read": ["a.py"]},
        ))

        result = await trail_service.get_trail("job-1", flat=True)
        assert result["job_id"] == "job-1"
        assert result["total_nodes"] == 2
        assert len(result["nodes"]) == 2
        # Flat mode: no children nesting
        assert all(n.get("children", []) == [] for n in result["nodes"])

    async def test_get_trail_nested(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_completed,
            payload={"step_id": "step-1", "files_read": ["a.py"]},
        ))

        result = await trail_service.get_trail("job-1", flat=False)
        assert len(result["nodes"]) == 1  # Only goal at root
        assert result["nodes"][0]["kind"] == "goal"
        assert len(result["nodes"][0]["children"]) == 1  # explore is a child

    async def test_get_summary(self, trail_service, trail_repo):
        await trail_service.handle_event(_job_started_event())
        for i in range(3):
            await trail_service.handle_event(_make_event(
                DomainEventKind.step_completed,
                payload={"step_id": f"step-{i}", "files_read": [f"f{i}.py"]},
            ))
        await trail_service.handle_event(_make_event(DomainEventKind.job_completed))

        summary = await trail_service.get_summary("job-1")
        assert summary["job_id"] == "job-1"
        assert summary["files_explored"] == 3  # 3 unique files
        assert isinstance(summary["goals"], list)


# ---------------------------------------------------------------------------
# Full lifecycle integration test
# ---------------------------------------------------------------------------


class TestTrailFullLifecycle:
    async def test_complete_job_lifecycle(self, trail_service, trail_repo):
        """Simulate a full job: start → phase → steps → complete."""
        job_id = "job-lifecycle"

        # Job starts
        await trail_service.handle_event(_job_started_event(job_id=job_id))

        # Phase change
        await trail_service.handle_event(_make_event(
            DomainEventKind.execution_phase_changed,
            job_id=job_id,
            payload={"phase": "agent_reasoning"},
        ))

        # Step 1: explore
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_started,
            job_id=job_id,
            payload={"step_id": "step-1", "step_number": 1},
        ))
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_completed,
            job_id=job_id,
            payload={"step_id": "step-1", "files_read": ["auth.py", "config.py"]},
        ))

        # Step 2: modify
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_started,
            job_id=job_id,
            payload={"step_id": "step-2", "step_number": 2},
        ))
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_completed,
            job_id=job_id,
            payload={
                "step_id": "step-2",
                "files_written": ["auth.py"],
                "start_sha": "aaa",
                "end_sha": "bbb",
            },
        ))

        # Step 3: shell (no file tools)
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_started,
            job_id=job_id,
            payload={"step_id": "step-3", "step_number": 3},
        ))
        await trail_service.handle_event(_make_event(
            DomainEventKind.step_completed,
            job_id=job_id,
            payload={"step_id": "step-3"},
        ))

        # Job completes
        await trail_service.handle_event(_make_event(
            DomainEventKind.job_completed, job_id=job_id,
        ))

        # Verify the full trail
        nodes = await trail_repo.get_by_job(job_id)
        kinds = [n.kind for n in nodes]
        assert kinds == ["goal", "summarize", "explore", "modify", "shell", "summarize"]

        # Verify enrichment states
        assert nodes[0].enrichment == "complete"  # goal
        assert nodes[1].enrichment == "complete"  # summarize (phase)
        assert nodes[2].enrichment == "pending"   # explore (needs enrichment)
        assert nodes[3].enrichment == "pending"   # modify (needs enrichment)
        assert nodes[4].enrichment == "pending"   # shell (needs enrichment)
        assert nodes[5].enrichment == "complete"  # summarize (terminal)

        # Verify tree structure
        goal_id = nodes[0].id
        for n in nodes[1:]:
            assert n.parent_id == goal_id

        # Verify state is cleaned up
        assert job_id not in trail_service._job_state

        # Verify counts
        total, enriched = await trail_repo.count_by_job(job_id)
        assert total == 6
        assert enriched == 3  # goal + 2 summarize
