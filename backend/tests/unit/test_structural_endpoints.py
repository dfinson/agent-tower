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
from backend.api.job_artifacts import _STRUCTURAL_CACHE


# -- Fixtures ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the structural cache between tests."""
    _STRUCTURAL_CACHE.clear()


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
class FakeImpact:
    reference_count: int | None = None
    ref_tiers: Any = None
    reference_basis: str = ""
    referencing_files: list[str] | None = None
    importing_files: list[str] | None = None
    import_count: int | None = None
    affected_test_files: list[str] | None = None
    confidence: str = "high"
    visibility: str | None = None
    is_static: bool | None = None


@dataclass
class FakeRefTiers:
    proven: int = 0
    strong: int = 0
    anchored: int = 0
    unknown: int = 0


@dataclass
class FakeStructuralChange:
    """Mirrors coderecon.index.diff.models.StructuralChange for testing."""

    path: str = ""
    kind: str = ""
    name: str = ""
    qualified_name: str | None = None
    change: str = "modified"
    structural_severity: str = ""
    behavior_change_risk: str = ""
    old_sig: str | None = None
    new_sig: str | None = None
    impact: FakeImpact | None = None
    risk_basis: str | None = None
    classification_confidence: str = ""
    entity_id: str | None = None
    previous_entity_id: str | None = None
    old_name: str | None = None
    start_line: int = 0
    start_col: int = 0
    end_line: int = 0
    end_col: int = 0
    lines_changed: int | None = None
    nested_changes: list[Any] | None = None
    delta_tags: list[str] = field(default_factory=list)
    change_preview: str | None = None


@dataclass
class FakeCycleCluster:
    nodes: frozenset[str] = field(default_factory=frozenset)
    size: int = 0


@dataclass
class FakeCommunity:
    community_id: int = 0
    members: list[str] = field(default_factory=list)
    size: int = 0
    representative: str | None = None


@dataclass
class FakeDiffResult:
    summary: str = "Modified 3 symbols"
    structural_changes: list[FakeStructuralChange] = field(default_factory=list)
    non_structural_changes: list[Any] = field(default_factory=list)
    breaking_summary: str | None = None
    files_analyzed: int = 0
    base_description: str = ""
    target_description: str = ""
    scope: Any = None


@dataclass
class FakeCyclesResult:
    cycles: list[FakeCycleCluster] = field(default_factory=list)
    level: str = "file"
    node_count: int = 0
    edge_count: int = 0


@dataclass
class FakeCommunitiesResult:
    communities: list[FakeCommunity] = field(default_factory=list)
    level: str = "file"
    node_count: int = 0
    edge_count: int = 0


def _make_coderecon(*, available: bool = True) -> SimpleNamespace:
    svc = SimpleNamespace()
    svc.available = available
    svc.ensure_repo_indexed = AsyncMock(return_value="test-repo")
    svc.semantic_diff = AsyncMock(return_value=FakeDiffResult())
    svc.graph_cycles = AsyncMock(return_value=FakeCyclesResult())
    svc.graph_communities = AsyncMock(return_value=FakeCommunitiesResult())
    return svc


def _make_svc(job: Job | None = None) -> SimpleNamespace:
    svc = SimpleNamespace()
    svc.get_job = AsyncMock(return_value=job)
    return svc


# -- Unit tests for helper functions -------------------------------------------


class TestClassifyCategory:
    def test_removed_with_callers_is_breaking(self) -> None:
        c = FakeStructuralChange(change="removed", impact=FakeImpact(reference_count=3))
        assert _classify_category(c) == "breaking"

    def test_removed_no_callers_is_non_structural(self) -> None:
        c = FakeStructuralChange(change="removed", impact=FakeImpact(reference_count=0))
        assert _classify_category(c) == "non-structural"

    def test_modified_signature_change_is_breaking(self) -> None:
        c = FakeStructuralChange(change="modified", old_sig="def f(a)", new_sig="def f(a, b)")
        assert _classify_category(c) == "breaking"

    def test_modified_body_only(self) -> None:
        c = FakeStructuralChange(change="modified", old_sig="def f(a)", new_sig="def f(a)")
        assert _classify_category(c) == "body"

    def test_added_is_additive(self) -> None:
        c = FakeStructuralChange(change="added")
        assert _classify_category(c) == "additive"

    def test_moved_is_body(self) -> None:
        c = FakeStructuralChange(change="moved")
        assert _classify_category(c) == "body"

    def test_unknown_kind_is_non_structural(self) -> None:
        c = FakeStructuralChange(change="unknown")
        assert _classify_category(c) == "non-structural"


