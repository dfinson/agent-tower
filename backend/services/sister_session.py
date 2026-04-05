"""Per-job dedicated utility sessions ("sister sessions").

SDK-agnostic — delegates all LLM calls to the ``AgentAdapterInterface``
obtained from the ``AdapterRegistry``.  Each job owns exactly one session;
no shared checkout contention.

A **standby pool** of pre-created ``SisterSession`` wrappers is kept ready
so ``warm()``, ``adopt()``, and ``create_for_job()`` can hand off a session
instantly.  The pool auto-refills in a background task.

Lifecycle:
1. **Pre-warm** — frontend opens the new-job panel → ``warm()`` returns a
   token linked to a session from the standby pool.  If the user navigates
   away, ``release()`` recycles it back.
2. **Adopt** — ``POST /api/jobs`` passes the token → ``adopt(token, job_id)``
   binds that session to the job.
3. **Create-for-job** — resume path (no pre-warm) → ``create_for_job()``
   pops a pooled session (or creates one on the spot).
4. **Use** — ``get(job_id)`` returns the session for direct calls.
5. **Close** — terminal state → ``close_job(job_id)`` removes the binding.

Also provides ``complete()`` for callers without a job context (naming,
terminal ask, MCP).
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from collections import deque
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.agent_adapter import AgentAdapterInterface

log = structlog.get_logger()

# Default model for utility work — cheap and fast
DEFAULT_UTILITY_MODEL = "gpt-4o-mini"

# Orphan expiry — warm sessions not adopted within this window are closed
_ORPHAN_EXPIRY_S = 300.0  # 5 minutes
_ORPHAN_CHECK_INTERVAL_S = 30.0

# Standby pool — keep this many sessions ready to hand off instantly
_STANDBY_POOL_SIZE = 2

# Retry count for one-shot callers
_TIMEOUT_RETRIES = 1

# System prompt prepended on the first call per session
_UTILITY_SYSTEM_PROMPT = """\
You are a concise utility assistant embedded in a coding task management system
called CodePlane. Your sole purpose is to generate short metadata: titles, branch
names, progress summaries, commit messages, and PR descriptions.

