"""Tests for structural analysis endpoints (structural-diff, multi-session, impact-graph, communities, review-story)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.job_artifacts import (
    _build_structural_changes,
    _classify_category,
    _compute_merge_confidence,
    _compute_risk,
    _compute_triage,
    _translate_ref_tiers,
    get_impact_graph,
    get_job_communities,
    get_job_multi_session,
    get_job_structural_diff,
    get_review_story,
)
from backend.models.api_schemas import (
    CommunitiesResponse,
    ImpactGraphResponse,
    MultiSessionResponse,
    ReviewStoryResponse,
    StructuralChange,
    StructuralDiffResponse,
)
from backend.models.domain import Job, JobState
from backend.models.events import DomainEvent, DomainEventKind


# -- Fixtures ------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _make_job(job_id: str = "job-1", **overrides: Any) -> Job:
    now = _now()
    defaults = {
        "id": job_id,
        "repo": "/repos/test",
        "prompt": "Fix the bug in auth module",
        "state": JobState.review,
        "base_ref": "main",
        "branch": "feat/test",
        "worktree_path": "/repos/test/.wt/fix-bug",
        "session_id": None,
        "created_at": now,
        "updated_at": now,
        "session_count": 1,
    }
    defaults.update(overrides)
    return Job(**defaults)


@dataclass
class FakeDiffResult:
    summary: str = "Modified 3 symbols"
    structural_changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeCyclesResult:
    cycles: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeCommunitiesResult:
    communities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeImpactResult:
    references: list[dict[str, Any]] = field(default_factory=list)
    total_references: int = 0
    files_affected: int = 0
    summary: str = ""


def _make_coderecon(*, available: bool = True) -> SimpleNamespace:
    svc = SimpleNamespace()
    svc.available = available
    svc.ensure_repo_indexed = AsyncMock(return_value="test-repo")
    svc.semantic_diff = AsyncMock(return_value=FakeDiffResult())
    svc.graph_cycles = AsyncMock(return_value=FakeCyclesResult())
    svc.graph_communities = AsyncMock(return_value=FakeCommunitiesResult())
    svc.recon_impact = AsyncMock(return_value=FakeImpactResult())
    return svc


def _make_svc(job: Job | None = None) -> SimpleNamespace:
    svc = SimpleNamespace()
    svc.get_job = AsyncMock(return_value=job)
    return svc


# -- Unit tests for helper functions -------------------------------------------


class TestClassifyCategory:
    def test_removed_with_callers_is_breaking(self) -> None:
        assert _classify_category({"kind": "removed", "ref_count": 3}) == "breaking"

    def test_removed_no_callers_is_non_structural(self) -> None:
        assert _classify_category({"kind": "removed", "ref_count": 0}) == "non-structural"

    def test_modified_signature_change_is_breaking(self) -> None:
        assert _classify_category({"kind": "modified", "signature_changed": True}) == "breaking"

    def test_modified_body_only(self) -> None:
        assert _classify_category({"kind": "modified", "signature_changed": False}) == "body"

    def test_added_is_additive(self) -> None:
        assert _classify_category({"kind": "added"}) == "additive"

    def test_moved_is_body(self) -> None:
        assert _classify_category({"kind": "moved"}) == "body"

    def test_unknown_kind_is_non_structural(self) -> None:
        assert _classify_category({"kind": "unknown"}) == "non-structural"


class TestTranslateRefTiers:
    def test_proven_maps_to_verified(self) -> None:
        assert _translate_ref_tiers({"PROVEN": 5}) == {"verified": 5}

    def test_strong_and_semantic_map_to_inferred(self) -> None:
        result = _translate_ref_tiers({"STRONG": 2, "SEMANTIC": 3})
        assert result == {"inferred": 5}

    def test_unknown_maps_to_unverified(self) -> None:
        assert _translate_ref_tiers({"UNKNOWN": 4}) == {"unverified": 4}

    def test_mixed_tiers(self) -> None:
        result = _translate_ref_tiers({"PROVEN": 1, "UNKNOWN": 2, "ANCHORED": 3})
        assert result == {"verified": 1, "unverified": 2, "inferred": 3}


class TestComputeRisk:
    def test_zero_risk_for_non_structural(self) -> None:
        risk = _compute_risk("non-structural", {}, [])
        assert risk == 0.25  # 0.4*0 + 0.35*0 + 0.25*1 (no tests)

    def test_max_risk_for_breaking_unverified_no_tests(self) -> None:
        risk = _compute_risk("breaking", {"unverified": 5}, [])
        assert risk == 1.0  # 0.4*1 + 0.35*1 + 0.25*1

    def test_low_risk_for_additive_with_tests(self) -> None:
        risk = _compute_risk("additive", {"verified": 3}, ["test_foo.py"])
        assert risk == 0.04  # 0.4*0.1 + 0.35*0 + 0.25*0

    def test_partial_unverified(self) -> None:
        risk = _compute_risk("body", {"verified": 2, "unverified": 2}, [])
        # 0.4*0.5 + 0.35*0.5 + 0.25*1 = 0.2 + 0.175 + 0.25 = 0.625
        assert risk == 0.62  # rounded to 2dp


class TestComputeMergeConfidence:
    def test_high_when_all_verified_with_tests(self) -> None:
        changes = [
            StructuralChange(kind="modified", file="a.py", category="body",
                             ref_tiers={"verified": 3}, test_files=["test_a.py"]),
        ]
        assert _compute_merge_confidence(changes) == "HIGH"

    def test_low_when_new_cycles(self) -> None:
        changes = [
            StructuralChange(kind="added", file="a.py", category="additive"),
        ]
        assert _compute_merge_confidence(changes, has_new_cycles=True) == "LOW"

    def test_low_when_breaking_with_unverified(self) -> None:
        changes = [
            StructuralChange(kind="modified", file="a.py", category="breaking",
                             ref_tiers={"unverified": 2}),
        ]
        assert _compute_merge_confidence(changes) == "LOW"

    def test_medium_when_unverified_on_non_breaking(self) -> None:
        changes = [
            StructuralChange(kind="modified", file="a.py", category="body",
                             ref_tiers={"unverified": 1}),
        ]
        assert _compute_merge_confidence(changes) == "MEDIUM"

    def test_medium_when_breaking_without_tests(self) -> None:
        changes = [
            StructuralChange(kind="modified", file="a.py", category="breaking",
                             ref_tiers={"verified": 3}, test_files=[]),
        ]
        assert _compute_merge_confidence(changes) == "MEDIUM"


class TestBuildStructuralChanges:
    def test_enriches_raw_changes(self) -> None:
        raw = [
            {
                "kind": "modified",
                "symbol": "foo",
                "file": "src/foo.py",
                "summary": "Changed signature",
                "signature_changed": True,
                "ref_count": 5,
                "ref_tiers": {"PROVEN": 3, "UNKNOWN": 2},
                "test_files": ["tests/test_foo.py"],
                "line_range": [10, 20],
            }
        ]
        result = _build_structural_changes(raw)
        assert len(result) == 1
        ch = result[0]
        assert ch.kind == "modified"
        assert ch.symbol == "foo"
        assert ch.category == "breaking"
        assert ch.ref_tiers == {"verified": 3, "unverified": 2}
        assert ch.risk > 0

    def test_unclassified_refs_treated_as_unverified(self) -> None:
        raw = [{"kind": "removed", "file": "x.py", "ref_count": 10, "ref_tiers": {"PROVEN": 3}}]
        result = _build_structural_changes(raw)
        assert result[0].ref_tiers["unverified"] == 7

    def test_empty_input(self) -> None:
        assert _build_structural_changes([]) == []


class TestComputeTriage:
    def test_counts_categories(self) -> None:
        changes = [
            StructuralChange(kind="modified", file="a.py", category="breaking"),
            StructuralChange(kind="modified", file="b.py", category="breaking"),
            StructuralChange(kind="added", file="c.py", category="additive"),
            StructuralChange(kind="modified", file="d.py", category="body"),
        ]
        triage = _compute_triage(changes)
        assert triage == {"breaking": 2, "additive": 1, "body": 1}


# -- Endpoint tests ------------------------------------------------------------


@pytest.mark.asyncio
async def test_structural_diff_unavailable() -> None:
    """Returns available=False when CodeRecon is not available."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon(available=False)
    result = await get_job_structural_diff("job-1", svc, coderecon)
    assert isinstance(result, StructuralDiffResponse)
    assert result.available is False