class TestTranslateRefTiers:
    def test_proven_maps_to_verified(self) -> None:
        assert _translate_ref_tiers(FakeRefTiers(proven=5)) == {"verified": 5}

    def test_strong_and_anchored_map_to_inferred(self) -> None:
        result = _translate_ref_tiers(FakeRefTiers(strong=2, anchored=3))
        assert result == {"inferred": 5}

    def test_unknown_maps_to_unverified(self) -> None:
        assert _translate_ref_tiers(FakeRefTiers(unknown=4)) == {"unverified": 4}

    def test_mixed_tiers(self) -> None:
        result = _translate_ref_tiers(FakeRefTiers(proven=1, unknown=2, anchored=3))
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
            FakeStructuralChange(
                change="modified",
                name="foo",
                qualified_name="foo",
                path="src/foo.py",
                change_preview="Changed signature",
                old_sig="def foo(a)",
                new_sig="def foo(a, b)",
                impact=FakeImpact(
                    reference_count=5,
                    ref_tiers=FakeRefTiers(proven=3, unknown=2),
                    affected_test_files=["tests/test_foo.py"],
                ),
                start_line=10,
                end_line=20,
            )
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
        raw = [FakeStructuralChange(
            change="removed",
            name="x",
            path="x.py",
            impact=FakeImpact(reference_count=10, ref_tiers=FakeRefTiers(proven=3)),
        )]
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
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    result = await get_job_structural_diff("job-1", svc, coderecon, step_repo)
    assert isinstance(result, StructuralDiffResponse)
    assert result.available is False


@pytest.mark.asyncio
async def test_structural_diff_no_worktree() -> None:
    """Returns available=False when job has no worktree."""
    job = _make_job(worktree_path=None)
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    result = await get_job_structural_diff("job-1", svc, coderecon, step_repo)
    assert result.available is False


@pytest.mark.asyncio
async def test_structural_diff_success() -> None:
    """Returns enriched structural changes with triage and confidence."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    coderecon.semantic_diff.return_value = FakeDiffResult(
        summary="3 changes",
        structural_changes=[
            FakeStructuralChange(change="added", name="new_fn", path="src/new.py"),
            FakeStructuralChange(change="modified", name="old_fn", path="src/old.py",
                                 old_sig="def old_fn()", new_sig="def old_fn()",
                                 impact=FakeImpact(reference_count=2, ref_tiers=FakeRefTiers(proven=2))),
        ],
    )
    result = await get_job_structural_diff("job-1", svc, coderecon, step_repo)
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
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[FakeStructuralChange(change="added", name="x", path="a.py")],
    )
    coderecon.graph_cycles.side_effect = [
        FakeCyclesResult(cycles=[FakeCycleCluster(nodes=frozenset(["a.py", "b.py"]), size=2)]),  # worktree
        FakeCyclesResult(cycles=[]),  # base (no cycles)
    ]
    result = await get_job_structural_diff("job-1", svc, coderecon, step_repo)
    assert result.merge_confidence == "LOW"


@pytest.mark.asyncio
async def test_impact_graph_error_returns_unavailable() -> None:
    """Impact graph returns available=False when impact() raises."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    coderecon.impact = AsyncMock(side_effect=Exception("unavailable"))
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    result = await get_impact_graph("job-1", "target_fn", svc, coderecon, step_repo)
    assert isinstance(result, ImpactGraphResponse)
    assert result.available is False


@pytest.mark.asyncio
async def test_impact_graph_not_available_when_coderecon_down() -> None:
    """Returns available=False when coderecon service is unavailable."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon(available=False)
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    result = await get_impact_graph("job-1", "target_fn", svc, coderecon, step_repo)
    assert result.available is False


@pytest.mark.asyncio
async def test_impact_graph_job_not_found() -> None:
    """Returns 404 when job doesn't exist."""
    svc = _make_svc(None)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    with pytest.raises(Exception, match="Job not found"):
        await get_impact_graph("nonexistent", "fn", svc, coderecon, step_repo)


