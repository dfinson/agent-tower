"""Tests for backend.services.steps.diff_service — StepDiffService helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

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
