"""API routes for the chat-driven metrics composer and custom metrics."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.api_schemas import (
    ConversationListResponse,
    CustomMetricResponse,
    CustomMetricsListResponse,
    CustomMetricWithDataResponse,
    MetricsChatRequest,
    MetricsChatResponse,
    MetricsChatMessageResponse,
    PinMetricRequest,
    UpdateMetricRequest,
)
from backend.persistence.custom_metrics_repo import (
    CustomMetricsRepository,
    MetricsChatRepository,
)
from backend.services.metrics.chat_service import MetricsChatService, clear_conversation
from backend.services.metrics.query_executor import (
    QueryValidationError,
    execute_query,
    validate_query,
)
from backend.services.sidecar.session import SidecarSessionManager

log = structlog.get_logger()

router = APIRouter(prefix="/metrics", route_class=DishkaRoute, tags=["metrics"])

# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=MetricsChatResponse)
async def chat_ask(
    body: MetricsChatRequest,
    sidecar: FromDishka[SidecarSessionManager],
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> MetricsChatResponse:
    """Send a natural language question about telemetry data."""
    conversation_id = body.conversation_id or uuid.uuid4().hex[:16]

    chat_repo = MetricsChatRepository(sf)
    chat_service = MetricsChatService(sidecar=sidecar, session_factory=sf)

    result = await chat_service.ask(
        body.question,
        conversation_id,
        period_days=body.period_days,
    )

    # Persist condensed exchange
    await chat_repo.save_exchange(
        conversation_id=conversation_id,
        question=body.question,
        answer_summary=result.condensed_summary(),
        viz_data_json=json.dumps(result.viz_data) if result.viz_data else None,
        sql_queries_json=json.dumps(result.sql_queries) if result.sql_queries else None,
    )

    return MetricsChatResponse(
        conversation_id=conversation_id,
        message=MetricsChatMessageResponse(**result.to_dict()),
    )


@router.get("/chat/conversations", response_model=ConversationListResponse)
async def list_conversations(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> ConversationListResponse:
    """List recent chat conversations."""
    repo = MetricsChatRepository(sf)
    convs = await repo.list_conversations()
    return ConversationListResponse(conversations=convs)


@router.delete("/chat/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    """Clear an in-memory conversation session."""
    clear_conversation(conversation_id)


# ---------------------------------------------------------------------------
# Custom metrics (pinned tiles) endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=CustomMetricsListResponse)
async def list_custom_metrics(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> CustomMetricsListResponse:
    """List all pinned custom metrics with their current data."""
    repo = CustomMetricsRepository(sf)
    metrics = await repo.list_all()

    async def _eval(m: dict[str, Any]) -> CustomMetricWithDataResponse:
        data: list[Any] = []
        error: str | None = None
        try:
            data = await execute_query(sf, m["sql"], timeout_seconds=30.0)
        except QueryValidationError as exc:
            error = str(exc)
        except Exception as exc:
            error = f"Unexpected error: {exc}"
        return CustomMetricWithDataResponse(
            metric=_row_to_metric_response(m), data=data, error=error,
        )

    results = await asyncio.gather(*[_eval(m) for m in metrics])
    return CustomMetricsListResponse(metrics=list(results))


@router.post("", response_model=CustomMetricResponse, status_code=201)
async def pin_metric(
    body: PinMetricRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> CustomMetricResponse:
    """Pin a metric as a dashboard tile."""
    # Validate SQL before persisting — reject bad queries early
    try:
        validate_query(body.sql)
    except QueryValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid SQL: {exc}") from exc

    metric_id = uuid.uuid4().hex[:16]

    repo = CustomMetricsRepository(sf)
    data = {
        "id": metric_id,
        "name": body.name,
        "sql": body.sql,
        "viz": body.viz,
        "viz_config_json": json.dumps(body.viz_config) if body.viz_config else None,
        "period_relative": 1 if body.period_relative else 0,
        "pin_dashboard": 1 if body.pin_dashboard else 0,
        "pin_job_panel": 1 if body.pin_job_panel else 0,
        "tile_size": body.tile_size,
        "original_question": body.original_question,
        "explanation": body.explanation,
    }
    await repo.create(data)

    saved = await repo.get(metric_id)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save metric")

    return _row_to_metric_response(saved)


@router.patch("/{metric_id}", response_model=CustomMetricResponse)
async def update_metric(
    metric_id: str,
    body: UpdateMetricRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> CustomMetricResponse:
    """Update a pinned metric's configuration."""
    repo = CustomMetricsRepository(sf)
    existing = await repo.get(metric_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Metric not found")

    updates: dict[str, Any] = {}
    for field_name in body.model_fields_set:
        val = getattr(body, field_name)
        # Convert booleans to int for SQLite
        if isinstance(val, bool):
            val = 1 if val else 0
        updates[field_name] = val

    if updates:
        await repo.update(metric_id, updates)

    saved = await repo.get(metric_id)
    return _row_to_metric_response(saved)  # type: ignore[arg-type]


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> None:
    """Delete a pinned metric."""
    repo = CustomMetricsRepository(sf)
    existing = await repo.get(metric_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Metric not found")
    await repo.delete(metric_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_metric_response(row: dict[str, Any]) -> CustomMetricResponse:
    viz_config = None
    if row.get("viz_config_json"):
        try:
            viz_config = json.loads(row["viz_config_json"])
        except (json.JSONDecodeError, TypeError):
            viz_config = {}

    return CustomMetricResponse(
        id=row["id"],
        name=row["name"],
        sql=row["sql"],
        viz=row["viz"],
        viz_config=viz_config,
        period_relative=bool(row.get("period_relative", 1)),
        pin_dashboard=bool(row.get("pin_dashboard", 1)),
        pin_job_panel=bool(row.get("pin_job_panel", 0)),
        alert_enabled=bool(row.get("alert_enabled", 0)),
        alert_op=row.get("alert_op"),
        alert_value=row.get("alert_value"),
        alert_severity=row.get("alert_severity"),
        alert_cooldown_hours=row.get("alert_cooldown_hours"),
        tile_size=row.get("tile_size", "1x1"),
        position=row.get("position", 0),
        original_question=row.get("original_question"),
        explanation=row.get("explanation"),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )
