"""Tests for coverage/blast radius endpoints and service methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.job_artifacts import (
    _STRUCTURAL_CACHE,
    get_job_blast_radius,
    get_job_covering_tests,
)
from backend.models.api_schemas import (
    BlastRadiusResponse,
    CoveringTestCandidate,
    CoveringTestsResponse,
    StructuralChange,
)
from backend.models.domain import Job, JobState


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
        "prompt": "Fix the bug",
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
class FakeTestCandidate:
    test_id: str = "tests/test_foo.py::test_bar"
    source: str = "coverage"
    distance: int = 0
    confidence: float = 0.9
    reason: str = "direct coverage"


@dataclass
class FakeBlastRadiusResult:
    candidates: list[FakeTestCandidate] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)
    has_coverage_data: bool = True


@dataclass
class FakeCoveringTestsResult:
    tests_by_def: dict[str, list[FakeTestCandidate]] = field(default_factory=dict)
    file_path: str = ""


@dataclass
class FakeStructuralChange:
    path: str = "src/foo.py"
    kind: str = "function"
    name: str = "do_stuff"
    qualified_name: str | None = "module.do_stuff"
    change: str = "modified"
    structural_severity: str = ""
    behavior_change_risk: str = ""
    old_sig: str | None = None
    new_sig: str | None = None
    impact: Any = None
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
class FakeDiffResult:
    summary: str = "Modified 1 symbol"
    structural_changes: list[FakeStructuralChange] = field(default_factory=list)
    non_structural_changes: list[Any] = field(default_factory=list)
    breaking_summary: str | None = None
    files_analyzed: int = 0
    base_description: str = ""
    target_description: str = ""
    scope: Any = None


def _make_coderecon(*, available: bool = True) -> SimpleNamespace:
    svc = SimpleNamespace()
    svc.available = available
    svc.ensure_repo_indexed = AsyncMock(return_value="test-repo")
    svc.register_worktree = AsyncMock(return_value=None)
    svc.semantic_diff = AsyncMock(return_value=FakeDiffResult(
        structural_changes=[FakeStructuralChange(path="src/foo.py")]
    ))
    svc.blast_radius = AsyncMock(return_value=FakeBlastRadiusResult(
        candidates=[FakeTestCandidate()],
        coverage_gaps=["src/uncovered.py"],
        has_coverage_data=True,
    ))
    svc.covering_tests = AsyncMock(return_value={
        "module.do_stuff": [FakeTestCandidate()],
    })
    return svc


def _make_svc(job: Job | None = None) -> SimpleNamespace:
    svc = SimpleNamespace()
    svc.get_job = AsyncMock(return_value=job)
    return svc



# -- Covering Tests Endpoint ---------------------------------------------------


class TestGetJobCoveringTests:
    @pytest.mark.anyio
    async def test_returns_covering_tests(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()

        result = await get_job_covering_tests(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
            file_path="src/foo.py",
        )

        assert isinstance(result, CoveringTestsResponse)
        assert result.job_id == "job-1"
        assert result.file_path == "src/foo.py"
        assert result.available is True
        assert "module.do_stuff" in result.symbols
        assert len(result.symbols["module.do_stuff"]) == 1
        candidate = result.symbols["module.do_stuff"][0]
        assert candidate.test_id == "tests/test_foo.py::test_bar"
        assert candidate.source == "coverage"
        assert candidate.confidence == 0.9

    @pytest.mark.anyio
    async def test_unavailable_when_coderecon_disabled(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon(available=False)

        result = await get_job_covering_tests(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
            file_path="src/foo.py",
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_unavailable_when_no_worktree(self) -> None:
        job = _make_job(worktree_path=None)
        svc = _make_svc(job)
        coderecon = _make_coderecon()

        result = await get_job_covering_tests(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
            file_path="src/foo.py",
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_unavailable_on_service_error(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.covering_tests = AsyncMock(side_effect=RuntimeError("index corrupt"))

        result = await get_job_covering_tests(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
            file_path="src/foo.py",
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_empty_symbols_when_no_coverage(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.covering_tests = AsyncMock(return_value={})

        result = await get_job_covering_tests(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
            file_path="src/foo.py",
        )

        assert result.available is True
        assert result.symbols == {}

    @pytest.mark.anyio
    async def test_supports_typed_covering_tests_result(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.covering_tests = AsyncMock(return_value=FakeCoveringTestsResult(
            tests_by_def={"module.do_stuff": [FakeTestCandidate()]},
            file_path="src/foo.py",
        ))

        result = await get_job_covering_tests(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
            file_path="src/foo.py",
        )

        assert result.available is True
        assert "module.do_stuff" in result.symbols
        assert result.symbols["module.do_stuff"][0].test_id == "tests/test_foo.py::test_bar"


# -- Blast Radius Endpoint -----------------------------------------------------


class TestGetJobBlastRadius:
    @pytest.mark.anyio
    async def test_returns_blast_radius(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert isinstance(result, BlastRadiusResponse)
        assert result.job_id == "job-1"
        assert result.available is True
        assert result.has_coverage_data is True
        assert len(result.candidates) == 1
        assert result.candidates[0].test_id == "tests/test_foo.py::test_bar"
        assert result.candidates[0].source == "coverage"
        assert result.coverage_gaps == ["src/uncovered.py"]

    @pytest.mark.anyio
    async def test_unavailable_when_coderecon_disabled(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon(available=False)

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_unavailable_when_no_worktree(self) -> None:
        job = _make_job(worktree_path=None)
        svc = _make_svc(job)
        coderecon = _make_coderecon()

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_empty_when_no_changes(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.semantic_diff = AsyncMock(return_value=FakeDiffResult(structural_changes=[]))

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert result.available is True
        assert result.has_coverage_data is False
        assert result.candidates == []

    @pytest.mark.anyio
    async def test_unavailable_on_diff_error(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.semantic_diff = AsyncMock(side_effect=RuntimeError("parse failed"))

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_unavailable_on_blast_radius_error(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.blast_radius = AsyncMock(side_effect=RuntimeError("no coverage data"))

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert result.available is False

    @pytest.mark.anyio
    async def test_multiple_candidates(self) -> None:
        job = _make_job()
        svc = _make_svc(job)
        coderecon = _make_coderecon()
        coderecon.blast_radius = AsyncMock(return_value=FakeBlastRadiusResult(
            candidates=[
                FakeTestCandidate(test_id="tests/test_a.py::test_1", source="coverage", confidence=0.95),
                FakeTestCandidate(test_id="tests/test_b.py::test_2", source="reachability", confidence=0.6, distance=2),
                FakeTestCandidate(test_id="tests/test_c.py::test_3", source="graph", confidence=0.3, distance=3),
            ],
            coverage_gaps=[],
            has_coverage_data=True,
        ))

        result = await get_job_blast_radius(
            job_id="job-1",
            svc=svc,
            coderecon=coderecon,
        )

        assert len(result.candidates) == 3
        assert result.candidates[0].confidence == 0.95
        assert result.candidates[1].source == "reachability"
        assert result.candidates[2].distance == 3


# -- Schema Tests --------------------------------------------------------------


class TestCoverageConfidenceOnStructuralChange:
    def test_coverage_confidence_included_in_schema(self) -> None:
        change = StructuralChange(
            kind="modified",
            file="foo.py",
            coverage_confidence="high",
        )
        data = change.model_dump(mode="json", by_alias=True)
        assert data["coverageConfidence"] == "high"

    def test_coverage_confidence_defaults_to_none(self) -> None:
        change = StructuralChange(kind="added", file="bar.py")
        assert change.coverage_confidence is None

    def test_blast_radius_response_serialization(self) -> None:
        from backend.models.api_schemas import BlastRadiusCandidate, BlastRadiusResponse

        resp = BlastRadiusResponse(
            job_id="j-1",
            has_coverage_data=True,
            candidates=[
                BlastRadiusCandidate(
                    test_id="tests/t.py::test_x",
                    source="coverage",
                    distance=0,
                    confidence=0.95,
                    reason="direct hit",
                )
            ],
            coverage_gaps=["uncovered.py"],
        )
        data = resp.model_dump(mode="json", by_alias=True)
        assert data["hasCoverageData"] is True
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["testId"] == "tests/t.py::test_x"
        assert data["coverageGaps"] == ["uncovered.py"]

    def test_covering_tests_response_serialization(self) -> None:
        resp = CoveringTestsResponse(
            job_id="j-1",
            file_path="src/foo.py",
            symbols={
                "foo.bar": [
                    CoveringTestCandidate(
                        test_id="tests/t.py::test_bar",
                        source="coverage",
                        distance=0,
                        confidence=0.9,
                        reason="direct",
                    )
                ]
            },
        )
        data = resp.model_dump(mode="json", by_alias=True)
        assert data["filePath"] == "src/foo.py"
        assert "foo.bar" in data["symbols"]
        assert data["symbols"]["foo.bar"][0]["testId"] == "tests/t.py::test_bar"


# -- MCP Tool Tests ------------------------------------------------------------


class TestBlastRadiusTool:
    def test_blast_radius_in_standard_tier(self) -> None:
        from backend.services.coderecon.coderecon_tools import _resolve_tier

        standard = _resolve_tier("standard")
        assert "blast_radius" in standard

    def test_blast_radius_in_full_tier(self) -> None:
        from backend.services.coderecon.coderecon_tools import _resolve_tier

        full = _resolve_tier("full")
        assert "blast_radius" in full

    def test_blast_radius_not_in_minimal_tier(self) -> None:
        from backend.services.coderecon.coderecon_tools import _resolve_tier

        minimal = _resolve_tier("minimal")
        assert "blast_radius" not in minimal

    def test_blast_radius_tool_def_exists(self) -> None:
        from backend.services.coderecon.coderecon_tools import _TOOL_DEFS

        assert "blast_radius" in _TOOL_DEFS
        defn = _TOOL_DEFS["blast_radius"]
        assert "changed_files" in defn["schema"]["properties"]
        assert "changed_files" in defn["schema"]["required"]


# -- Service Method Tests (sync wrapping) -------------------------------------


class TestCodeReconServiceCoverageMethods:
    @pytest.mark.anyio
    async def test_ingest_coverage_delegates_to_kit(self) -> None:
        from unittest.mock import MagicMock

        from backend.services.coderecon.coderecon_service import CodeReconService

        service = CodeReconService()
        service._available = True

        fake_result = SimpleNamespace(
            facts_written=10, defs_covered=5, reachability_facts=3, calibrated_edges=2
        )
        mock_kit = MagicMock()
        mock_kit.ingest_coverage.return_value = fake_result
        service._kits["repo"] = mock_kit

        result = await service.ingest_coverage(
            "repo", "/path/to/coverage.json", worktree="main"
        )

        assert result.facts_written == 10
        mock_kit.ingest_coverage.assert_called_once_with(
            "/path/to/coverage.json",
            worktree="main",
            test_id=None,
            failed_tests=None,
            rebuild_reachability=True,
        )

    @pytest.mark.anyio
    async def test_blast_radius_delegates_to_kit(self) -> None:
        from unittest.mock import MagicMock

        from backend.services.coderecon.coderecon_service import CodeReconService

        service = CodeReconService()
        service._available = True

        fake_result = SimpleNamespace(
            candidates=[], coverage_gaps=["gap.py"], has_coverage_data=True
        )
        mock_kit = MagicMock()
        mock_kit.blast_radius.return_value = fake_result
        service._kits["repo"] = mock_kit

        result = await service.blast_radius("repo", ["src/a.py"], worktree="main", max_hops=3)

        assert result.has_coverage_data is True
        assert result.coverage_gaps == ["gap.py"]
        mock_kit.blast_radius.assert_called_once_with(
            ["src/a.py"], worktree="main", max_hops=3
        )

    @pytest.mark.anyio
    async def test_covering_tests_delegates_to_kit(self) -> None:
        from unittest.mock import MagicMock

        from backend.services.coderecon.coderecon_service import CodeReconService

        service = CodeReconService()
        service._available = True

        fake_candidate = SimpleNamespace(
            test_id="t.py::test_x", source="coverage", distance=0, confidence=0.9, reason="direct"
        )
        mock_kit = MagicMock()
        mock_kit.covering_tests.return_value = {"mod.fn": [fake_candidate]}
        service._kits["repo"] = mock_kit

        result = await service.covering_tests("repo", "src/mod.py", worktree="main")

        assert "mod.fn" in result
        assert result["mod.fn"][0].test_id == "t.py::test_x"
        mock_kit.covering_tests.assert_called_once_with("src/mod.py", worktree="main")

    @pytest.mark.anyio
    async def test_raises_when_unavailable(self) -> None:
        from backend.services.coderecon.coderecon_service import (
            CodeReconService,
            CodeReconUnavailableError,
        )

        service = CodeReconService()
        service._available = False

        with pytest.raises(CodeReconUnavailableError):
            await service.blast_radius("repo", ["a.py"])

    @pytest.mark.anyio
    async def test_raises_when_repo_not_indexed(self) -> None:
        from backend.services.coderecon.coderecon_service import (
            CodeReconService,
            RepoNotIndexedError,
        )

        service = CodeReconService()
        service._available = True
        # No kits registered

        with pytest.raises(RepoNotIndexedError):
            await service.covering_tests("nonexistent", "file.py")
