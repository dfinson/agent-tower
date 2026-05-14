"""Tests for backend.services.steps.diff_service — StepDiffService helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.api_schemas import FileMotivation, HunkMotivation
from backend.services.steps.diff_service import StepDiffService

# ── Fake span / file / hunk objects ──


@dataclass
class FakeHunkLine:
    content: str
    type: str  # "addition" | "deletion" | "context"


@dataclass
class FakeHunk:
    lines: list[FakeHunkLine] = field(default_factory=list)


@dataclass
class FakeChangedFile:
    path: str
    hunks: list[FakeHunk] = field(default_factory=list)


# ── _extract_hunk_motivations ──


class TestExtractHunkMotivations:
    def test_no_edit_motivations(self):
        span = {"edit_motivations": None}
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}
        StepDiffService._extract_hunk_motivations(span, "a.py", [], file_mots, hunk_mots, "j1")
        assert hunk_mots == {}

    def test_empty_string_edit_motivations(self):
        span = {"edit_motivations": ""}
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}
        StepDiffService._extract_hunk_motivations(span, "a.py", [], file_mots, hunk_mots, "j1")
        assert hunk_mots == {}

    def test_invalid_json_edit_motivations(self):
        span = {"edit_motivations": "not json"}
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}
        StepDiffService._extract_hunk_motivations(span, "a.py", [], file_mots, hunk_mots, "j1")
        assert hunk_mots == {}

    def test_empty_list_edit_motivations(self):
        span = {"edit_motivations": "[]"}
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}
        StepDiffService._extract_hunk_motivations(span, "a.py", [], file_mots, hunk_mots, "j1")
        assert hunk_mots == {}

    def test_non_list_edit_motivations(self):
        span = {"edit_motivations": '{"a": 1}'}
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}
        StepDiffService._extract_hunk_motivations(span, "a.py", [], file_mots, hunk_mots, "j1")
        assert hunk_mots == {}

    def test_single_hunk_match(self):
        edit_mots = [{"summary": "Fixed bug\nDetails here", "edit_key": "k1"}]
        span = {
            "edit_motivations": json.dumps(edit_mots),
            "tool_args_json": None,
        }
        hunk = FakeHunk(lines=[FakeHunkLine("old line", "deletion")])
        changed_file = FakeChangedFile(path="a.py", hunks=[hunk])
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}

        StepDiffService._extract_hunk_motivations(span, "a.py", [changed_file], file_mots, hunk_mots, "j1")
        assert "a.py:0" in hunk_mots
        assert hunk_mots["a.py:0"].title == "Fixed bug"
        assert hunk_mots["a.py:0"].why == "Details here"
        assert hunk_mots["a.py:0"].edit_key == "k1"

    def test_no_matching_file(self):
        edit_mots = [{"summary": "Fixed bug", "edit_key": "k1"}]
        span = {
            "edit_motivations": json.dumps(edit_mots),
            "tool_args_json": None,
        }
        changed_file = FakeChangedFile(path="b.py", hunks=[FakeHunk()])
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}

        StepDiffService._extract_hunk_motivations(span, "a.py", [changed_file], file_mots, hunk_mots, "j1")
        # No match — should go to unmatched_edits IF file_motivations has entry
        assert "a.py:0" not in hunk_mots

    def test_multi_hunk_old_str_matching(self):
        """When multiple hunks exist and old_str is provided, best match by deletion content."""
        edit_mots = [{"summary": "Refactored method", "edit_key": "k2"}]
        tool_args = {"old_str": "def foo():\n    return 1"}
        span = {
            "edit_motivations": json.dumps(edit_mots),
            "tool_args_json": json.dumps(tool_args),
        }
        hunk0 = FakeHunk(
            lines=[
                FakeHunkLine("class Bar:", "context"),
                FakeHunkLine("pass", "deletion"),
            ]
        )
        hunk1 = FakeHunk(
            lines=[
                FakeHunkLine("def foo():", "deletion"),
                FakeHunkLine("    return 1", "deletion"),
            ]
        )
        changed_file = FakeChangedFile(path="a.py", hunks=[hunk0, hunk1])
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}

        StepDiffService._extract_hunk_motivations(span, "a.py", [changed_file], file_mots, hunk_mots, "j1")
        assert "a.py:1" in hunk_mots
        assert hunk_mots["a.py:1"].title == "Refactored method"

    def test_unmatched_goes_to_file_motivations(self):
        """When no hunk matches, result is appended to file-level unmatched_edits."""
        edit_mots = [{"summary": "Summary", "edit_key": "k3"}]
        tool_args = {"old_str": "totally different content"}
        span = {
            "edit_motivations": json.dumps(edit_mots),
            "tool_args_json": json.dumps(tool_args),
        }
        hunk0 = FakeHunk(lines=[FakeHunkLine("x", "deletion")])
        hunk1 = FakeHunk(lines=[FakeHunkLine("y", "deletion")])
        changed_file = FakeChangedFile(path="a.py", hunks=[hunk0, hunk1])
        file_mots: dict[str, FileMotivation] = {"a.py": FileMotivation(title="File change", why="")}
        hunk_mots: dict[str, HunkMotivation] = {}

        StepDiffService._extract_hunk_motivations(span, "a.py", [changed_file], file_mots, hunk_mots, "j1")
        assert len(hunk_mots) == 0
        assert len(file_mots["a.py"].unmatched_edits) == 1

    def test_old_string_alias(self):
        """old_str aliased as oldString in tool args."""
        edit_mots = [{"summary": "Fix", "edit_key": "k4"}]
        tool_args = {"oldString": "def foo():"}
        span = {
            "edit_motivations": json.dumps(edit_mots),
            "tool_args_json": json.dumps(tool_args),
        }
        hunk = FakeHunk(lines=[FakeHunkLine("def foo():", "deletion")])
        changed_file = FakeChangedFile(path="a.py", hunks=[hunk, FakeHunk()])
        file_mots: dict[str, FileMotivation] = {}
        hunk_mots: dict[str, HunkMotivation] = {}

        StepDiffService._extract_hunk_motivations(span, "a.py", [changed_file], file_mots, hunk_mots, "j1")
        assert "a.py:0" in hunk_mots


# ── _resolve_shas ──


def _make_step_diff_svc(
    *,
    events: list | None = None,
    step_row: object | None = None,
    step_by_turn: object | None = None,
) -> StepDiffService:
    """Build a StepDiffService with mocked dependencies."""
    job_svc = AsyncMock()
    job_svc.list_events_by_job = AsyncMock(return_value=events or [])

    step_repo = AsyncMock()
    step_repo.get = AsyncMock(return_value=step_row)
    step_repo.get_by_turn_id = AsyncMock(return_value=step_by_turn)

    git_service = AsyncMock()
    spans_repo = AsyncMock()

    return StepDiffService(
        job_svc=job_svc,
        step_repo=step_repo,
        git_service=git_service,
        spans_repo=spans_repo,
    )


@dataclass
class FakeEvent:
    payload: dict


@dataclass
class FakeStepRow:
    start_sha: str | None = None
    end_sha: str | None = None
    turn_id: str | None = None
    preceding_context: str | None = None


@pytest.mark.asyncio
class TestResolveShas:
    async def test_from_plan_step_events(self) -> None:
        ev = FakeEvent(
            payload={
                "plan_step_id": "ps-1",
                "start_sha": "aaa",
                "end_sha": "bbb",
            }
        )
        svc = _make_step_diff_svc(events=[ev])
        start, end, row = await svc._resolve_shas("j1", "ps-1")
        assert start == "aaa"
        assert end == "bbb"

    async def test_fallback_to_step_row(self) -> None:
        step_row = FakeStepRow(start_sha="ccc", end_sha="ddd")
        svc = _make_step_diff_svc(step_row=step_row)
        start, end, row = await svc._resolve_shas("j1", "step-1")
        assert start == "ccc"
        assert end == "ddd"
        assert row is step_row

    async def test_fallback_to_turn_id(self) -> None:
        step_by_turn = FakeStepRow(start_sha="eee", end_sha="fff")
        svc = _make_step_diff_svc(step_by_turn=step_by_turn)
        start, end, row = await svc._resolve_shas("j1", "turn-1")
        assert start == "eee"
        assert end == "fff"

    async def test_all_exhausted(self) -> None:
        svc = _make_step_diff_svc()
        start, end, row = await svc._resolve_shas("j1", "unknown")
        assert start is None
        assert end is None
        assert row is None

    async def test_event_no_sha_falls_through(self) -> None:
        """Event matches plan_step_id but has no SHAs — should fallback."""
        ev = FakeEvent(payload={"plan_step_id": "ps-1"})
        step_row = FakeStepRow(start_sha="ggg", end_sha="hhh")
        svc = _make_step_diff_svc(events=[ev], step_row=step_row)
        start, end, row = await svc._resolve_shas("j1", "ps-1")
        assert start == "ggg"
        assert end == "hhh"


# ── get_step_diff (public API) ──


@pytest.mark.asyncio
class TestGetStepDiff:
    async def test_identical_shas_returns_empty(self) -> None:
        ev = FakeEvent(
            payload={
                "plan_step_id": "ps-1",
                "start_sha": "same",
                "end_sha": "same",
            }
        )
        svc = _make_step_diff_svc(events=[ev])
        result = await svc.get_step_diff("j1", "ps-1")
        assert result.diff == ""
        assert result.files_changed == 0

    async def test_no_shas_returns_empty(self) -> None:
        svc = _make_step_diff_svc()
        result = await svc.get_step_diff("j1", "unknown")
        assert result.diff == ""
        assert result.files_changed == 0

    async def test_no_worktree_returns_empty(self) -> None:
        ev = FakeEvent(
            payload={
                "plan_step_id": "ps-1",
                "start_sha": "aaa",
                "end_sha": "bbb",
            }
        )
        svc = _make_step_diff_svc(events=[ev])
        job = MagicMock()
        job.worktree_path = None
        svc._job_svc.get_job = AsyncMock(return_value=job)
        result = await svc.get_step_diff("j1", "ps-1")
        assert result.diff == ""

    async def test_normal_diff(self) -> None:
        ev = FakeEvent(
            payload={
                "plan_step_id": "ps-1",
                "start_sha": "aaa",
                "end_sha": "bbb",
            }
        )
        svc = _make_step_diff_svc(events=[ev])

        job = MagicMock()
        job.worktree_path = "/tmp/work"
        svc._job_svc.get_job = AsyncMock(return_value=job)
        svc._git_service.diff_range = AsyncMock(return_value="diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n")
        svc._spans_repo.file_write_spans_for_step = AsyncMock(return_value=[])
        svc._spans_repo.motivated_spans_for_job = AsyncMock(return_value=[])

        result = await svc.get_step_diff("j1", "ps-1")
        assert result.files_changed == 1
        assert result.diff.startswith("diff --git")


# ── _build_motivations ──


@pytest.mark.asyncio
class TestBuildMotivations:
    async def test_with_preceding_context(self) -> None:
        svc = _make_step_diff_svc()
        step_row = FakeStepRow(preceding_context="User asked to refactor")
        svc._spans_repo.file_write_spans_for_step = AsyncMock(return_value=[])
        svc._spans_repo.motivated_spans_for_job = AsyncMock(return_value=[])

        ctx, file_mots, hunk_mots = await svc._build_motivations("j1", "step-1", step_row, [])
        assert ctx == "User asked to refactor"

    async def test_from_file_write_spans(self) -> None:
        svc = _make_step_diff_svc()
        step_row = FakeStepRow(turn_id="t1")
        spans = [
            {"tool_target": "main.py", "motivation_summary": "Refactored\nFor clarity"},
        ]
        svc._spans_repo.file_write_spans_for_step = AsyncMock(return_value=spans)

        ctx, file_mots, hunk_mots = await svc._build_motivations("j1", "step-1", step_row, [])
        assert "main.py" in file_mots
        assert file_mots["main.py"].title == "Refactored"
        assert file_mots["main.py"].why == "For clarity"

    async def test_fallback_to_all_spans(self) -> None:
        svc = _make_step_diff_svc()
        step_row = FakeStepRow(turn_id="t1")
        all_spans = [
            {"tool_target": "app.py", "motivation_summary": "Bug fix\nFixed null check"},
            {"tool_target": "other.py", "motivation_summary": "Unrelated"},
        ]
        changed_file = FakeChangedFile(path="app.py")
        svc._spans_repo.file_write_spans_for_step = AsyncMock(return_value=[])
        svc._spans_repo.motivated_spans_for_job = AsyncMock(return_value=all_spans)

        ctx, file_mots, hunk_mots = await svc._build_motivations("j1", "step-1", step_row, [changed_file])
        assert "app.py" in file_mots
        # "other.py" not in changed_paths, should be filtered out
        assert "other.py" not in file_mots

    async def test_no_spans_no_motivations(self) -> None:
        svc = _make_step_diff_svc()
        step_row = FakeStepRow()
        svc._spans_repo.file_write_spans_for_step = AsyncMock(return_value=[])
        svc._spans_repo.motivated_spans_for_job = AsyncMock(return_value=[])

        ctx, file_mots, hunk_mots = await svc._build_motivations("j1", "step-1", step_row, [])
        assert ctx is None
        assert file_mots == {}
        assert hunk_mots == {}

    async def test_malformed_span_graceful(self) -> None:
        svc = _make_step_diff_svc()
        step_row = FakeStepRow(turn_id="t1")
        # Span missing tool_target — should be skipped gracefully
        spans = [{"motivation_summary": "Something"}]
        svc._spans_repo.file_write_spans_for_step = AsyncMock(return_value=spans)

        ctx, file_mots, hunk_mots = await svc._build_motivations("j1", "step-1", step_row, [])
        assert file_mots == {}
