"""Module-level constants and helpers for the Claude adapter."""

from __future__ import annotations

import contextlib
import os
import signal

from backend.models.domain import PermissionMode

# Claude SDK tool names that are internal / should not appear in transcript
_HIDDEN_TOOLS: frozenset[str] = frozenset()

# Map CodePlane permission modes to Claude SDK permission modes
_PERMISSION_MODE_MAP: dict[PermissionMode, str] = {
    PermissionMode.full_auto: "bypassPermissions",
    PermissionMode.observe_only: "plan",
    PermissionMode.review_and_approve: "default",
}


def _kill_sdk_subprocess(client: object | None) -> None:
    """Terminate the SDK's CLI subprocess using raw OS signals.

    This MUST be used instead of ``client.disconnect()`` or
    ``transport.close()`` because both invoke anyio methods whose
    cancel-scope teardown injects ``CancelledError`` into every
    SQLAlchemy connection in the process via the greenlet adapter.

    Pure OS calls (``os.kill`` / ``os.waitpid``) bypass anyio entirely
    and cannot contaminate other asyncio tasks.
    """
    if client is None:
        return
    transport = getattr(client, "_transport", None)
    if transport is None:
        return
    process = getattr(transport, "_process", None)
    if process is None:
        return
    # anyio Process wraps an asyncio.subprocess.Process in _process
    inner = getattr(process, "_process", None)
    pid: int | None = None
    if inner is not None:
        pid = getattr(inner, "pid", None)
    if pid is None:
        pid = getattr(process, "pid", None)
    if pid is None:
        return
    with contextlib.suppress(ProcessLookupError, OSError):
        os.kill(pid, signal.SIGTERM)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    # Null out SDK internal references so the garbage collector doesn't
    # try to clean them up through anyio (which triggers the connection
    # pool contamination on __del__).
    with contextlib.suppress(AttributeError, TypeError):
        transport._process = None  # private access needed for cleanup
        transport._stdout_stream = None
        transport._stdin_stream = None
        transport._ready = False
    with contextlib.suppress(AttributeError, TypeError):
        query = getattr(client, "_query", None)
        if query is not None:
            query._tg = None  # prevent cancel-scope teardown in GC
            client._query = None  # type: ignore[attr-defined]
        client._transport = None  # type: ignore[attr-defined]
