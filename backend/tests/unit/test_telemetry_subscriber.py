"""Tests for TraceForge-native telemetry subscriber persistence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from traceforge.types import EventMetadata, ToolMotivation

from backend.models.db import Base, JobRow
from backend.models.domain import JobState
from backend.models.events import EventKind, new_event
from backend.persistence.database import _set_sqlite_pragmas
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
from backend.services.events.event_bus import EventBus
from backend.services.events.telemetry_subscriber import TelemetrySubscriber

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Coroutine


class _Harness:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.pending: list[Coroutine[Any, Any, None]] = []
        self.subscriber = TelemetrySubscriber(
            session_factory=factory,
            schedule_write=self.pending.append,
            sdk="copilot",
        )

    async def handle_and_drain(self, event: Any) -> None:
        await self.subscriber.handle_event(event)
        while self.pending:
            coro = self.pending.pop(0)
            await coro


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        now = datetime.now(UTC)
        sess.add(
            JobRow(
                id="job-1",
                repo="/repos/test",
                prompt="Fix the bug",
                state=JobState.running,
                base_ref="main",
                permission_mode="full_auto",
                preset="autonomous",
                sdk="copilot",
                created_at=now,
                updated_at=now,
            )
        )
        await sess.commit()

    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_subscriber_persists_usage_tools_files_and_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harness = _Harness(session_factory)
    harness.subscriber.set_job_start_time("job-1", 100.0)

    events = [
        new_event("job-1", EventKind.message_user, {"content": "please update app"}),
        new_event("job-1", EventKind.message_assistant, {"content": "I'll edit it."}),
        new_event(
            "job-1",
            EventKind.telemetry_usage,
            {
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 10,
                "cache_write_tokens": 5,
                "cost_usd": 0.25,
                "duration_ms": 1234.9,
                "premium_requests": 2,
                "advance_turn": True,
            },
        ),
        new_event(
            "job-1",
            EventKind.tool_call_completed,
            {
                "tool_name": "write_file",
                "arguments": {"path": "src/app.py"},
                "result": "wrote file",
                "success": True,
                "tool_call_id": "tool-1",
            },
            metadata=EventMetadata(
                duration_ms=20.8,
                turn_id="turn-1",
                motivation=ToolMotivation(intent="Update app", reasoning="Need to change behavior"),
            ),
        ),
        new_event(
            "job-1",
            EventKind.tool_call_completed,
            {
                "tool_name": "bash",
                "arguments": {"command": "bad"},
                "result": "error: command not found",
                "success": False,
                "tool_call_id": "tool-2",
            },
            metadata=EventMetadata(duration_ms=30.2, turn_id="turn-1"),
        ),
    ]

    for event in events:
        await harness.handle_and_drain(event)

    async with session_factory() as session:
        summary = await TelemetrySummaryRepository(session).get("job-1")
        assert summary is not None
        assert summary["model"] == "gpt-4o"
        assert summary["input_tokens"] == 100
        assert summary["output_tokens"] == 50
        assert summary["cache_read_tokens"] == 10
        assert summary["cache_write_tokens"] == 5
        assert summary["total_cost_usd"] == pytest.approx(0.25)
        assert summary["premium_requests"] == pytest.approx(2)
        assert summary["llm_call_count"] == 1
        assert summary["total_llm_duration_ms"] == 1234
        assert summary["total_turns"] == 1
        assert summary["tool_call_count"] == 2
        assert summary["tool_failure_count"] == 1
        assert summary["total_tool_duration_ms"] == 50
        assert summary["file_write_count"] == 1
        assert summary["agent_messages"] == 1
        assert summary["operator_messages"] == 1

        spans = await TelemetrySpansRepository(session).list_for_job("job-1")
        assert [span["span_type"] for span in spans] == ["llm", "tool", "tool"]

        llm_span = spans[0]
        assert llm_span["name"] == "gpt-4o"
        assert float(llm_span["duration_ms"]) == pytest.approx(1234.9)
        assert llm_span["turn_number"] == 1
        assert llm_span["execution_phase"] == "agent_reasoning"
        assert llm_span["input_tokens"] == 100
        assert llm_span["output_tokens"] == 50
        assert llm_span["cache_read_tokens"] == 10
        assert llm_span["cache_write_tokens"] == 5
        assert llm_span["cost_usd"] == pytest.approx(0.25)
        assert llm_span["attrs"]["cost"] == pytest.approx(0.25)

        write_span = spans[1]
        assert write_span["name"] == "write_file"
        assert write_span["tool_category"] == "file_write"
        assert write_span["tool_target"] == "src/app.py"
        assert float(write_span["duration_ms"]) == pytest.approx(20.8)
        assert write_span["turn_number"] == 1
        assert write_span["tool_args_json"] == json.dumps({"path": "src/app.py"})
        assert write_span["result_size_bytes"] == len("wrote file")
        assert write_span["attrs"] == {"success": True}
        assert write_span["turn_id"] == "turn-1"
        assert write_span["motivation_summary"] == "Update app\nNeed to change behavior"
        assert write_span["preceding_context"] is not None
        preceding = json.loads(write_span["preceding_context"])
        assert preceding == [
            {"role": "operator", "content": "please update app"},
            {"role": "agent", "content": "I'll edit it."},
            {
                "role": "tool_call",
                "tool_name": "write_file",
                "tool_args": json.dumps({"path": "src/app.py"}),
                "tool_result": "wrote file",
            },
        ]

        failed_span = spans[2]
        assert failed_span["name"] == "bash"
        assert failed_span["tool_category"] == "shell"
        assert failed_span["tool_target"] == "bad"
        assert failed_span["attrs"] == {"success": False, "error_snippet": "error: command not found"}
        assert failed_span["result_size_bytes"] == len("error: command not found")
        assert failed_span["turn_id"] == "turn-1"

        access_rows = (
            await session.execute(
                text(
                    "SELECT job_id, file_path, access_type, turn_number "
                    "FROM job_file_access_log WHERE job_id = :job_id"
                ),
                {"job_id": "job-1"},
            )
        ).mappings().all()
        assert [dict(row) for row in access_rows] == [
            {
                "job_id": "job-1",
                "file_path": "src/app.py",
                "access_type": "write",
                "turn_number": 1,
            }
        ]


@pytest.mark.asyncio
async def test_subscribe_attaches_to_event_bus(session_factory: async_sessionmaker[AsyncSession]) -> None:
    harness = _Harness(session_factory)
    bus = EventBus()
    harness.subscriber.subscribe(bus)

    await bus.publish(new_event("job-1", EventKind.message_user, {"content": "hello"}))
    while harness.pending:
        await harness.pending.pop(0)

    async with session_factory() as session:
        summary = await TelemetrySummaryRepository(session).get("job-1")
        assert summary is not None
        assert summary["operator_messages"] == 1


@pytest.mark.asyncio
async def test_cleanup_removes_per_job_state(session_factory: async_sessionmaker[AsyncSession]) -> None:
    harness = _Harness(session_factory)
    await harness.handle_and_drain(new_event("job-1", EventKind.telemetry_usage, {"advance_turn": True}))
    assert harness.subscriber.get_turn("job-1") == 1

    harness.subscriber.cleanup("job-1")

    assert harness.subscriber.get_turn("job-1") == 0


def test_scheduler_can_create_tasks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    pending: list[asyncio.Task[None]] = []
    subscriber = TelemetrySubscriber(
        session_factory=session_factory,
        schedule_write=lambda coro: pending.append(asyncio.create_task(coro)),
        sdk="copilot",
    )
    assert subscriber.get_turn("job-1") == 0
