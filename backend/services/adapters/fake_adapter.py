"""Deterministic fake agent adapter used by CI E2E runs."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.models.events import EventKind
from backend.services.adapters.agent_adapter import CompletionResult
from backend.services.adapters.base_adapter import BaseAgentAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.models.domain import SessionConfig
    from backend.models.events import SessionEvent
    from backend.services.events.event_bus import EventBus
    from backend.services.job.approval_service import ApprovalService


class E2EFakeCopilotAdapter(BaseAgentAdapter):
    """Scripted adapter that produces a short, deterministic job lifecycle."""

    _source_framework = "copilot"

    def __init__(
        self,
        approval_service: ApprovalService | None = None,
        event_bus: EventBus | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        super().__init__(approval_service=approval_service, event_bus=event_bus, session_factory=session_factory)
        self._session_tasks: dict[str, asyncio.Task[None]] = {}

    async def create_session(self, config: SessionConfig) -> str:
        session_id = f"fake-{uuid.uuid4().hex}"
        self._queues[session_id] = asyncio.Queue()
        self._clients[session_id] = {"kind": config.session_kind}
        if config.job_id:
            self.set_job_id(session_id, config.job_id)
        if config.session_kind != "job":
            self.set_session_kind(session_id, config.session_kind)
        self._session_tasks[session_id] = asyncio.create_task(
            self._script_session(session_id, config),
            name=f"fake-copilot-{session_id[:8]}",
        )
        return session_id

    async def stream_events(self, session_id: str) -> AsyncIterator[SessionEvent]:
        queue = self._queues.get(session_id)
        if queue is None:
            return

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    async def send_message(self, session_id: str, message: str) -> None:
        queue = self._queues.get(session_id)
        if queue is None:
            return
        job_id = self._session_to_job.get(session_id, session_id)
        reply = self._make_assistant_reply(message)
        self._emit_tf(
            session_id,
            job_id,
            EventKind.message_assistant,
            self._transcript_payload(reply, seq=1),
        )
        self._emit_tf(
            session_id,
            job_id,
            EventKind.session_idle,
            {"timestamp": datetime.now(UTC).isoformat(), "reason": "follow-up complete"},
        )
        queue.put_nowait(None)

    async def abort_session(self, session_id: str) -> None:
        task = self._session_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
        queue = self._queues.get(session_id)
        if queue is not None:
            queue.put_nowait(None)

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_message: str | None = None,
        excluded_tools: list[str] | None = None,
    ) -> CompletionResult:
        text = self._complete_text(prompt)
        return CompletionResult(text=text, model=model or "fake-copilot")

    async def _script_session(self, session_id: str, config: SessionConfig) -> None:
        try:
            await asyncio.sleep(0.05)
            job_id = self._session_to_job.get(session_id, session_id)
            prompt = (config.prompt or "").strip()

            if prompt:
                self._emit_tf(
                    session_id,
                    job_id,
                    EventKind.message_user,
                    self._transcript_payload(prompt, seq=1),
                )

            self._emit_log_line(session_id, job_id, "CI fake adapter started")
            await asyncio.sleep(0.05)

            if config.session_kind == "planning":
                reply = self._make_plan_reply(prompt)
                self._emit_tf(
                    session_id,
                    job_id,
                    EventKind.message_assistant,
                    self._transcript_payload(reply, seq=2),
                )
                self._emit_tf(
                    session_id,
                    job_id,
                    EventKind.session_idle,
                    {"timestamp": datetime.now(UTC).isoformat(), "reason": "planning complete"},
                )
                return

            reply = self._make_assistant_reply(prompt)
            self._emit_tf(
                session_id,
                job_id,
                EventKind.message_assistant,
                self._transcript_payload(reply, seq=2),
            )
            self._emit_tf(
                session_id,
                job_id,
                EventKind.file_edited,
                {
                    "path": "README.md",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "hunks": [],
                },
            )
            self._emit_tf(
                session_id,
                job_id,
                EventKind.session_idle,
                {"timestamp": datetime.now(UTC).isoformat(), "reason": "session complete"},
            )
            self._emit_tf(
                session_id,
                job_id,
                EventKind.session_ended,
                {"timestamp": datetime.now(UTC).isoformat(), "reason": "session complete"},
            )
        finally:
            queue = self._queues.get(session_id)
            if queue is not None:
                queue.put_nowait(None)
            self._session_tasks.pop(session_id, None)

    @staticmethod
    def _transcript_payload(content: str, *, seq: int) -> dict[str, object]:
        return {
            "seq": seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "content": content,
            "title": None,
            "tool_name": None,
            "tool_call_id": None,
            "arguments": None,
            "result": None,
            "success": None,
        }

    @staticmethod
    def _complete_text(prompt: str) -> str:
        summary = E2EFakeCopilotAdapter._summarize_prompt(prompt)
        if summary:
            return summary
        return "CI safe fallback"

    @staticmethod
    def _make_assistant_reply(prompt: str) -> str:
        summary = E2EFakeCopilotAdapter._summarize_prompt(prompt)
        return f"Completed: {summary.lower()}" if summary else "Completed the requested work."

    @staticmethod
    def _make_plan_reply(prompt: str) -> str:
        summary = E2EFakeCopilotAdapter._summarize_prompt(prompt)
        return f"Plan: {summary}" if summary else "Plan: proceed with the requested changes."

    @staticmethod
    def _summarize_prompt(prompt: str) -> str:
        text = prompt.split("Task:", 1)[-1] if "Task:" in prompt else prompt
        words = re.findall(r"[A-Za-z0-9']+", text)
        filtered = [word for word in words if word.lower() not in {"the", "a", "an", "and", "or", "to", "of", "for"}]
        if not filtered:
            return ""
        return " ".join(word.capitalize() for word in filtered[:6])
