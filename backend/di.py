"""Dishka dependency-injection providers for CodePlane.

Defines the DI container wiring that replaces the previous hand-rolled
``app.state`` approach.  APP-scoped services are created once at startup
(via ``from_context``); REQUEST-scoped services are created per HTTP request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, NewType

import httpx
from dishka import Provider, Scope, from_context, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import CPLConfig
from backend.persistence.approval_repo import ApprovalRepository
from backend.persistence.cost_attribution_repo import CostAttributionRepository
from backend.persistence.event_repo import EventRepository
from backend.persistence.file_access_repo import FileAccessRepository
from backend.persistence.job_repo import JobRepository
from backend.persistence.latency_attribution_repo import LatencyAttributionRepository
from backend.persistence.sidecar_template_repo import SidecarTemplateRepository
from backend.persistence.step_repo import StepRepository
from backend.persistence.telemetry_spans_repo import TelemetrySpansRepository
from backend.persistence.telemetry_summary_repo import TelemetrySummaryRepository
from backend.services.adapters.platform_adapter import PlatformRegistry
from backend.services.analytics.analytics_service import AnalyticsService
from backend.services.analytics.model_pricing import ModelPricingService
from backend.services.analytics.telemetry_query_service import TelemetryQueryService
from backend.services.artifacts.artifact_service import ArtifactService
from backend.services.artifacts.diff_service import DiffService
from backend.services.coderecon.coderecon_service import CodeReconService
from backend.services.completers.naming_service import NamingService
from backend.services.completers.narrator_completer import NarratorCompleter
from backend.services.completers.voice_service import VoiceService
from backend.services.events.event_bus import EventBus
from backend.services.events.ingest_service import IngestService
from backend.services.events.sse_manager import SSEManager
from backend.services.git.git_service import GitService
from backend.services.job.approval_service import ApprovalService
from backend.services.job.job_service import JobService
from backend.services.memory.compacter import MemoryCompacter
from backend.services.merge_service import MergeService
from backend.services.runtime import RuntimeService
from backend.services.sharing.push_service import PushService
from backend.services.sharing.share_service import ShareService
from backend.services.sidecar.dispatcher import SidecarDispatcher
from backend.services.sidecar.session import SidecarSessionManager
from backend.services.sidecar.template_service import SidecarTemplateService
from backend.services.steps.diff_service import StepDiffService
from backend.services.story.service import StoryService
from backend.services.terminal.terminal_service import TerminalService
from backend.services.trail import TrailService
from backend.services.watcher.claude import ClaudeSessionStateWatcher

# NewType wrappers for plain values that need unique DI keys
CachedModelsBySdk = NewType("CachedModelsBySdk", dict[str, Any])
VoiceMaxBytes = NewType("VoiceMaxBytes", int)
PreviewHttpClient = NewType("PreviewHttpClient", httpx.AsyncClient)


class AppProvider(Provider):
    """APP-scoped services — created once during startup, live for the
    duration of the process.  Values are injected via the container's
    ``context`` dict at creation time."""

    scope = Scope.APP

    config = from_context(provides=CPLConfig)
    session_factory = from_context(provides=async_sessionmaker)
    event_bus = from_context(provides=EventBus)
    sse_manager = from_context(provides=SSEManager)
    approval_service = from_context(provides=ApprovalService)
    runtime_service = from_context(provides=RuntimeService)
    merge_service = from_context(provides=MergeService)
    platform_registry = from_context(provides=PlatformRegistry)
    sidecar_sessions = from_context(provides=SidecarSessionManager)
    sidecar_dispatcher = from_context(provides=SidecarDispatcher)
    voice_service = from_context(provides=VoiceService)
    cached_models = from_context(provides=CachedModelsBySdk)
    voice_max_bytes = from_context(provides=VoiceMaxBytes)
    push_service = from_context(provides=PushService)
    share_service = from_context(provides=ShareService)
    trail_service = from_context(provides=TrailService)
    terminal_service = from_context(provides=TerminalService)
    coderecon_service = from_context(provides=CodeReconService)
    narrator_completer = from_context(provides=NarratorCompleter)
    memory_compacter = from_context(provides=MemoryCompacter)
    ingest_service = from_context(provides=IngestService)
    model_pricing = from_context(provides=ModelPricingService)
    claude_session_watcher = from_context(provides=ClaudeSessionStateWatcher)

    @provide
    def git_service(self, config: CPLConfig) -> GitService:
        return GitService(config)

    @provide
    def diff_service(self, git_service: GitService, event_bus: EventBus) -> DiffService:
        return DiffService(git_service=git_service, event_bus=event_bus)

    @provide
    def story_service(
        self,
        narrator: NarratorCompleter,
        coderecon: CodeReconService,
        sf: async_sessionmaker[AsyncSession],
        model_pricing: ModelPricingService,
    ) -> StoryService:
        return StoryService(completer=narrator, coderecon=coderecon, session_factory=sf, model_pricing=model_pricing)

    @provide
    def step_repo(self, sf: async_sessionmaker[AsyncSession]) -> StepRepository:
        return StepRepository(sf)

    @provide
    async def preview_http_client(self) -> AsyncIterator[PreviewHttpClient]:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )
        try:
            yield PreviewHttpClient(client)
        finally:
            await client.aclose()


class RequestProvider(Provider):
    """REQUEST-scoped dependencies — created fresh per HTTP request."""

    scope = Scope.REQUEST

    @provide
    async def session(
        self,
        sf: async_sessionmaker[AsyncSession],
    ) -> AsyncIterator[AsyncSession]:
        from backend.persistence.database import get_write_lock

        async with sf() as session:
            try:
                yield session
                if session.dirty or session.new or session.deleted:
                    async with get_write_lock():
                        await session.commit()
            except Exception:
                await session.rollback()
                raise

    @provide
    def naming_service(self, sidecar_sessions: SidecarSessionManager) -> NamingService:
        return NamingService(sidecar_sessions)

    @provide
    def sidecar_template_repo(self, session: AsyncSession) -> SidecarTemplateRepository:
        return SidecarTemplateRepository(session)

    @provide
    def sidecar_template_service(
        self,
        repo: SidecarTemplateRepository,
        sidecar_sessions: SidecarSessionManager,
    ) -> SidecarTemplateService:
        return SidecarTemplateService(repo=repo, sidecar_sessions=sidecar_sessions)

    @provide
    def job_service(
        self,
        session: AsyncSession,
        config: CPLConfig,
        naming_service: NamingService,
    ) -> JobService:
        return JobService.from_session(
            session,
            config,
            naming_service=naming_service,
        )

    @provide
    def analytics_service(self, session: AsyncSession) -> AnalyticsService:
        return AnalyticsService(session)

    @provide
    def artifact_service(self, session: AsyncSession) -> ArtifactService:
        return ArtifactService.from_session(session)

    @provide
    def approval_repo(self, session: AsyncSession) -> ApprovalRepository:
        return ApprovalRepository(session)

    @provide
    def cost_attribution_repo(self, session: AsyncSession) -> CostAttributionRepository:
        return CostAttributionRepository(session)

    @provide
    def latency_attribution_repo(self, session: AsyncSession) -> LatencyAttributionRepository:
        return LatencyAttributionRepository(session)

    @provide
    def event_repo(self, session: AsyncSession) -> EventRepository:
        return EventRepository(session)

    @provide
    def file_access_repo(self, session: AsyncSession) -> FileAccessRepository:
        return FileAccessRepository(session)

    @provide
    def job_repo(self, session: AsyncSession) -> JobRepository:
        return JobRepository(session)

    @provide
    def telemetry_spans_repo(self, session: AsyncSession) -> TelemetrySpansRepository:
        return TelemetrySpansRepository(session)

    @provide
    def telemetry_summary_repo(self, session: AsyncSession) -> TelemetrySummaryRepository:
        return TelemetrySummaryRepository(session)

    @provide
    def telemetry_query_service(
        self,
        cost_repo: CostAttributionRepository,
        file_repo: FileAccessRepository,
        job_repo: JobRepository,
        latency_repo: LatencyAttributionRepository,
        spans_repo: TelemetrySpansRepository,
        summary_repo: TelemetrySummaryRepository,
    ) -> TelemetryQueryService:
        return TelemetryQueryService(cost_repo, file_repo, job_repo, latency_repo, spans_repo, summary_repo)

    @provide
    def step_diff_service(
        self,
        job_svc: JobService,
        step_repo: StepRepository,
        git_service: GitService,
        spans_repo: TelemetrySpansRepository,
    ) -> StepDiffService:
        return StepDiffService(job_svc, step_repo, git_service, spans_repo)
