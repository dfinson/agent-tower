"""IngestService — operator messaging bridge for imported CLI sessions.

Routes operator messages and abort commands to the appropriate channel:
- claude_cli → ClaudeSessionStateWatcher (pending message queue for Stop hook)
- copilot_cli → SessionStateWatcher (Copilot steer API)

Session data ingestion for both SDKs is handled entirely by their respective
SessionStateWatcher implementations via file-tailing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from backend.models.domain import Job, JobSource

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.watcher.claude import ClaudeSessionStateWatcher
    from backend.services.copilot_steer import CopilotSteerClient
    from backend.services.watcher.copilot import SessionStateWatcher

log = structlog.get_logger()


class IngestService:
    """Routes operator messages to the appropriate session watcher."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        steer_client: CopilotSteerClient | None = None,
        claude_watcher: ClaudeSessionStateWatcher | None = None,
        session_state_watcher: SessionStateWatcher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._steer = steer_client
        self._claude_watcher = claude_watcher
        self._session_state_watcher = session_state_watcher

    async def send_operator_message(self, job_id: str, message: str) -> None:
        """Queue an operator message for delivery to the agent."""
        job = await self._get_job(job_id)
        if not job:
            return

        if job.source == JobSource.claude_cli:
            if self._claude_watcher:
                await self._claude_watcher.send_operator_message(job_id, message)
            else:
                log.warning("operator_message_no_claude_watcher", job_id=job_id)
        elif job.source == JobSource.copilot_cli:
            if self._session_state_watcher:
                ext_id = job.external_session_id
                if ext_id:
                    await self._session_state_watcher.send_message(ext_id, message)
                    log.info("operator_message_sent_copilot", job_id=job_id)
            elif self._steer:
                ext_id = job.external_session_id
                if ext_id:
                    await self._steer.send_message(ext_id, message)
                    log.info("operator_message_sent_copilot", job_id=job_id)
        else:
            log.warning("operator_message_no_channel", job_id=job_id, source=job.source)

    async def abort_session(self, job_id: str) -> None:
        """Abort the external session.

        The caller (cancel_job endpoint) already transitions job state to
        canceled. This method only handles external agent communication.
        """
        job = await self._get_job(job_id)
        if not job:
            return

        if job.source == JobSource.claude_cli:
            if self._claude_watcher:
                await self._claude_watcher.abort_session(job_id)
        elif job.source == JobSource.copilot_cli:
            if self._session_state_watcher:
                ext_id = job.external_session_id
                if ext_id:
                    await self._session_state_watcher.abort_session(ext_id)
            elif self._steer:
                ext_id = job.external_session_id
                if ext_id:
                    await self._steer.abort(ext_id)

    async def _get_job(self, job_id: str) -> Job | None:
        async with self._session_factory() as session:
            from backend.persistence.job_repo import JobRepository

            repo = JobRepository(session)
            return await repo.get(job_id)
