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
from collections import OrderedDict, deque
from typing import TYPE_CHECKING

import structlog

from backend.services.lightweight_completer import LightweightCompleter

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

# Maximum number of closed-job metric snapshots to retain
_CLOSED_JOBS_MAX = 500

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
        self._prime_once = asyncio.Event()
        self._prime_lock = asyncio.Lock()
        self._primed = False
        self.created_at: float = time.monotonic()
        # Metrics — only accessed via += after each call, safe under GIL
        self.call_count: int = 0
        self.total_latency_ms: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.last_call_at: float | None = None

    def _reset_metrics(self) -> None:
        """Zero out all metric counters (used when recycling back to pool)."""
        self.call_count = 0
        self.total_latency_ms = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.last_call_at = None

    async def _ensure_primed(self, prompt: str) -> str:
        """Prepend system prompt on the very first call, then let all
        subsequent calls proceed without any lock contention."""
        if self._primed:
            return prompt
        async with self._prime_lock:
            # Double-check after acquiring
            if self._primed:
                return prompt
            self._primed = True
            return f"{_UTILITY_SYSTEM_PROMPT}\n\n{prompt}"

    async def complete(self, prompt: str, timeout: float = 30.0) -> str:
        """Send *prompt* to the adapter and return the response text.

        Calls are fully concurrent after the first (which injects the
        system prompt).  The underlying adapter.complete() is responsible
        for its own thread/connection safety.
        """
        effective = await self._ensure_primed(prompt)
        t0 = time.monotonic()
        result = await asyncio.wait_for(
            self._adapter.complete(effective),
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        self.call_count += 1
        self.total_latency_ms += elapsed_ms
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens
        self.total_cost_usd += result.cost_usd
        self.last_call_at = time.monotonic()
        return result.text or ""


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

        # Fast-path completer — direct HTTP to LLM API, bypasses SDK subprocess
        self._fast_completer = LightweightCompleter(adapter, model=model)

        # Standby pool — ready-to-use SisterSession instances
        self._pool: deque[SisterSession] = deque()

        # Pre-warmed sessions awaiting adoption (token → session)
        self._warm: dict[str, SisterSession] = {}
        self._warm_created_at: dict[str, float] = {}

        # Adopted sessions bound to a job (job_id → session)
        self._jobs: dict[str, SisterSession] = {}

        # Snapshots of per-job metrics preserved after close_job() (LRU-bounded)
        self._closed_jobs: OrderedDict[str, dict[str, object]] = OrderedDict()

        self._bg_tasks: list[asyncio.Task[None]] = []

        # Global metrics (accumulated from closed sessions)
        self._global_call_count: int = 0
        self._global_latency_ms: float = 0.0
        self._global_input_tokens: int = 0
        self._global_output_tokens: int = 0
        self._global_cost_usd: float = 0.0

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
        await self._fast_completer.close()
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
            session._reset_metrics()  # noqa: SLF001
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
            # Snapshot per-job metrics so they survive after close
            if session.call_count > 0:
                self._closed_jobs[job_id] = {
                    "callCount": session.call_count,
                    "avgLatencyMs": round(session.total_latency_ms / session.call_count, 1),
                    "totalLatencyMs": round(session.total_latency_ms, 1),
                    "inputTokens": session.total_input_tokens,
                    "outputTokens": session.total_output_tokens,
                    "costUsd": round(session.total_cost_usd, 6),
                }
                # Evict oldest entries if over the cap
                while len(self._closed_jobs) > _CLOSED_JOBS_MAX:
                    self._closed_jobs.popitem(last=False)
            # Accumulate into global metrics before dropping
            self._global_call_count += session.call_count
            self._global_latency_ms += session.total_latency_ms
            self._global_input_tokens += session.total_input_tokens
            self._global_output_tokens += session.total_output_tokens
            self._global_cost_usd += session.total_cost_usd
            log.debug("sister_session_closed", job_id=job_id)

    # -- Non-job one-shot (Completable protocol) -----------------------------

    async def complete(self, prompt: str, timeout: float = 30.0) -> str:
        """One-shot completion for callers without a job context.

        Uses the fast-path direct HTTP completer when available (bypasses
        the SDK subprocess entirely).  Falls back to a pooled SisterSession.
        """
        # Fast path — direct API call (~500ms vs 3-10s subprocess)
        if self._fast_completer.available:
            try:
                t0 = time.monotonic()
                result = await asyncio.wait_for(
                    self._fast_completer.complete(
                        f"{_UTILITY_SYSTEM_PROMPT}\n\n{prompt}"
                    ),
                    timeout=timeout,
                )
                elapsed_ms = (time.monotonic() - t0) * 1000
                # Track fast-path calls in global metrics
                self._global_call_count += 1
                self._global_latency_ms += elapsed_ms
                self._global_input_tokens += result.input_tokens
                self._global_output_tokens += result.output_tokens
                self._global_cost_usd += result.cost_usd
                log.debug(
                    "fast_complete_ok",
                    elapsed_ms=round(elapsed_ms, 1),
                    model=self._model,
                )
                return result.text or ""
            except Exception:
                log.warning("fast_complete_failed_falling_back", exc_info=True)

        # Slow path — full SDK session
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
            # Accumulate one-shot session metrics into globals before recycling
            self._global_call_count += session.call_count
            self._global_latency_ms += session.total_latency_ms
            self._global_input_tokens += session.total_input_tokens
            self._global_output_tokens += session.total_output_tokens
            self._global_cost_usd += session.total_cost_usd
            # Recycle
            if len(self._pool) < self._pool_size:
                session._primed = False  # noqa: SLF001
                session._reset_metrics()  # noqa: SLF001
                self._pool.append(session)

    # -- Background tasks ----------------------------------------------------

    def get_metrics(self) -> dict:
        """Return global + per-job sister session metrics."""
        # Live metrics from active job sessions
        active_calls = sum(s.call_count for s in self._jobs.values())
        active_latency = sum(s.total_latency_ms for s in self._jobs.values())
        total_calls = self._global_call_count + active_calls
        total_latency = self._global_latency_ms + active_latency

        per_job: dict[str, dict[str, object]] = {}
        # Include closed (completed) job snapshots
        per_job.update(self._closed_jobs)
        # Overlay live metrics from active jobs (overrides if somehow both)
        for job_id, session in self._jobs.items():
            per_job[job_id] = {
                "callCount": session.call_count,
                "avgLatencyMs": round(session.total_latency_ms / session.call_count, 1) if session.call_count else 0,
                "totalLatencyMs": round(session.total_latency_ms, 1),
                "inputTokens": session.total_input_tokens,
                "outputTokens": session.total_output_tokens,
                "costUsd": round(session.total_cost_usd, 6),
            }

        return {
            "global": {
                "totalCalls": total_calls,
                "avgLatencyMs": round(total_latency / total_calls, 1) if total_calls else 0,
                "activeJobs": len(self._jobs),
                "poolSize": len(self._pool),
                "warmTokens": len(self._warm),
            },
            "jobs": per_job,
        }

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