@pytest.mark.asyncio
async def test_structural_diff_no_worktree() -> None:
    """Returns available=False when job has no worktree."""
    job = _make_job(worktree_path=None)
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    result = await get_job_structural_diff("job-1", svc, coderecon)
    assert result.available is False


@pytest.mark.asyncio
async def test_structural_diff_success() -> None:
    """Returns enriched structural changes with triage and confidence."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.semantic_diff.return_value = FakeDiffResult(
        summary="3 changes",
        structural_changes=[
            {"kind": "added", "symbol": "new_fn", "file": "src/new.py", "ref_count": 0},
            {"kind": "modified", "symbol": "old_fn", "file": "src/old.py", "ref_count": 2,
             "ref_tiers": {"PROVEN": 2}, "signature_changed": False},
        ],
    )
    result = await get_job_structural_diff("job-1", svc, coderecon)
    assert result.available is True
    assert len(result.changes) == 2
    assert result.merge_confidence == "HIGH"
    assert result.triage["additive"] == 1
    assert result.triage["body"] == 1


@pytest.mark.asyncio
async def test_structural_diff_with_new_cycles_lowers_confidence() -> None:
    """New dependency cycles result in LOW merge confidence."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[{"kind": "added", "symbol": "x", "file": "a.py"}],
    )
    coderecon.graph_cycles.side_effect = [
        FakeCyclesResult(cycles=[{"members": ["a.py", "b.py"]}]),  # worktree
        FakeCyclesResult(cycles=[]),  # base (no cycles)
    ]
    result = await get_job_structural_diff("job-1", svc, coderecon)
    assert result.merge_confidence == "LOW"


