"""TrailService facade — thin orchestrator composing trail subsystem components."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from backend.config import TrailConfig
from backend.models.events import DomainEvent
from backend.persistence.trail_repo import TrailNodeRepository
from backend.services.trail.activity_tracker import ActivityTracker
from backend.services.trail.enricher import TrailEnricher
from backend.services.trail.models import TrailJobState
from backend.services.trail.node_builder import TrailNodeBuilder
from backend.services.trail.plan_manager import PlanManager
from backend.services.trail.query_service import TrailQueryService
from backend.services.trail.title_generator import TitleGenerator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.event_bus import EventBus
    from backend.services.sister_session import SisterSessionManager

log = structlog.get_logger()


class TrailService:
    """Thin facade composing trail subsystem components.

    Single entry point for the rest of the application — delegates to
    TrailNodeBuilder, PlanManager, ActivityTracker, TrailEnricher,
    TrailQueryService, and TitleGenerator.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        sister_sessions: SisterSessionManager | None = None,
        config: TrailConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._sister_sessions = sister_sessions
        self._config = config or TrailConfig()

        # Shared state
        self._job_state: dict[str, TrailJobState] = {}
        self._repo = TrailNodeRepository(session_factory)

        # Components
        self._title_gen = TitleGenerator()

        self._plan_manager = PlanManager(
            event_bus=event_bus,
            job_state=self._job_state,
            sister_sessions=sister_sessions,
        )

        self._activity_tracker = ActivityTracker(
            event_bus=event_bus,
            job_state=self._job_state,
            title_generator=self._title_gen,
            session_factory=session_factory,
        )

        self._node_builder = TrailNodeBuilder(
            session_factory=session_factory,
            job_state=self._job_state,
            repo=self._repo,
            plan_manager=self._plan_manager,
            activity_tracker=self._activity_tracker,
        )

        self._enricher = TrailEnricher(
            session_factory=session_factory,
            event_bus=event_bus,
            sister_sessions=sister_sessions,
            config=self._config,
            job_state=self._job_state,
        )

        self._query = TrailQueryService(session_factory)

    # ==================================================================
    # Event handling (delegate to node builder)
    # ==================================================================

    async def handle_event(self, event: DomainEvent) -> None:
        """Domain event subscriber."""
        await self._node_builder.handle_event(event)

    # ==================================================================
    # Data ingestion (delegate to plan manager)
    # ==================================================================

    async def start_tracking(self, job_id: str, prompt: str = "") -> None:
        """Initialize plan tracking for a job."""
        state = self._job_state.get(job_id)
        if state:
            state.job_prompt = prompt

    def stop_tracking(self, job_id: str) -> None:
        """No-op — cleanup happens in _on_job_terminal."""

    def cleanup(self, job_id: str) -> None:
        """Remove all in-memory state for a job."""
        self._job_state.pop(job_id, None)

    async def feed_transcript(
        self,
        job_id: str,
        role: str,
        content: str,
        tool_intent: str = "",
    ) -> None:
        """Buffer transcript data."""
        await self._plan_manager.feed_transcript(job_id, role, content, tool_intent)

    async def feed_tool_name(self, job_id: str, tool_name: str) -> None:
        """Track tool usage."""
        await self._plan_manager.feed_tool_name(job_id, tool_name)

    async def feed_native_plan(self, job_id: str, items: list[dict[str, str]]) -> None:
        """Create/update plan steps from the agent's native todo tool."""
        await self._plan_manager.feed_native_plan(job_id, items)

    # ==================================================================
    # Plan queries (delegate to plan manager)
    # ==================================================================

    def get_active_plan_step_id(self, job_id: str) -> str | None:
        return self._plan_manager.get_active_plan_step_id(job_id)

    def get_plan_steps(self, job_id: str) -> list[dict[str, str]]:
        return self._plan_manager.get_plan_steps(job_id)

    # ==================================================================
    # Finalization (delegate to plan manager)
    # ==================================================================

    async def finalize(self, job_id: str, succeeded: bool) -> None:
        """Finalize plan steps on job completion."""
        await self._plan_manager.finalize(job_id, succeeded)

    # ==================================================================
    # Enrichment drain (delegate to enricher)
    # ==================================================================

    async def drain_enrichment(self) -> int:
        return await self._enricher.drain_enrichment()

    async def drain_titles(self) -> int:
        return await self._enricher.drain_titles()

    async def drain_loop(self) -> None:
        await self._enricher.drain_loop()

    # ==================================================================
    # Query helpers (delegate to query service)
    # ==================================================================

    async def get_trail(
        self,
        job_id: str,
        *,
        kinds: list[str] | None = None,
        flat: bool = False,
        after_seq: int | None = None,
    ) -> dict:
        return await self._query.get_trail(
            job_id, kinds=kinds, flat=flat, after_seq=after_seq,
        )

    async def get_summary(self, job_id: str) -> dict:
        return await self._query.get_summary(job_id)
