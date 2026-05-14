"""Tests for trail.title_generator — turn title generation via LLM or fallback."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.services.trail.models import (
    Activity,
    PlanStep,
    TrailJobState,
)
from backend.services.trail.title_generator import TitleGenerator


def _state(**overrides: object) -> TrailJobState:
    defaults = dict(
        job_prompt="Fix all the bugs",
        plan_steps=[
            PlanStep(plan_step_id="ps-1", label="Setup", status="done", order=0),
            PlanStep(plan_step_id="ps-2", label="Implement", status="active", order=1),
        ],
        activities=[Activity(activity_id="a1", label="Fixing bugs", status="active")],
        activity_steps=[],
        plan_established=True,
        active_idx=1,
    )
    defaults.update(overrides)
    return TrailJobState(**defaults)


@pytest.fixture
def gen() -> TitleGenerator:
    return TitleGenerator()


# ---------------------------------------------------------------------------
# _build_now_line
# ---------------------------------------------------------------------------


class TestBuildNowLine:
    def test_agent_msg_first_line(self) -> None:
        result = TitleGenerator._build_now_line("First line\nSecond line", None, [])
        assert result == "First line"

    def test_agent_msg_truncated(self) -> None:
        long_msg = "A" * 200
        result = TitleGenerator._build_now_line(long_msg, None, [])
        assert len(result) == 120

    def test_preceding_context(self) -> None:
        result = TitleGenerator._build_now_line("", "intent: fix bug\n(details)", [])
        assert result == "intent: fix bug"

    def test_preceding_context_skips_parenthetical(self) -> None:
        result = TitleGenerator._build_now_line("", "(skip)\nactual content", [])
        assert result == "actual content"

    def test_tool_names_fallback(self) -> None:
        result = TitleGenerator._build_now_line("", None, ["read_file", "grep_search"])
        assert "read_file" in result
        assert "grep_search" in result

    def test_empty_fallback(self) -> None:
        result = TitleGenerator._build_now_line("", None, [])
        assert result == "(no message)"


# ---------------------------------------------------------------------------
# generate — success path
# ---------------------------------------------------------------------------


class TestGenerate:
    @pytest.mark.asyncio
    async def test_returns_none_without_sidecar(self, gen: TitleGenerator) -> None:
        state = _state()
        result = await gen.generate(
            "j1",
            state,
            None,
            agent_msg="hello",
            files_read=[],
            files_written=["a.py"],
            duration_ms=100,
            assigned_plan_step_id="ps-2",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_generation(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "title": "Fixed auth bug",
                "merge_with_previous": False,
                "boundary": "same",
                "label": None,
            }
        )

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="I fixed the auth bug",
            files_read=[],
            files_written=["auth.py"],
            duration_ms=500,
            assigned_plan_step_id="ps-2",
        )
        assert result is not None
        assert result.title == "Fixed auth bug"
        assert result.merge_with_previous is False
        assert result.new_activity is False
        assert result.activity_label is None

    @pytest.mark.asyncio
    async def test_boundary_shift(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "title": "Starting tests",
                "merge_with_previous": False,
                "boundary": "shift",
                "label": "Running tests",
            }
        )

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="Now running tests",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id="ps-2",
        )
        assert result is not None
        assert result.new_activity is True
        assert result.activity_label == "Running tests"

    @pytest.mark.asyncio
    async def test_merge_with_previous(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "title": "Retry build",
                "merge_with_previous": True,
                "boundary": "same",
                "label": None,
            }
        )

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="Retrying",
            files_read=[],
            files_written=[],
            duration_ms=50,
            assigned_plan_step_id="ps-2",
        )
        assert result is not None
        assert result.merge_with_previous is True

    @pytest.mark.asyncio
    async def test_empty_title_returns_none(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "title": "",
                "merge_with_previous": False,
                "boundary": "same",
            }
        )

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_none(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = "not json at all"

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        assert result is None
        assert state.sidecar_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_sidecar_error_returns_none(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.side_effect = OSError("connection failed")

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        assert result is None
        assert state.sidecar_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_code_fence_stripped(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = (
            '```json\n{"title": "Stripped", "merge_with_previous": false, "boundary": "same"}\n```'
        )

        state = _state()
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="hi",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        assert result is not None
        assert result.title == "Stripped"

    @pytest.mark.asyncio
    async def test_first_turn_no_activities(self, gen: TitleGenerator) -> None:
        sidecar = AsyncMock()
        sidecar.complete.return_value = json.dumps(
            {
                "title": "Initial setup",
                "merge_with_previous": False,
                "boundary": "same",
                "label": None,
            }
        )

        state = _state(activities=[], activity_steps=[])
        result = await gen.generate(
            "j1",
            state,
            sidecar,
            agent_msg="Starting work",
            files_read=[],
            files_written=[],
            duration_ms=100,
            assigned_plan_step_id=None,
        )
        assert result is not None
        assert result.title == "Initial setup"