@pytest.mark.asyncio
async def test_impact_graph_success() -> None:
    """Returns enriched references with tier labels."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.recon_impact.return_value = FakeImpactResult(
        references=[
            {"symbol": "caller_a", "file": "src/a.py", "line": 42, "tier": "PROVEN", "is_test": False},
            {"symbol": "test_b", "file": "tests/b.py", "line": 10, "tier": "UNKNOWN", "is_test": True},
        ],
        total_references=2,
        files_affected=2,
        summary="2 callers found",
    )
    result = await get_impact_graph("job-1", "target_fn", svc, coderecon)
    assert isinstance(result, ImpactGraphResponse)
    assert result.total_references == 2
    assert result.references[0].tier == "verified"
    assert result.references[1].tier == "unverified"
    assert result.references[1].is_test is True


@pytest.mark.asyncio
async def test_impact_graph_unavailable_raises_503() -> None:
    """Raises 503 when CodeRecon is unavailable."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon(available=False)
    with pytest.raises(Exception) as exc_info:
        await get_impact_graph("job-1", "target_fn", svc, coderecon)
    assert "503" in str(exc_info.value.status_code)


@pytest.mark.asyncio
async def test_communities_success() -> None:
    """Groups changes by community with risk totals."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[
            {"kind": "modified", "symbol": "fn_a", "file": "src/auth/login.py", "ref_count": 0},
            {"kind": "added", "symbol": "fn_b", "file": "src/auth/signup.py", "ref_count": 0},
            {"kind": "modified", "symbol": "fn_c", "file": "src/db/query.py", "ref_count": 0},
        ],
    )
    coderecon.graph_communities.return_value = FakeCommunitiesResult(
        communities=[
            {"name": "auth", "members": ["src/auth/login.py", "src/auth/signup.py"]},
            {"name": "database", "members": ["src/db/query.py", "src/db/models.py"]},
        ]
    )
    result = await get_job_communities("job-1", svc, coderecon)
    assert isinstance(result, CommunitiesResponse)
    assert len(result.communities) == 2
    names = {c.name for c in result.communities}
    assert "auth" in names
    assert "database" in names
    assert result.unclustered == []


@pytest.mark.asyncio
async def test_communities_unclustered() -> None:
    """Files not in any community go to unclustered."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[
            {"kind": "added", "symbol": "orphan", "file": "misc/util.py", "ref_count": 0},
        ],
    )
    coderecon.graph_communities.return_value = FakeCommunitiesResult(
        communities=[{"name": "core", "members": ["src/core.py"]}]
    )
    result = await get_job_communities("job-1", svc, coderecon)
    assert len(result.communities) == 0
    assert len(result.unclustered) == 1