@pytest.mark.asyncio
async def test_impact_graph_success() -> None:
    """Maps all three ImpactResult categories into references."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))

    fake_result = SimpleNamespace(
        definition_sites=[
            SimpleNamespace(symbol="login", file="src/auth.py", line=10),
        ],
        references=[
            SimpleNamespace(symbol="call_login", file="src/main.py", line=42, tier="proven"),
            SimpleNamespace(symbol="test_login", file="tests/test_auth.py", line=5, tier="strong"),
        ],
        import_sites=[
            SimpleNamespace(symbol="login", file="src/routes.py", line=1),
        ],
        total_references=4,
    )
    coderecon.impact = AsyncMock(return_value=fake_result)

    result = await get_impact_graph("job-1", "login", svc, coderecon, step_repo)
    assert result.available is True
    assert result.total_references == 4
    assert result.files_affected == 4
    assert len(result.references) == 4

    # definition_sites → tier="verified", raw_tier="definition"
    defn = result.references[0]
    assert defn.symbol == "login"
    assert defn.tier == "verified"
    assert defn.raw_tier == "definition"

    # references → tier mapped from SDK tier
    ref1 = result.references[1]
    assert ref1.tier == "verified"  # proven → verified
    assert ref1.raw_tier == "proven"

    ref2 = result.references[2]
    assert ref2.tier == "verified"  # strong → verified
    assert ref2.is_test is True

    # import_sites → tier="inferred"
    imp = result.references[3]
    assert imp.tier == "inferred"
    assert imp.raw_tier == "import"


@pytest.mark.asyncio
async def test_impact_graph_empty_result() -> None:
    """Handles empty ImpactResult gracefully."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    coderecon.impact = AsyncMock(return_value=SimpleNamespace(
        definition_sites=[], references=[], import_sites=[], total_references=0,
    ))
    result = await get_impact_graph("job-1", "unknown_fn", svc, coderecon, step_repo)
    assert result.available is True
    assert result.total_references == 0
    assert result.files_affected == 0
    assert result.references == []


@pytest.mark.asyncio
async def test_impact_graph_cached() -> None:
    """Second call for same symbol returns cached result without re-calling impact()."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    fake_step = SimpleNamespace(end_sha="abc123")
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[fake_step]))
    coderecon.impact = AsyncMock(return_value=SimpleNamespace(
        definition_sites=[], references=[], import_sites=[], total_references=0,
    ))
    r1 = await get_impact_graph("job-1", "fn", svc, coderecon, step_repo)
    r2 = await get_impact_graph("job-1", "fn", svc, coderecon, step_repo)
    assert r1 is r2
    coderecon.impact.assert_awaited_once()


@pytest.mark.asyncio
async def test_communities_success() -> None:
    """Groups changes by community with risk totals."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[
            FakeStructuralChange(change="modified", name="fn_a", path="src/auth/login.py"),
            FakeStructuralChange(change="added", name="fn_b", path="src/auth/signup.py"),
            FakeStructuralChange(change="modified", name="fn_c", path="src/db/query.py"),
        ],
    )
    coderecon.graph_communities.return_value = FakeCommunitiesResult(
        communities=[
            FakeCommunity(community_id=0, members=["src/auth/login.py", "src/auth/signup.py"], size=2, representative="auth"),
            FakeCommunity(community_id=1, members=["src/db/query.py", "src/db/models.py"], size=2, representative="database"),
        ]
    )
    result = await get_job_communities("job-1", svc, coderecon, step_repo)
    assert isinstance(result, CommunitiesResponse)
    assert len(result.communities) == 2
    names = {c.name for c in result.communities}
    assert "0" in names
    assert "1" in names
    assert result.unclustered == []


@pytest.mark.asyncio
async def test_communities_unclustered() -> None:
    """Files not in any community go to unclustered."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon()
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    coderecon.semantic_diff.return_value = FakeDiffResult(
        structural_changes=[
            FakeStructuralChange(change="added", name="orphan", path="misc/util.py"),
        ],
    )
    coderecon.graph_communities.return_value = FakeCommunitiesResult(
        communities=[FakeCommunity(community_id=0, members=["src/core.py"], size=1, representative="core")]
    )
    result = await get_job_communities("job-1", svc, coderecon, step_repo)
    assert len(result.communities) == 0
    assert len(result.unclustered) == 1


@pytest.mark.asyncio
async def test_review_story_unavailable() -> None:
    """Returns available=False when CodeRecon not available."""
    job = _make_job()
    svc = _make_svc(job)
    coderecon = _make_coderecon(available=False)
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    result = await get_review_story("job-1", svc, coderecon, step_repo)
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
            FakeStructuralChange(change="modified", name="auth_check", path="src/auth.py",
                                 old_sig="def auth_check()", new_sig="def auth_check(token)",
                                 impact=FakeImpact(reference_count=5, ref_tiers=FakeRefTiers(unknown=5))),
            FakeStructuralChange(change="added", name="new_helper", path="src/util.py"),
        ],
    )
    step_repo = SimpleNamespace(get_by_job=AsyncMock(return_value=[]))
    result = await get_review_story("job-1", svc, coderecon, step_repo)
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
        structural_changes=[FakeStructuralChange(change="added", name="x", path="a.py")],
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
                FakeStructuralChange(change="added", name="new_fn", path="a.py"),
            ])
        return FakeDiffResult(structural_changes=[
            FakeStructuralChange(change="modified", name="new_fn", path="a.py"),
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