Rules:
- Always respond with ONLY the requested format (usually JSON).
- Never add commentary, greetings, or markdown fencing unless the caller asks.
- Be extremely concise — every token costs time.
- You do NOT execute code or use tools. You only produce text.
"""


class SisterSession:
    """SDK-agnostic wrapper around an adapter's ``complete()`` method.

    Each job owns one of these.  The wrapper injects the system prompt on
    the first call and serialises concurrent access.
    """

    def __init__(self, adapter: AgentAdapterInterface) -> None:
        self._adapter = adapter
        self._lock = asyncio.Lock()
        self._primed = False
        self.created_at: float = time.monotonic()

    async def complete(self, prompt: str, timeout: float = 30.0) -> str:
        """Send *prompt* to the adapter and return the response text."""
        async with self._lock:
            effective = prompt
            if not self._primed:
                effective = f"{_UTILITY_SYSTEM_PROMPT}\n\n{prompt}"
                self._primed = True

            result = await asyncio.wait_for(
                self._adapter.complete(effective),
                timeout=timeout,
            )
            return result or ""


class SisterSessionManager:
    """Registry of per-job sister sessions backed by an SDK adapter.

    Maintains a small standby pool so sessions can be handed off instantly
    without blocking on adapter creation.

    Satisfies ``Completable`` so it can be passed directly to
    ``NamingService`` and ``SummarizationService``.
    """

    def __init__(
        self,
        adapter: AgentAdapterInterface,
        *,
        model: str = DEFAULT_UTILITY_MODEL,
        pool_size: int = _STANDBY_POOL_SIZE,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._pool_size = pool_size

        # Standby pool — ready-to-use SisterSession instances
        self._pool: deque[SisterSession] = deque()

        # Pre-warmed sessions awaiting adoption (token → session)
        self._warm: dict[str, SisterSession] = {}
        self._warm_created_at: dict[str, float] = {}

        # Adopted sessions bound to a job (job_id → session)
        self._jobs: dict[str, SisterSession] = {}

        self._bg_tasks: list[asyncio.Task[None]] = []

    @property
    def model(self) -> str:
        return self._model

    # -- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Seed the standby pool and start background maintenance tasks."""
        self._fill_pool()
        self._bg_tasks.append(
            asyncio.create_task(self._orphan_reaper(), name="sister-orphan-reaper")
        )
        log.debug("sister_session_manager_started", pool_size=self._pool_size)

    async def shutdown(self) -> None:
        """Cancel background tasks and clear all sessions."""
        for task in self._bg_tasks:
            task.cancel()
        for task in self._bg_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._bg_tasks.clear()
        self._pool.clear()
        self._warm.clear()
        self._warm_created_at.clear()
        self._jobs.clear()
        log.debug("sister_session_manager_shutdown")

    # -- Standby pool --------------------------------------------------------

    def _make_session(self) -> SisterSession:
        """Create a new SisterSession wrapper (cheap — no I/O)."""
        return SisterSession(adapter=self._adapter)

    def _fill_pool(self) -> None:
        """Top up the standby pool to ``_pool_size``."""
        while len(self._pool) < self._pool_size:
            self._pool.append(self._make_session())

    def _pop_or_create(self) -> SisterSession:
        """Pop a session from the pool, or create one if empty.

        Eagerly refills the pool after every pop so the next caller
        always finds a session ready.
        """
        session = self._pool.popleft() if self._pool else self._make_session()
        self._fill_pool()  # immediate top-up
        return session

    # -- Pre-warm (new-job panel) -------------------------------------------

    async def warm(self) -> str:
        """Hand out a pooled session under a token.

        Returns immediately — no blocking I/O.
        """
        token = secrets.token_urlsafe(16)
        self._warm[token] = self._pop_or_create()
        self._warm_created_at[token] = time.monotonic()
        log.debug("sister_session_warmed", token=token[:8])
        return token

    async def release(self, token: str) -> bool:
        """Return an unused warm session to the pool.  Returns True if found."""
        session = self._warm.pop(token, None)
        self._warm_created_at.pop(token, None)
        if session is None:
            return False
        # Recycle back into the pool if there's room
        if len(self._pool) < self._pool_size:
            session._primed = False  # noqa: SLF001
            self._pool.append(session)
        log.debug("sister_session_released", token=token[:8])
        return True

    # -- Job binding ---------------------------------------------------------

    async def adopt(self, token: str, job_id: str) -> None:
        """Bind a pre-warmed session to a job.

        If the token is gone (expired / already released), a fresh pooled
        session is used instead.
        """
        session = self._warm.pop(token, None)
        self._warm_created_at.pop(token, None)
        if session is None:
            log.debug("sister_adopt_token_miss", token=token[:8], job_id=job_id)
            session = self._pop_or_create()
        self._jobs[job_id] = session
        log.debug("sister_session_adopted", job_id=job_id)

    async def create_for_job(self, job_id: str) -> None:
        """Assign a pooled session to a job (resume / no pre-warm path)."""
        self._jobs[job_id] = self._pop_or_create()
        log.debug("sister_session_created", job_id=job_id)

    # -- Per-job access ------------------------------------------------------

    def get(self, job_id: str) -> SisterSession | None:
        """Get the sister session for a running job."""
        return self._jobs.get(job_id)

    # -- Cleanup -------------------------------------------------------------

    async def close_job(self, job_id: str) -> None:
        """Remove the session binding for a finished job."""
        session = self._jobs.pop(job_id, None)
        if session is not None:
            log.debug("sister_session_closed", job_id=job_id)

    # -- Non-job one-shot (Completable protocol) -----------------------------

    async def complete(self, prompt: str, timeout: float = 30.0) -> str:
        """One-shot completion for callers without a job context.

        Uses a pooled session, then recycles it.
        """
        session = self._pop_or_create()
        try:
            for attempt in range(_TIMEOUT_RETRIES + 1):
                try:
                    return await session.complete(prompt, timeout=timeout)
                except (TimeoutError, asyncio.TimeoutError):
                    if attempt >= _TIMEOUT_RETRIES:
                        raise
                    session._primed = False  # noqa: SLF001  # retry without context
            return ""
        except Exception:
            log.warning("sister_oneshot_failed", exc_info=True)
            return ""
        finally:
            # Recycle
            if len(self._pool) < self._pool_size:
                session._primed = False  # noqa: SLF001
                self._pool.append(session)

    # -- Background tasks ----------------------------------------------------

    async def _orphan_reaper(self) -> None:
        """Close warm sessions that were never adopted."""
        try:
            while True:
                await asyncio.sleep(_ORPHAN_CHECK_INTERVAL_S)
                now = time.monotonic()
                expired = [
                    token
                    for token, created in self._warm_created_at.items()
                    if now - created > _ORPHAN_EXPIRY_S
                ]
                for token in expired:
                    self._warm.pop(token, None)
                    self._warm_created_at.pop(token, None)
                    log.debug("sister_session_orphan_expired", token=token[:8])
        except asyncio.CancelledError:
            pass