@pytest.mark.asyncio
async def test_review_story_unavailable() -> None:
    """Returns available=False when CodeRecon not available."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon(available=False)
    result = await get_review_story("job-1", svc, coderecon)
    assert isinstance(result, ReviewStoryResponse)
    assert result.available is False
    assert result.header is None


@pytest.mark.asyncio
async def test_review_story_success() -> None:
    """Returns full story with header, attention, concerns, verdict."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[
            {"kind": "modified", "symbol": "auth_check", "file": "src/auth.py",
             "signature_changed": True, "ref_count": 5, "ref_tiers": {"UNKNOWN": 5}},
            {"kind": "added", "symbol": "new_helper", "file": "src/util.py", "ref_count": 0},
        ],
    )
    result = await get_review_story("job-1", svc, coderecon)
    assert result.available is True
    assert result.header is not None
    assert result.header.breaking_count == 1
    assert result.header.file_count == 2
    assert result.header.merge_confidence == "LOW"
    assert len(result.attention_required) == 1
    assert result.verdict is not None
    assert result.verdict.confidence == "LOW"
    assert len(result.verdict.blockers) > 0


@pytest.mark.asyncio
async def test_multi_session_single_session_returns_empty() -> None:
    """Single-session job returns empty sessions list."""
    job = _make_job(session_count=1)
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    event_repo = SimpleNamespace(list_by_job=AsyncMock(return_value=[]))
    result = await get_job_multi_session("job-1", svc, step_repo, event_repo, coderecon)
    assert isinstance(result, MultiSessionResponse)
    assert result.sessions == []


@pytest.mark.asyncio
async def test_multi_session_partitions_by_event_boundaries() -> None:
    """Steps are partitioned using session_resumed event timestamps."""
    base_time = _now()
    job = _make_job(session_count=2)
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[{"kind": "added", "symbol": "x", "file": "a.py"}],
    )

    # Two steps: one before boundary, one after
    step1 = SimpleNamespace(
        started_at=base_time - timedelta(hours=1),
        start_sha="aaa", end_sha="bbb",
        files_written=None,
    )
    step2 = SimpleNamespace(
        started_at=base_time + timedelta(minutes=5),
        start_sha="ccc", end_sha="ddd",
        files_written=None,
    )
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[step1, step2]))

    # Session boundary: session_resumed event at base_time
    resumed_event = DomainEvent(
        event_id="evt-1",
        job_id="job-1",
        timestamp=base_time,
        kind=DomainEventKind.session_resumed,
        payload={"session_number": 2},
    )
    event_repo = SimpleNamespace(list_by_job=AsyncMock(return_value=[resumed_event]))

    result = await get_job_multi_session("job-1", svc, step_repo, event_repo, coderecon)
    assert len(result.sessions) == 2
    assert result.sessions[0].session_number == 1
    assert result.sessions[1].session_number == 2


@pytest.mark.asyncio
async def test_multi_session_direction_change_detection() -> None:
    """Detects when session 2 modifies symbols added by session 1."""
    base_time = _now()
    job = _make_job(session_count=2)
    svc = _make_svc(job)
    coderecon = _make_coderecon()

    # Session 1 adds symbol "new_fn", session 2 modifies it
    diff_call_count = 0

    async def _mock_diff(*args: Any, **kwargs: Any) -> FakeDiffResult:
        nonlocal diff_call_count
        diff_call_count += 1
        if diff_call_count == 1:
            return FakeDiffResult(structural_changes=[
                {"kind": "added", "symbol": "new_fn", "file": "a.py", "ref_count": 0},
            ])
        return FakeDiffResult(structural_changes=[
            {"kind": "modified", "symbol": "new_fn", "file": "a.py", "ref_count": 0},
        ])

    coderecon.semantic_diff = AsyncMock(side_effect=_mock_diff)

    step1 = SimpleNamespace(
        started_at=base_time - timedelta(hours=1),
        start_sha="aaa", end_sha="bbb",
        files_written=None,
    )
    step2 = SimpleNamespace(
        started_at=base_time + timedelta(minutes=5),
        start_sha="ccc", end_sha="ddd",
        files_written=None,
    )
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[step1, step2]))

    resumed_event = DomainEvent(
        event_id="evt-1",
        job_id="job-1",
        timestamp=base_time,
        kind=DomainEventKind.session_resumed,
        payload={"session_number": 2},
    )
    event_repo = SimpleNamespace(list_by_job=AsyncMock(return_value=[resumed_event]))

    result = await get_job_multi_session("job-1", svc, step_repo, event_repo, coderecon)
    assert len(result.direction_changes) == 1
    assert "new_fn" in result.direction_changes[0]["symbols"]
