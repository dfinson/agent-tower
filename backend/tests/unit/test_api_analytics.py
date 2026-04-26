"""Tests for the redesigned analytics endpoints (scorecard, model-comparison, job-context)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.analytics_service import AnalyticsService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_analytics_svc(**overrides: object) -> AnalyticsService:
    """Build a mock AnalyticsService with sensible defaults."""
    svc = AsyncMock(spec=AnalyticsService)
    for name, value in overrides.items():
        getattr(svc, name).return_value = value
    return svc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scorecard_data() -> dict[str, object]:
    return {
        "budget": [
            {
                "sdk": "copilot",
                "total_cost_usd": 1.25,
                "job_count": 5,
                "avg_cost_per_job": 0.25,
                "avg_duration_ms": 120_000,
                "premium_requests": 42,
            },
        ],
        "activity": {
            "total_jobs": 5,
            "running": 1,
            "in_review": 1,
            "merged": 2,
            "pr_created": 0,
            "discarded": 1,
            "failed": 0,
            "cancelled": 0,
        },
        "quota_json": None,
        "cost_trend": [{"date": "2025-01-01", "cost": 0.5, "jobs": 2}],
    }


def _model_comparison_rows() -> list[dict[str, object]]:
    return [
        {
            "model": "claude-sonnet-4-20250514",
            "sdk": "claude",
            "job_count": 3,
            "total_cost_usd": 0.75,
            "avg_cost": 0.25,
            "avg_duration_ms": 90_000,
            "merged": 2,
            "pr_created": 0,
            "discarded": 1,
            "failed": 0,
            "cancelled": 0,
            "avg_verify_turns": 1.5,
            "verify_job_count": 2,
            "avg_diff_lines": 120,
            "cache_hit_rate": 0.35,
            "cost_per_minute": 0.17,
            "cost_per_turn": 0.05,
        }
    ]


def _job_context_data() -> dict[str, object]:
    return {
        "job": {
            "cost": 0.30,
            "durationMs": 100_000,
            "diffLinesAdded": 10,
            "diffLinesRemoved": 5,
            "sdk": "claude",
            "model": "claude-sonnet-4-20250514",
            "totalTurns": 12,
            "peakTurnCostUsd": 0.05,
            "avgTurnCostUsd": 0.025,
            "costFirstHalfUsd": 0.12,
            "costSecondHalfUsd": 0.18,
        },
        "repoAvg": {
            "jobCount": 8,
            "avgCost": 0.25,
            "avgDurationMs": 95_000,
            "avgDiffLines": 15,
        },
        "flags": [
            {"type": "turn_escalation", "message": "Cost escalation: 60% of spend in second half"},
        ],
    }


# ---------------------------------------------------------------------------
# Test scorecard endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scorecard_returns_data():
    """analytics_scorecard delegates to service and returns enriched dict."""
    svc = _mock_analytics_svc(scorecard=_scorecard_data())

    with patch("backend.config.load_config") as mock_load_config:
        mock_cfg = SimpleNamespace(
            telemetry=SimpleNamespace(daily_spend_limit_usd=25.0),
        )
        mock_load_config.return_value = mock_cfg

        from backend.api.analytics import analytics_scorecard

        result = await analytics_scorecard(svc=svc, period=7)

    assert result.activity.total_jobs == 5
    assert len(result.budget) > 0
    assert result.budget[0].sdk == "copilot"
    assert result.daily_spend_limit_usd == 25.0


# ---------------------------------------------------------------------------
# Test model comparison endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_comparison_returns_models():
    """analytics_model_comparison returns model rows with resolution data."""
    rows = _model_comparison_rows()
    svc = _mock_analytics_svc(model_comparison=rows)

    from backend.api.analytics import analytics_model_comparison

    result = await analytics_model_comparison(svc=svc, period=30, repo=None)

    assert result.period == 30
    assert result.repo is None
    assert len(result.models) == 1
    assert result.models[0].model == "claude-sonnet-4-20250514"
    assert result.models[0].merged == 2


@pytest.mark.asyncio
async def test_model_comparison_with_repo_filter():
    """analytics_model_comparison passes repo filter to the service method."""
    svc = _mock_analytics_svc(model_comparison=[])

    from backend.api.analytics import analytics_model_comparison

    result = await analytics_model_comparison(svc=svc, period=14, repo="/tmp/my-repo")

    svc.model_comparison.assert_awaited_once_with(period_days=14, repo="/tmp/my-repo")
    assert result.repo == "/tmp/my-repo"
    assert result.models == []


# ---------------------------------------------------------------------------
# Test job context endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_context_returns_job_data():
    """analytics_job_context returns job + repo avg + flags."""
    data = _job_context_data()
    svc = _mock_analytics_svc(job_context=data)

    from backend.api.analytics import analytics_job_context

    result = await analytics_job_context(job_id="j-1", svc=svc)

    assert result.job.cost == 0.30
    assert result.repo_avg is not None
    assert result.repo_avg.avg_cost == 0.25
    assert len(result.flags) == 1
    assert result.flags[0].type == "turn_escalation"


@pytest.mark.asyncio
async def test_job_context_returns_error_on_missing():
    """analytics_job_context raises HTTPException when telemetry is not found."""
    svc = _mock_analytics_svc(job_context=None)

    from fastapi import HTTPException

    from backend.api.analytics import analytics_job_context

    with pytest.raises(HTTPException) as exc_info:
        await analytics_job_context(job_id="nonexistent", svc=svc)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Test fleet_cost_drivers confidence annotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fleet_cost_drivers_confidence_annotation():
    """fleet_cost_drivers adds confidence:'approximate' to activity dimension rows."""
    mock_summary = [
        {"dimension": "activity", "bucket": "edit", "cost_usd": 0.10},
        {"dimension": "phase", "bucket": "agent_reasoning", "cost_usd": 0.50},
        {"dimension": "activity", "bucket": "read", "cost_usd": 0.05},
    ]
    svc = _mock_analytics_svc(fleet_cost_summary=mock_summary)

    from backend.api.analytics import fleet_cost_drivers

    result = await fleet_cost_drivers(svc=svc, period=30, dimension=None)

    summary = result.summary
    assert len(summary) == 3
    # Activity rows get "approximate"
    assert summary[0]["confidence"] == "approximate"
    assert summary[2]["confidence"] == "approximate"
    # Non-activity rows get "exact"
    assert summary[1]["confidence"] == "exact"
