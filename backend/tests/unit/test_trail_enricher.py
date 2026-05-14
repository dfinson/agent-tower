"""Comprehensive tests for TrailEnricher — enrichment, titles, write summaries, edit motivations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.config import TrailConfig
from backend.models.db import TrailNodeRow
from backend.models.events import DomainEventKind
from backend.services.trail.enricher import TrailEnricher
from backend.services.trail.models import TrailJobState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(
    *,
    id: str = "n1",
    job_id: str = "job-1",
    seq: int = 1,
    anchor_seq: int = 1,
    parent_id: str | None = None,
    kind: str = "modify",
    phase: str | None = "execution",
    timestamp: datetime | None = None,
    enrichment: str = "pending",
    intent: str | None = None,
    rationale: str | None = None,
    outcome: str | None = None,
    files: str | None = None,
    tool_name: str | None = None,
    snippet: str | None = None,
    write_summary: str | None = None,
    turn_id: str | None = None,
    agent_message: str | None = None,
    activity_id: str | None = None,
    activity_label: str | None = None,
    plan_item_id: str | None = None,
    title: str | None = None,
    preceding_context: str | None = None,
    deterministic_kind: str | None = None,
    tags: str | None = None,
    supersedes: str | None = None,
    tool_names: str | None = None,
    start_sha: str | None = None,
    end_sha: str | None = None,
) -> MagicMock:
    """Build a mock TrailNodeRow with all required attributes."""
    node = MagicMock(spec=TrailNodeRow)
    node.id = id
    node.job_id = job_id
    node.seq = seq
    node.anchor_seq = anchor_seq
    node.parent_id = parent_id
    node.kind = kind
    node.phase = phase
    node.timestamp = timestamp or datetime.now(UTC)
    node.enrichment = enrichment
    node.intent = intent
    node.rationale = rationale
    node.outcome = outcome
    node.files = files
    node.tool_name = tool_name
    node.snippet = snippet
    node.write_summary = write_summary
    node.turn_id = turn_id
    node.agent_message = agent_message
    node.activity_id = activity_id
    node.activity_label = activity_label
    node.plan_item_id = plan_item_id
    node.title = title
    node.preceding_context = preceding_context
    node.deterministic_kind = deterministic_kind
    node.tags = tags
    node.supersedes = supersedes
    node.tool_names = tool_names
    node.start_sha = start_sha
    node.end_sha = end_sha
    return node


def _make_session_factory():
    """Build a mock async_sessionmaker that works as an async context manager."""
    mock_session = AsyncMock()
    mock_factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_session
    ctx.__aexit__.return_value = False
    mock_factory.return_value = ctx
    mock_factory._mock_session = mock_session  # expose for assertions
    return mock_factory


def _make_enricher(
    *,
    sidecar: AsyncMock | None = None,
    config: TrailConfig | None = None,
    job_state: dict[str, TrailJobState] | None = None,
) -> TrailEnricher:
    """Construct a TrailEnricher with mocked dependencies."""
    session_factory = _make_session_factory()
    event_bus = AsyncMock()
    enricher = TrailEnricher(
        session_factory=session_factory,
        event_bus=event_bus,
        sidecar_sessions=sidecar,
        config=config or TrailConfig(),
        job_state=job_state,
    )
    enricher._repo = AsyncMock()
    return enricher


# ===========================================================================
# drain_enrichment tests
# ===========================================================================


class TestDrainEnrichment:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_sidecar(self):
        enricher = _make_enricher(sidecar=None)
        assert await enricher.drain_enrichment() == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_pending_nodes(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)
        enricher._repo.get_pending_enrichment.return_value = []
        assert await enricher.drain_enrichment() == 0

    @pytest.mark.asyncio
    async def test_basic_annotation_enrichment(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [
                    {
                        "node_id": "n1",
                        "kind": "modify",
                        "intent": "fix bug",
                        "rationale": "tests failing",
                        "outcome": "tests pass",
                        "tags": ["bugfix"],
                        "files": ["src/main.py"],
                    }
                ],
                "semantic_nodes": [],
            }
        )

        result = await enricher.drain_enrichment()
        assert result == 1
        enricher._repo.update_enrichment.assert_called_once()
        call_kwargs = enricher._repo.update_enrichment.call_args
        assert call_kwargs[0][0] == "n1"
        assert call_kwargs[1]["intent"] == "fix bug"

    @pytest.mark.asyncio
    async def test_kind_change_from_shell_to_modify_allowed(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "kind": "modify"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["kind"] == "modify"

    @pytest.mark.asyncio
    async def test_kind_change_blocked_for_modify_node(self):
        """kind change from modify to something else is suppressed."""
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="modify")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "kind": "explore"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["kind"] is None

    @pytest.mark.asyncio
    async def test_kind_change_blocked_for_explore_node(self):
        """kind change from explore is also suppressed."""
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="explore")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "kind": "modify"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["kind"] is None

    @pytest.mark.asyncio
    async def test_kind_change_to_invalid_kind_blocked(self):
        """new_kind not in ALL_KINDS is rejected."""
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "kind": "nonsense_kind"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["kind"] is None

    @pytest.mark.asyncio
    async def test_supersedes_validated_against_repo(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []
        # supersedes node does NOT exist
        enricher._repo.get.return_value = None

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "supersedes": "old-node-xyz"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["supersedes"] is None

    @pytest.mark.asyncio
    async def test_supersedes_valid_passes_through(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []
        enricher._repo.get.return_value = _node(id="old-node")

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "supersedes": "old-node"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["supersedes"] == "old-node"

    @pytest.mark.asyncio
    async def test_files_normalized(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "files": ["./src/app.py", "/absolute/path.py"]}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["files"] == ["src/app.py", "absolute/path.py"]

    @pytest.mark.asyncio
    async def test_files_non_list_ignored(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "files": "not-a-list"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["files"] is None

    @pytest.mark.asyncio
    async def test_tags_must_be_list(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "tags": "not-a-list"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        call_kwargs = enricher._repo.update_enrichment.call_args[1]
        assert call_kwargs["tags"] is None

    @pytest.mark.asyncio
    async def test_unknown_node_id_skipped(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "unknown-node", "intent": "mystery"}],
                "semantic_nodes": [],
            }
        )

        result = await enricher.drain_enrichment()
        assert result == 0
        enricher._repo.update_enrichment.assert_not_called()

    @pytest.mark.asyncio
    async def test_parse_failure_marks_all_failed(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        n1 = _node(id="n1", job_id="j1", kind="shell")
        n2 = _node(id="n2", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [n1, n2]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = "this is not valid json"

        result = await enricher.drain_enrichment()
        assert result == 0
        assert enricher._repo.update_enrichment.call_count == 2
        for call in enricher._repo.update_enrichment.call_args_list:
            assert call[1]["enrichment"] == "failed"

    @pytest.mark.asyncio
    async def test_semantic_node_created(self):
        sidecar = AsyncMock()
        job_state = {"j1": TrailJobState(next_seq=10)}
        enricher = _make_enricher(sidecar=sidecar, job_state=job_state)

        node = _node(id="n1", job_id="j1", kind="modify", anchor_seq=5, parent_id="p1", phase="execution")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [],
                "semantic_nodes": [
                    {
                        "kind": "decide",
                        "intent": "chose approach A",
                        "rationale": "simpler",
                        "outcome": "proceeding",
                        "tags": ["architecture"],
                        "anchor_node_id": "n1",
                    }
                ],
            }
        )

        result = await enricher.drain_enrichment()
        assert result == 1
        enricher._repo.create.assert_called_once()
        created = enricher._repo.create.call_args[0][0]
        assert created.kind == "decide"
        assert created.anchor_seq == 5
        assert created.parent_id == "p1"
        assert created.phase == "execution"
        assert created.enrichment == "complete"
        assert job_state["j1"].next_seq == 11

    @pytest.mark.asyncio
    async def test_semantic_node_without_anchor_uses_first_node(self):
        sidecar = AsyncMock()
        job_state = {"j1": TrailJobState(next_seq=5)}
        enricher = _make_enricher(sidecar=sidecar, job_state=job_state)

        node = _node(id="n1", job_id="j1", kind="modify", anchor_seq=3, parent_id="p2")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [],
                "semantic_nodes": [{"kind": "insight", "anchor_node_id": None}],
            }
        )

        await enricher.drain_enrichment()
        created = enricher._repo.create.call_args[0][0]
        assert created.anchor_seq == 3
        assert created.parent_id == "p2"

    @pytest.mark.asyncio
    async def test_semantic_node_without_job_state_uses_max_seq(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar, job_state={})

        node = _node(id="n1", job_id="j1", kind="modify", anchor_seq=3, parent_id="p1")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []
        enricher._repo.max_seq.return_value = 20

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [],
                "semantic_nodes": [{"kind": "plan"}],
            }
        )

        await enricher.drain_enrichment()
        created = enricher._repo.create.call_args[0][0]
        assert created.seq == 21

    @pytest.mark.asyncio
    async def test_semantic_node_invalid_kind_skipped(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [],
                "semantic_nodes": [{"kind": "invalid_kind"}],
            }
        )

        result = await enricher.drain_enrichment()
        assert result == 0
        enricher._repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_node_supersedes_validated(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar, job_state={"j1": TrailJobState(next_seq=1)})

        node = _node(id="n1", job_id="j1", kind="modify")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []
        enricher._repo.get.return_value = None  # supersedes target doesn't exist

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [],
                "semantic_nodes": [{"kind": "backtrack", "supersedes": "nonexistent"}],
            }
        )

        await enricher.drain_enrichment()
        created = enricher._repo.create.call_args[0][0]
        assert created.supersedes is None

    @pytest.mark.asyncio
    async def test_goal_intent_passed_to_prompt(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        goal_node = _node(id="g1", intent="implement feature X")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = [goal_node]
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        prompt_text = sidecar.complete.call_args[0][0]
        assert "implement feature X" in prompt_text

    @pytest.mark.asyncio
    async def test_exception_marks_nodes_failed(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []
        sidecar.complete.side_effect = OSError("network down")

        result = await enricher.drain_enrichment()
        assert result == 0
        enricher._repo.update_enrichment.assert_called_once_with("n1", enrichment="failed")

    @pytest.mark.asyncio
    async def test_exception_marking_failed_is_swallowed(self):
        """If update_enrichment itself fails during error handling, it doesn't crash."""
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []
        sidecar.complete.side_effect = ValueError("bad")
        enricher._repo.update_enrichment.side_effect = SQLAlchemyError("db error")

        # Should not raise
        result = await enricher.drain_enrichment()
        assert result == 0

    @pytest.mark.asyncio
    async def test_sidecar_returns_non_string(self):
        """When sidecar returns something other than str, it's converted."""
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [node]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        # Return a dict directly (non-string)
        response = {
            "annotations": [{"node_id": "n1", "intent": "test"}],
            "semantic_nodes": [],
        }
        sidecar.complete.return_value = response

        # The str(result) will produce dict repr, which isn't valid JSON → parse fails
        await enricher.drain_enrichment()
        # Parse will fail → marks failed
        assert enricher._repo.update_enrichment.call_count >= 1

    @pytest.mark.asyncio
    async def test_multiple_jobs_processed(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        n1 = _node(id="n1", job_id="j1", kind="shell")
        n2 = _node(id="n2", job_id="j2", kind="shell")
        enricher._repo.get_pending_enrichment.return_value = [n1, n2]
        enricher._repo.get_by_job.return_value = []
        enricher._repo.get_recent_decisions.return_value = []

        sidecar.complete.return_value = json.dumps(
            {
                "annotations": [{"node_id": "n1", "intent": "a"}],
                "semantic_nodes": [],
            }
        )

        await enricher.drain_enrichment()
        # Called twice — once per job
        assert sidecar.complete.call_count == 2


# ===========================================================================
# drain_titles tests
# ===========================================================================


class TestDrainTitles:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_untitled_nodes(self):
        enricher = _make_enricher()
        enricher._repo.get_untitled_work_nodes.return_value = []
        assert await enricher.drain_titles() == 0

    @pytest.mark.asyncio
    async def test_file_based_title(self):
        enricher = _make_enricher()
        node = _node(
            id="n1",
            job_id="j1",
            files=json.dumps(["src/app.py", "src/config.py"]),
            agent_message=None,
            activity_id="",
            activity_label="",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        result = await enricher.drain_titles()
        assert result == 1
        mock_session = enricher._session_factory._mock_session
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_title_truncates_to_three(self):
        enricher = _make_enricher()
        files = ["a.py", "b.py", "c.py", "d.py", "e.py"]
        node = _node(
            id="n1",
            files=json.dumps(files),
            agent_message=None,
            activity_id="",
            activity_label="",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        await enricher.drain_titles()
        mock_session = enricher._session_factory._mock_session
        assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_message_based_title(self):
        enricher = _make_enricher()
        node = _node(
            id="n1",
            files=None,
            agent_message="Fixed the auth bug\nMore details here",
            activity_id="act-1",
            activity_label="fix auth",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        result = await enricher.drain_titles()
        assert result == 1

    @pytest.mark.asyncio
    async def test_no_signal_node_skipped(self):
        """Node with no files and no agent_message is skipped."""
        enricher = _make_enricher()
        node = _node(id="n1", files=None, agent_message=None)
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        result = await enricher.drain_titles()
        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_files_json_falls_through_to_message(self):
        """files=[] means no files written → fall through to agent_message."""
        enricher = _make_enricher()
        node = _node(
            id="n1",
            files=json.dumps([]),
            agent_message="Setting up project\nline2",
            activity_id="",
            activity_label="",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        result = await enricher.drain_titles()
        assert result == 1

    @pytest.mark.asyncio
    async def test_event_published_when_activity_id_present(self):
        enricher = _make_enricher()
        node = _node(
            id="n1",
            job_id="j1",
            files=json.dumps(["main.py"]),
            agent_message=None,
            activity_id="act-123",
            activity_label="fixing bugs",
            turn_id="turn-1",
            plan_item_id="plan-1",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        await enricher.drain_titles()
        enricher._event_bus.publish.assert_called_once()
        event = enricher._event_bus.publish.call_args[0][0]
        assert event.kind == DomainEventKind.turn_summary
        assert event.payload["activity_id"] == "act-123"
        assert event.payload["title"] == "Edited main.py"
        assert event.payload["is_new_activity"] is False
        assert event.payload["plan_item_id"] == "plan-1"

    @pytest.mark.asyncio
    async def test_no_event_when_activity_id_empty(self):
        enricher = _make_enricher()
        node = _node(
            id="n1",
            files=json.dumps(["main.py"]),
            agent_message=None,
            activity_id="",
            activity_label="",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        await enricher.drain_titles()
        enricher._event_bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_caught_and_continues(self):
        enricher = _make_enricher()
        good_node = _node(
            id="n2",
            files=json.dumps(["ok.py"]),
            agent_message=None,
            activity_id="",
            activity_label="",
        )
        enricher._repo.get_untitled_work_nodes.return_value = [good_node]

        enricher._session_factory._mock_session.execute.side_effect = SQLAlchemyError("db error")

        # Should not raise, returns 0 since processing failed
        result = await enricher.drain_titles()
        assert result == 0

    @pytest.mark.asyncio
    async def test_activity_id_none_treated_as_empty(self):
        """activity_id=None → no event published."""
        enricher = _make_enricher()
        node = _node(
            id="n1",
            files=json.dumps(["f.py"]),
            agent_message=None,
            activity_id=None,
            activity_label=None,
        )
        enricher._repo.get_untitled_work_nodes.return_value = [node]

        await enricher.drain_titles()
        enricher._event_bus.publish.assert_not_called()


# ===========================================================================
# drain_write_summaries tests
# ===========================================================================


class TestDrainWriteSummaries:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_sidecar(self):
        enricher = _make_enricher(sidecar=None)
        assert await enricher.drain_write_summaries() == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_unsummarized_nodes(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)
        enricher._repo.get_unsummarized_write_nodes.return_value = []
        assert await enricher.drain_write_summaries() == 0

    @pytest.mark.asyncio
    async def test_no_parent_context_marks_empty_summary(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id="p1", tool_name="create", snippet=None, files=None)
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]
        # Parent has no preceding_context
        parent = _node(id="p1", preceding_context=None)
        enricher._repo.get.return_value = parent

        # Mock job desc fetch
        mock_session = AsyncMock()
        mock_job_row = MagicMock()
        mock_job_row.description = "test job"
        mock_job_row.prompt = None

        enricher._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        enricher._session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = mock_job_row
            mock_job_repo_cls.return_value = mock_job_repo_inst

            result = await enricher.drain_write_summaries()

        assert result == 1
        enricher._repo.set_write_summary.assert_called_once_with("n1", "")

    @pytest.mark.asyncio
    async def test_no_parent_id_marks_empty(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id=None, tool_name="create")
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = None
            mock_job_repo_cls.return_value = mock_job_repo_inst

            result = await enricher.drain_write_summaries()

        assert result == 1
        enricher._repo.set_write_summary.assert_called_once_with("n1", "")

    @pytest.mark.asyncio
    async def test_with_context_calls_sidecar(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "Updated auth middleware to validate tokens"
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(
            id="n1",
            job_id="j1",
            parent_id="p1",
            tool_name="str_replace_editor",
            snippet="- old code\n+ new code",
            files=json.dumps(["src/auth.py"]),
        )
        parent = _node(id="p1", preceding_context="Agent was fixing authentication")
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        mock_job_row = MagicMock()
        mock_job_row.description = "Fix auth bug"
        mock_job_row.prompt = None

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = mock_job_row
            mock_job_repo_cls.return_value = mock_job_repo_inst

            result = await enricher.drain_write_summaries()

        assert result == 1
        enricher._repo.set_write_summary.assert_called_once_with("n1", "Updated auth middleware to validate tokens")
        prompt_text = sidecar.complete.call_args[0][0]
        assert "CODE SNIPPET" in prompt_text
        assert "FILE: src/auth.py" in prompt_text

    @pytest.mark.asyncio
    async def test_job_description_from_prompt_fallback(self):
        """When job.description is None, falls back to job.prompt."""
        sidecar = AsyncMock()
        sidecar.complete.return_value = "summary"
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id="p1", tool_name="create")
        parent = _node(id="p1", preceding_context="ctx")
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        mock_job_row = MagicMock()
        mock_job_row.description = None
        mock_job_row.prompt = "Fix the tests"

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = mock_job_row
            mock_job_repo_cls.return_value = mock_job_repo_inst

            await enricher.drain_write_summaries()

        prompt_text = sidecar.complete.call_args[0][0]
        assert "Fix the tests" in prompt_text

    @pytest.mark.asyncio
    async def test_no_snippet_no_file_still_works(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "basic summary"
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id="p1", tool_name="write", snippet=None, files=None)
        parent = _node(id="p1", preceding_context="some context")
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = None
            mock_job_repo_cls.return_value = mock_job_repo_inst

            result = await enricher.drain_write_summaries()

        assert result == 1
        prompt_text = sidecar.complete.call_args[0][0]
        assert "CODE SNIPPET" not in prompt_text
        assert "FILE:" not in prompt_text

    @pytest.mark.asyncio
    async def test_sidecar_error_caught(self):
        sidecar = AsyncMock()
        sidecar.complete.side_effect = OSError("network")
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id="p1", tool_name="create")
        parent = _node(id="p1", preceding_context="ctx")
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = None
            mock_job_repo_cls.return_value = mock_job_repo_inst

            result = await enricher.drain_write_summaries()

        assert result == 0
        enricher._repo.set_write_summary.assert_not_called()

    @pytest.mark.asyncio
    async def test_sidecar_returns_non_string_converted(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = 42  # non-string
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id="p1", tool_name="create")
        parent = _node(id="p1", preceding_context="ctx")
        enricher._repo.get_unsummarized_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        with patch("backend.persistence.job_repo.JobRepository") as mock_job_repo_cls:
            mock_job_repo_inst = AsyncMock()
            mock_job_repo_inst.get.return_value = None
            mock_job_repo_cls.return_value = mock_job_repo_inst

            result = await enricher.drain_write_summaries()

        assert result == 1
        enricher._repo.set_write_summary.assert_called_once_with("n1", "42")


# ===========================================================================
# drain_edit_motivations tests
# ===========================================================================


class TestDrainEditMotivations:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_sidecar(self):
        enricher = _make_enricher(sidecar=None)
        assert await enricher.drain_edit_motivations() == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_unenriched_nodes(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)
        enricher._repo.get_unenriched_edit_write_nodes.return_value = []
        assert await enricher.drain_edit_motivations() == 0

    @pytest.mark.asyncio
    async def test_no_snippet_marks_empty_edits(self):
        sidecar = AsyncMock()
        enricher = _make_enricher(sidecar=sidecar)

        node = _node(id="n1", job_id="j1", parent_id="p1", tool_name="write", snippet=None)
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]
        enricher._repo.get.return_value = None  # no parent

        result = await enricher.drain_edit_motivations()
        assert result == 1
        enricher._repo.set_edit_motivations.assert_called_once_with("n1", "[]")

    @pytest.mark.asyncio
    async def test_snippet_with_old_new_lines(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "Changed method signature for clarity"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "- def old_method(self):\n+ def new_method(self, arg):"
        node = _node(
            id="n1",
            job_id="j1",
            parent_id="p1",
            tool_name="str_replace_editor",
            snippet=snippet,
            files=json.dumps(["src/main.py"]),
            write_summary="refactored method",
        )
        parent = _node(id="p1", preceding_context="refactoring module")
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        result = await enricher.drain_edit_motivations()
        assert result == 1

        call_args = enricher._repo.set_edit_motivations.call_args
        motivations = json.loads(call_args[0][1])
        assert len(motivations) == 1
        assert motivations[0]["summary"] == "Changed method signature for clarity"
        assert "edit_key" in motivations[0]

    @pytest.mark.asyncio
    async def test_snippet_with_only_new_lines(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "Added new function"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "+ def new_func():\n+     return True"
        node = _node(
            id="n1",
            job_id="j1",
            parent_id=None,
            tool_name="create",
            snippet=snippet,
            files=json.dumps(["src/new.py"]),
            write_summary=None,
        )
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]

        result = await enricher.drain_edit_motivations()
        assert result == 1
        sidecar.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_key_computed_for_replace(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "fix"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "- old_code\n+ new_code"
        node = _node(id="n1", tool_name="str_replace_editor", snippet=snippet, parent_id=None)
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]

        await enricher.drain_edit_motivations()
        call_args = enricher._repo.set_edit_motivations.call_args
        motivations = json.loads(call_args[0][1])
        assert motivations[0]["edit_key"].startswith("replace:")

    @pytest.mark.asyncio
    async def test_prompt_includes_file_path(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "updated config"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "+ new_setting = True"
        node = _node(
            id="n1",
            tool_name="create",
            snippet=snippet,
            files=json.dumps(["config/settings.py"]),
            parent_id="p1",
            write_summary="config changes",
        )
        parent = _node(id="p1", preceding_context="updating configuration")
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        await enricher.drain_edit_motivations()
        prompt_text = sidecar.complete.call_args[0][0]
        assert "config/settings.py" in prompt_text

    @pytest.mark.asyncio
    async def test_no_parent_no_context(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "added file"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "+ content"
        node = _node(id="n1", tool_name="create", snippet=snippet, parent_id=None, write_summary=None)
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]

        await enricher.drain_edit_motivations()
        prompt_text = sidecar.complete.call_args[0][0]
        # No PRECEDING CONTEXT in the prompt since parent is None
        assert "PRECEDING CONTEXT" not in prompt_text or "None" in prompt_text

    @pytest.mark.asyncio
    async def test_sidecar_error_caught(self):
        sidecar = AsyncMock()
        sidecar.complete.side_effect = OSError("network")
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "- old\n+ new"
        node = _node(id="n1", tool_name="edit", snippet=snippet, parent_id=None)
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]

        result = await enricher.drain_edit_motivations()
        assert result == 0
        enricher._repo.set_edit_motivations.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_files_json_gives_empty_path(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "summary"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "+ x"
        node = _node(
            id="n1",
            tool_name="create",
            snippet=snippet,
            files=json.dumps([]),
            parent_id=None,
        )
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]

        await enricher.drain_edit_motivations()
        # Should still succeed with empty file_path
        assert enricher._repo.set_edit_motivations.called

    @pytest.mark.asyncio
    async def test_sidecar_returns_non_string(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = {"result": "obj"}
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "+ code"
        node = _node(id="n1", tool_name="create", snippet=snippet, parent_id=None)
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]

        await enricher.drain_edit_motivations()
        call_args = enricher._repo.set_edit_motivations.call_args
        motivations = json.loads(call_args[0][1])
        # str(dict) is used as summary
        assert "result" in motivations[0]["summary"]

    @pytest.mark.asyncio
    async def test_write_summary_included_in_prompt(self):
        sidecar = AsyncMock()
        sidecar.complete.return_value = "detail"
        enricher = _make_enricher(sidecar=sidecar)

        snippet = "- old\n+ new"
        node = _node(
            id="n1",
            tool_name="edit",
            snippet=snippet,
            parent_id="p1",
            write_summary="High-level: updated module interface",
        )
        parent = _node(id="p1", preceding_context="working on interfaces")
        enricher._repo.get_unenriched_edit_write_nodes.return_value = [node]
        enricher._repo.get.return_value = parent

        await enricher.drain_edit_motivations()
        prompt_text = sidecar.complete.call_args[0][0]
        assert "updated module interface" in prompt_text


# ===========================================================================
# Integration-ish: constructor defaults
# ===========================================================================


class TestEnricherInit:
    def test_default_config_used_when_none(self):
        enricher = _make_enricher()
        assert enricher._config.enrich_batch_size == 20

    def test_custom_config_used(self):
        cfg = TrailConfig(enrich_batch_size=5)
        enricher = _make_enricher(config=cfg)
        assert enricher._config.enrich_batch_size == 5

    def test_job_state_defaults_to_empty_dict(self):
        enricher = _make_enricher()
        assert enricher._job_state == {}

    def test_job_state_passed_through(self):
        state = {"j1": TrailJobState(next_seq=42)}
        enricher = _make_enricher(job_state=state)
        assert enricher._job_state["j1"].next_seq == 42
