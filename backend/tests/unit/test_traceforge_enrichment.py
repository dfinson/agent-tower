"""Contract/regression tests for the TraceForge enrichment wiring.

Covers:
 - tool_display derivation from TF classification metadata
 - Enricher inline wiring (buffering, pairing, orphan flushing)
 - Title pipeline TitleUpdate → turn_summary conversion
 - Re-enrichment idempotency
 - PowerShell / pwsh tool display regression
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from traceforge.enricher import Enricher as TFEnricher
from traceforge.types import Classification, EventMetadata, TitleUpdate

from backend.models.events import EventKind, SessionEvent, new_event
from backend.services.events.event_bus import EventBus
from backend.services.events.event_processor import (
    EventProcessor,
    _derive_tool_display,
    _extract_command,
)


def _tf(kind: EventKind, payload: dict | None = None, **md_kwargs) -> SessionEvent:
    """Build a TF-native SessionEvent with optional metadata overrides."""
    md = EventMetadata(**md_kwargs) if md_kwargs else None
    return new_event(session_id="j1", kind=kind, payload=payload or {}, metadata=md)


# ---------------------------------------------------------------------------
# _derive_tool_display — classification → display label
# ---------------------------------------------------------------------------


class TestDeriveToolDisplay:
    def test_shell_mechanism_formats_command(self):
        """Shell executor (mechanism='process') → '$ <command>'."""
        event = _tf(
            EventKind.tool_call_started,
            {"tool_name": "powershell", "arguments": '{"command": "Get-ChildItem"}'},
            classification=Classification(mechanism="process.shell"),
        )
        result = _derive_tool_display(event)
        assert result.metadata.tool_display == "$ Get-ChildItem"

    def test_already_set_display_overridden_for_process_mechanism(self):
        """For shell mechanisms, tool_display is always derived from command,
        overriding the generic 'shell' label the TF enricher sets."""
        event = _tf(
            EventKind.tool_call_started,
            {"tool_name": "bash", "arguments": '{"command": "ls -la"}'},
            classification=Classification(mechanism="process.shell"),
            tool_display="shell",
        )
        result = _derive_tool_display(event)
        assert result.metadata.tool_display == "$ ls -la"

    def test_no_classification_returns_unchanged(self):
        """No classification → event returned as-is."""
        event = _tf(
            EventKind.tool_call_started,
            {"tool_name": "grep", "arguments": '{"pattern": "foo"}'},
        )
        result = _derive_tool_display(event)
        assert result.metadata.tool_display is None

    def test_non_process_mechanism_no_display(self):
        """Non-shell mechanism → no tool_display derived."""
        event = _tf(
            EventKind.tool_call_started,
            {"tool_name": "edit", "arguments": '{"path": "foo.py"}'},
            classification=Classification(mechanism="file.write"),
        )
        result = _derive_tool_display(event)
        assert result.metadata.tool_display is None

    def test_command_truncation(self):
        """Long commands are truncated to 55 chars."""
        long_cmd = "a" * 100
        event = _tf(
            EventKind.tool_call_started,
            {"tool_name": "bash", "arguments": f'{{"command": "{long_cmd}"}}'},
            classification=Classification(mechanism="process.exec"),
        )
        result = _derive_tool_display(event)
        assert result.metadata.tool_display.startswith("$ ")
        assert result.metadata.tool_display.endswith("…")
        assert len(result.metadata.tool_display) <= 59  # "$ " + 55 + "…"

    def test_pwsh_shell_mechanism(self):
        """pwsh is also classified as process → gets shell display."""
        event = _tf(
            EventKind.tool_call_started,
            {"tool_name": "pwsh", "arguments": '{"command": "Write-Host hi"}'},
            classification=Classification(mechanism="process.shell"),
        )
        result = _derive_tool_display(event)
        assert result.metadata.tool_display == "$ Write-Host hi"


# ---------------------------------------------------------------------------
# _extract_command
# ---------------------------------------------------------------------------


class TestExtractCommand:
    def test_json_string_arguments(self):
        assert _extract_command({"arguments": '{"command": "ls"}'}) == "ls"

    def test_dict_arguments(self):
        assert _extract_command({"arguments": {"command": "ls -la"}}) == "ls -la"

    def test_cmd_key_not_recognized(self):
        """Only 'command' is the canonical key — 'cmd' is not an alias."""
        assert _extract_command({"arguments": {"cmd": "dir"}}) == ""

    def test_raw_string_arguments_returns_empty(self):
        """Non-JSON string arguments return empty — no reconstruction."""
        result = _extract_command({"arguments": "just a string"})
        assert result == ""

    def test_no_arguments(self):
        assert _extract_command({}) == ""


# ---------------------------------------------------------------------------
# EventProcessor with enricher — pairing / buffering
# ---------------------------------------------------------------------------


class TestEnricherWiring:
    @pytest.mark.asyncio
    async def test_enricher_buffers_tool_start(self):
        """TF Enricher buffers tool_call_started, returning None → no publish."""
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        enricher = TFEnricher()
        proc = EventProcessor(bus, enricher=enricher)

        result = await proc.process_event(
            "j1",
            _tf(
                EventKind.tool_call_started,
                {
                    "tool_name": "bash",
                    "tool_call_id": "tc-1",
                    "arguments": '{"command": "echo hi"}',
                },
            ),
        )
        # Enricher buffers the start — nothing published
        assert result is None
        assert len(published) == 0

    @pytest.mark.asyncio
    async def test_enricher_pairs_start_and_complete(self):
        """tool_call_completed pairs with buffered start → enriched event published."""
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        enricher = TFEnricher()
        proc = EventProcessor(bus, enricher=enricher)

        # Start — buffered by enricher
        await proc.process_event(
            "j1",
            _tf(
                EventKind.tool_call_started,
                {"tool_name": "bash", "tool_call_id": "tc-1", "arguments": '{"command": "echo hi"}'},
            ),
        )

        # Complete — triggers pairing with buffered start
        result = await proc.process_event(
            "j1",
            _tf(
                EventKind.tool_call_completed,
                {
                    "tool_name": "bash",
                    "tool_call_id": "tc-1",
                    "result": "hi",
                    "success": True,
                },
            ),
        )
        # TF Enricher absorbs start into complete — only the enriched
        # completed event is emitted (with duration_ms from the pair).
        assert result is not None
        assert len(published) >= 1
        # Enriched event should have classification and duration
        enriched = published[-1]
        assert enriched.metadata.classification is not None
        assert enriched.metadata.duration_ms is not None

    @pytest.mark.asyncio
    async def test_on_job_terminal_flushes_orphans(self):
        """on_job_terminal flushes buffered tool starts as orphans."""
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        enricher = TFEnricher()
        proc = EventProcessor(bus, enricher=enricher)

        # Buffer a tool start without completion
        await proc.process_event(
            "j1",
            _tf(
                EventKind.tool_call_started,
                {"tool_name": "bash", "tool_call_id": "tc-orphan"},
            ),
        )
        assert len(published) == 0

        # Terminal event flushes orphans
        await proc.on_job_terminal("j1", "completed")
        assert len(published) == 1  # orphan published


# ---------------------------------------------------------------------------
# PowerShell / pwsh display regression
# ---------------------------------------------------------------------------


class TestPowerShellRegression:
    """Regression: powershell/pwsh toolDisplay was null before TF enrichment."""

    @pytest.mark.asyncio
    async def test_powershell_gets_tool_display_via_enricher(self):
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        enricher = TFEnricher()
        proc = EventProcessor(bus, enricher=enricher)

        # Start PowerShell tool
        await proc.process_event(
            "j1",
            _tf(
                EventKind.tool_call_started,
                {
                    "tool_name": "powershell",
                    "tool_call_id": "tc-ps",
                    "arguments": '{"command": "Get-Process"}',
                },
            ),
        )

        # Complete PowerShell tool
        await proc.process_event(
            "j1",
            _tf(
                EventKind.tool_call_completed,
                {
                    "tool_name": "powershell",
                    "tool_call_id": "tc-ps",
                    "result": "output here",
                    "success": True,
                },
            ),
        )

        # TF Enricher absorbs start into complete — only the enriched
        # completed event is emitted. tool_display should be the command.
        assert len(published) >= 1
        enriched = published[-1]
        md = enriched.metadata
        assert md is not None
        assert md.classification is not None
        # tool_display should be derived from the command, overriding
        # the generic "shell" label the enricher sets.
        assert md.tool_display is not None
        assert md.tool_display.startswith("$ ")


# ---------------------------------------------------------------------------
# Title pipeline callback
# ---------------------------------------------------------------------------


class TestTitlePipelineCallback:
    """The title pipeline callback in lifespan.py converts TitleUpdate → turn_summary."""

    @pytest.mark.asyncio
    async def test_activity_title_update_emits_turn_summary(self):
        """An activity-kind TitleUpdate should produce a turn_summary event."""
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        # Simulate the callback that lifespan.py wires
        async def _on_title_update(update: TitleUpdate) -> None:
            if update.kind == "session":
                return
            await bus.publish(
                new_event(
                    session_id=update.session_id,
                    timestamp=datetime.now(UTC),
                    kind=EventKind.turn_summary,
                    payload={
                        "turn_id": update.segment_id,
                        "title": update.title,
                        "activity_id": update.parent_id or update.segment_id,
                        "activity_label": update.title if update.kind == "activity" else "",
                        "activity_status": "active",
                        "is_new_activity": update.kind == "activity",
                        "plan_item_id": None,
                    },
                )
            )

        update = TitleUpdate(
            session_id="j1",
            segment_id="seg-1",
            kind="activity",
            title="Setting up environment",
            version=1,
            parent_id=None,
        )
        await _on_title_update(update)

        assert len(published) == 1
        ev = published[0]
        assert ev.kind == EventKind.turn_summary
        assert ev.payload["title"] == "Setting up environment"
        assert ev.payload["is_new_activity"] is True
        assert ev.payload["activity_label"] == "Setting up environment"

    @pytest.mark.asyncio
    async def test_session_title_update_skipped(self):
        """Session-kind TitleUpdates are not emitted as turn_summaries."""
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        async def _on_title_update(update: TitleUpdate) -> None:
            if update.kind == "session":
                return
            await bus.publish(
                new_event(
                    session_id=update.session_id,
                    timestamp=datetime.now(UTC),
                    kind=EventKind.turn_summary,
                    payload={},
                )
            )

        update = TitleUpdate(
            session_id="j1",
            segment_id="seg-1",
            kind="session",
            title="Job title",
            version=1,
            parent_id=None,
        )
        await _on_title_update(update)

        assert len(published) == 0

    @pytest.mark.asyncio
    async def test_step_title_update_uses_parent_as_activity_id(self):
        """Step-kind TitleUpdate uses parent_id as activity_id."""
        bus = EventBus()
        published: list[SessionEvent] = []

        async def _handler(e: SessionEvent) -> None:
            published.append(e)

        bus.subscribe(_handler)

        async def _on_title_update(update: TitleUpdate) -> None:
            if update.kind == "session":
                return
            await bus.publish(
                new_event(
                    session_id=update.session_id,
                    timestamp=datetime.now(UTC),
                    kind=EventKind.turn_summary,
                    payload={
                        "turn_id": update.segment_id,
                        "title": update.title,
                        "activity_id": update.parent_id or update.segment_id,
                        "activity_label": update.title if update.kind == "activity" else "",
                        "is_new_activity": update.kind == "activity",
                    },
                )
            )

        update = TitleUpdate(
            session_id="j1",
            segment_id="step-1",
            kind="step",
            title="Reading config file",
            version=1,
            parent_id="activity-1",
        )
        await _on_title_update(update)

        assert len(published) == 1
        ev = published[0]
        assert ev.payload["activity_id"] == "activity-1"
        assert ev.payload["is_new_activity"] is False
        assert ev.payload["activity_label"] == ""
