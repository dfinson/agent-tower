"""Tests for backend.services.completers.summarization_service — pure helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003
from typing import Any

from backend.services.completers.summarization_service import (
    _clean_transcript,
    _clean_transcript_from_trail,
    _extract_json,
    _format_transcript,
    build_followup_prompt,
    build_resume_prompt,
    extract_changed_files,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(role: str, content: str, *, kind: str = "transcript_entry") -> Any:
    """Build a minimal DomainEvent-like object."""
    from backend.models.events import new_event

    return new_event(
        session_id="j1", kind=kind, payload={"role": role, "content": content, "timestamp": "2025-01-01T00:00:00Z"}
    )


@dataclass
class _FakeNode:
    kind: str
    agent_message: str | None = None
    intent: str | None = None
    timestamp: datetime | None = None


# ---------------------------------------------------------------------------
# _clean_transcript
# ---------------------------------------------------------------------------


class TestCleanTranscript:
    def test_filters_empty_content(self):
        events = [_make_event("agent", ""), _make_event("agent", "hello")]
        result = _clean_transcript(events)
        assert len(result) == 1
        assert result[0]["content"] == "hello"

    def test_filters_non_agent_roles(self):
        events = [_make_event("system", "init"), _make_event("agent", "hi")]
        result = _clean_transcript(events)
        assert len(result) == 1

    def test_normalizes_user_to_operator(self):
        events = [_make_event("user", "do this")]
        result = _clean_transcript(events)
        assert result[0]["role"] == "operator"

    def test_deduplicates_consecutive(self):
        events = [_make_event("agent", "same"), _make_event("agent", "same")]
        result = _clean_transcript(events)
        assert len(result) == 1

    def test_deduplicates_globally(self):
        events = [
            _make_event("agent", "hello"),
            _make_event("operator", "cmd"),
            _make_event("agent", "hello"),
        ]
        result = _clean_transcript(events)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _clean_transcript_from_trail
# ---------------------------------------------------------------------------


class TestCleanTranscriptFromTrail:
    def test_agent_step_nodes(self):
        nodes = [
            _FakeNode(kind="modify", agent_message="Editing file"),
            _FakeNode(kind="shell", agent_message="Running tests"),
        ]
        result = _clean_transcript_from_trail(nodes)
        assert len(result) == 2
        assert result[0]["role"] == "agent"

    def test_request_nodes_as_operator(self):
        nodes = [_FakeNode(kind="request", intent="Approve this change")]
        result = _clean_transcript_from_trail(nodes)
        assert result[0]["role"] == "operator"

    def test_empty_content_skipped(self):
        nodes = [_FakeNode(kind="modify", agent_message=""), _FakeNode(kind="modify", agent_message="ok")]
        result = _clean_transcript_from_trail(nodes)
        assert len(result) == 1

    def test_deduplicates(self):
        nodes = [
            _FakeNode(kind="modify", agent_message="same"),
            _FakeNode(kind="modify", agent_message="same"),
        ]
        result = _clean_transcript_from_trail(nodes)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _format_transcript
# ---------------------------------------------------------------------------


class TestFormatTranscript:
    def test_formats_turns(self):
        turns = [
            {"role": "agent", "content": "hello", "timestamp": ""},
            {"role": "operator", "content": "world", "timestamp": ""},
        ]
        result = _format_transcript(turns)
        assert "[1] AGENT: hello" in result
        assert "[2] OPERATOR: world" in result

    def test_empty(self):
        assert _format_transcript([]) == "(no transcript recorded)"


# ---------------------------------------------------------------------------
# extract_changed_files
# ---------------------------------------------------------------------------


class TestExtractChangedFiles:
    def test_extracts_paths(self):
        events = [
            _make_event("agent", "", kind="diff_updated"),
        ]
        events[0].payload["changed_files"] = [{"path": "a.py"}, {"new_path": "b.py"}]
        result = extract_changed_files(events)
        assert "a.py" in result
        assert "b.py" in result

    def test_deduplicates(self):
        ev = _make_event("agent", "", kind="diff_updated")
        ev.payload["changed_files"] = [{"path": "a.py"}, {"path": "a.py"}]
        result = extract_changed_files([ev])
        assert len(result) == 1

    def test_empty_events(self):
        assert extract_changed_files([]) == []


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_valid_json(self):
        raw = '{"key": "value"}'
        result = _extract_json(raw, "j1", "task", 1)
        assert json.loads(result)["key"] == "value"

    def test_markdown_fences_stripped(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _extract_json(raw, "j1", "task", 1)
        assert json.loads(result)["key"] == "value"

    def test_json_embedded_in_text(self):
        raw = 'Here is the result: {"key": "value"} end'
        result = _extract_json(raw, "j1", "task", 1)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_fallback_on_invalid(self):
        raw = "not json at all"
        result = _extract_json(raw, "j1", "task", 1)
        parsed = json.loads(result)
        assert parsed["summarized"] is False
        assert "not json at all" in parsed["raw_response"]


# ---------------------------------------------------------------------------
# build_resume_prompt
# ---------------------------------------------------------------------------


class TestBuildResumePrompt:
    def test_contains_sections(self):
        result = build_resume_prompt(
            summary_text="Did stuff",
            changed_files=["a.py", "b.py"],
            instruction="Continue",
            session_number=2,
            job_id="j1",
            original_task="Build feature",
        )
        assert "RESUMED SESSION" in result
        assert "Build feature" in result
        assert "Did stuff" in result
        assert "a.py" in result
        assert "Continue" in result

    def test_no_summary(self):
        result = build_resume_prompt(
            summary_text=None,
            changed_files=[],
            instruction="Go",
            session_number=1,
            job_id="j1",
            original_task="Task",
        )
        assert "no summary available" in result

    def test_no_files(self):
        result = build_resume_prompt(
            summary_text="sum",
            changed_files=[],
            instruction="Go",
            session_number=1,
            job_id="j1",
            original_task="Task",
        )
        assert "no file changes" in result


# ---------------------------------------------------------------------------
# build_followup_prompt
# ---------------------------------------------------------------------------


class TestBuildFollowupPrompt:
    def test_contains_sections(self):
        result = build_followup_prompt(
            summary_text="Did stuff",
            changed_files=["a.py"],
            instruction="Next step",
            parent_job_id="j0",
            original_task="Build feature",
        )
        assert "FOLLOW-UP JOB" in result
        assert "Build feature" in result
        assert "Did stuff" in result
        assert "a.py" in result
        assert "Next step" in result

    def test_no_summary(self):
        result = build_followup_prompt(
            summary_text=None,
            changed_files=[],
            instruction="Go",
            parent_job_id="j0",
            original_task="Task",
        )
        assert "no summary available" in result
