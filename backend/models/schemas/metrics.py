"""Pydantic schemas for the custom metrics and chat composer."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from backend.models.schemas.base import CamelModel

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class MetricsChatRequest(CamelModel):
    question: str = Field(max_length=10_000)
    conversation_id: str | None = Field(default=None, max_length=64)
    period_days: int | None = None


class MetricsChatMessageResponse(CamelModel):
    message_id: str
    narrative: str
    error: bool = False
    title: str | None = None
    viz: str | None = None
    viz_config: dict[str, Any] | None = None
    viz_data: list[Any] | None = None
    sql_queries: list[str] | None = None
    suggestion: str | None = None


class MetricsChatResponse(CamelModel):
    conversation_id: str
    message: MetricsChatMessageResponse


# ---------------------------------------------------------------------------
# Custom Metrics (pinned tiles)
# ---------------------------------------------------------------------------


class PinMetricRequest(CamelModel):
    name: str = Field(max_length=200)
    sql: str = Field(max_length=10_000)
    viz: str = Field(max_length=50)
    viz_config: dict[str, Any] | None = None
    period_relative: bool = True
    pin_dashboard: bool = True
    pin_job_panel: bool = False
    tile_size: str = "1x1"
    original_question: str | None = None
    explanation: str | None = None


class UpdateMetricRequest(CamelModel):
    name: str | None = None
    tile_size: str | None = None
    position: int | None = None
    pin_dashboard: bool | None = None
    pin_job_panel: bool | None = None
    alert_enabled: bool | None = None
    alert_op: str | None = None
    alert_value: float | None = None
    alert_severity: str | None = None
    alert_cooldown_hours: int | None = None


class CustomMetricResponse(CamelModel):
    id: str
    name: str
    sql: str
    viz: str
    viz_config: dict[str, Any] | None = None
    period_relative: bool = True
    pin_dashboard: bool = True
    pin_job_panel: bool = False
    alert_enabled: bool = False
    alert_op: str | None = None
    alert_value: float | None = None
    alert_severity: str | None = None
    alert_cooldown_hours: int | None = None
    tile_size: str = "1x1"
    position: int = 0
    original_question: str | None = None
    explanation: str | None = None
    created_at: str
    updated_at: str


class CustomMetricWithDataResponse(CamelModel):
    metric: CustomMetricResponse
    data: list[Any] = []
    error: str | None = None


class CustomMetricsListResponse(CamelModel):
    metrics: list[CustomMetricWithDataResponse]


class ConversationListResponse(CamelModel):
    conversations: list[dict[str, Any]]
