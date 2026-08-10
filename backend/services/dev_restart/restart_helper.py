"""Detached restart helper: hand-off, job pause, and process replacement.

Implements:
  - Story 1.3 "Hand Off to a Detached Helper" — native parent-side detached
    spawn plus bounded wait for adoption, and the helper-side claim of the
    pending request (create-exclusive lock, pending -> claimed rename,
    started marker).
  - Story 1.4 "Pause Jobs and Replace CodePlane" — response grace, complete
    running-job retrieval before any pause, individual pause-failure
    tolerance, exact old-process stop with port-release proof, and starting
    exactly one replacement with the request nonce (no ``/resume`` calls).

Schema, timeouts, phase logging, the create-exclusive lock, and the active
launch profile are owned by ``backend.services.dev_restart.restart_protocol``
and ``backend.services.dev_restart.launch_profile`` (integration session).
This module imports them directly and fails loudly if they are unavailable —
no local fallback implementations are used, per the project's decision to
keep a single protocol contract.

``tools/dev_restart.py`` stays a thin argparse/dispatch shell around the
functions here.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil
import structlog

from backend.services.dev_restart.launch_profile import (
    LaunchProfile,
    LaunchProfileError,
    load_active_profile,
    profile_owns_listener,
)
from backend.services.dev_restart.restart_protocol import (
    RestartLock,
    RestartLockHeldError,
    RestartPhase,
    RestartProtocolError,
    RestartRequestPaths,
    RestartTimeouts,
    acquire_restart_lock,
    get_request_paths,
    is_identity_alive,
    log_phase,
    read_json_file,
    release_restart_lock,
    write_json_atomic,
)
from backend.services.dev_restart.restart_remote import (
    RemoteProbeError,
    probe_remote_origin,
    resolve_remote_probe_target,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

log = structlog.get_logger()

# Job states the helper must pause before stopping the old server. Jobs that
# are already `waiting_for_approval` are, by definition, not running an agent
# turn — existing startup recovery (RuntimeService.recover_on_startup) owns
# their fate, and the helper never sends /resume for anything (AD-7).
_RUNNING_STATE = "running"

# Secret-free redaction keys: never let these substrings reach a log line or
# a persisted diagnostic file (AD-12).
_REDACTED_KEY_MARKERS = ("password", "token", "cookie", "authorization", "secret", "credential")


class HelperAbort(Exception):  # noqa: N818 - intentional control-flow signal, not an error condition
    """Raised internally by helper phases to unwind to the top-level handler.

    Carries the phase that was active and a short, redaction-safe reason so
    the outer loop can log exactly one ``failed`` phase line and exit
    nonzero, per AD-4/AD-11 (no success-shaped fallback, reproducible local
    recovery command).
    """

    def __init__(self, phase: RestartPhase, reason: str, **fields: Any) -> None:
        super().__init__(reason)
        self.phase = phase
        self.reason = reason
        self.fields = fields


@dataclass(slots=True)
class RestartRequest:
    """In-memory view of a claimed/pending restart request file."""

    request_id: str
    target_source_root: Path
    launch_profile: LaunchProfile
    timeouts: RestartTimeouts
    nonce: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestartRequest:
        return cls(
            request_id=data["requestId"],
            target_source_root=Path(data["targetSourceRoot"]),
            launch_profile=LaunchProfile.from_dict(data["launchProfile"]),
            timeouts=RestartTimeouts.from_dict(data.get("timeouts", {})),
            nonce=data.get("nonce") or uuid.uuid4().hex,
        )


def _redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop any field whose key looks secret-bearing before it is logged."""
    return {k: v for k, v in fields.items() if not any(marker in k.lower() for marker in _REDACTED_KEY_MARKERS)}


# ---------------------------------------------------------------------------
# Story 1.3 — native detached spawn (parent side)
# ---------------------------------------------------------------------------


def spawn_detached_helper(python_executable: Path, helper_script: Path, request_path: Path, log_handle: Any) -> int:
    """Start ``helper_script --helper <request_path>`` fully detached.

    POSIX: ``start_new_session=True`` puts the helper in a new session (and
    therefore a new process group), so it survives both the invoking
    shell/tool exiting and the CodePlane process-group being torn down.

    Windows: ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`` detaches from
    the parent's console and process group for the same survival property.

    stdin is always detached (``subprocess.DEVNULL``); stdout/stderr are
    bound to the single already-open log handle the parent computed once
    (AD-1/AD-12) — the helper never recomputes or reopens the log path.
    Returns the spawned helper's PID.
    """
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": log_handle,
        "close_fds": True,
    }

    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, native executable
        [str(python_executable), str(helper_script), "--helper", str(request_path)],
        **popen_kwargs,
    )
    return proc.pid


def await_adoption(paths: RestartRequestPaths, request_id: str, timeout_seconds: float) -> bool:
    """Block until ``<id>.started.json`` exists and names this exact request.

    Parent success requires adoption, not restart completion (AD-3) — this
    only proves a helper claimed the request and is proceeding; it says
    nothing about pause/stop/start outcomes.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if paths.started.exists():
            try:
                started = read_json_file(paths.started)
            except RestartProtocolError:
                time.sleep(0.1)
                continue
            if started.get("requestId") == request_id:
                return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# Story 1.3 — helper-side claim (pending -> claimed -> started)
# ---------------------------------------------------------------------------


def _claim_request(
    request_path: Path,
    paths: RestartRequestPaths,
    request_id: str,
    helper_pid: int,
    helper_process_time: float,
) -> RestartRequest:
    """Load the exact pending request path the parent spawned us with, write
    helper identity into it, and atomically rename pending -> claimed.

    The helper never scans the request directory for other pending requests
    (AD-3/Dev Notes) — it only ever consumes ``request_path`` exactly as
    passed on argv.
    """
    try:
        payload = read_json_file(request_path)
    except RestartProtocolError as exc:
        raise HelperAbort(RestartPhase.failed, "unreadable_request", detail=str(exc)) from exc

    if payload.get("requestId") != request_id:
        raise HelperAbort(
            RestartPhase.failed,
            "request_id_mismatch",
            expected=request_id,
            found=payload.get("requestId"),
        )

    payload["helperPid"] = helper_pid
    payload["helperProcessTime"] = helper_process_time
    payload["claimedAt"] = _now_iso()

    write_json_atomic(paths.claimed, payload)
    # The pending path is the exact file the parent spawned us with; once
    # claimed content is durably written, remove the pending file so a
    # second helper can never adopt the same request (defense in depth —
    # the create-exclusive lock is the primary concurrency guard).
    if request_path != paths.claimed:
        request_path.unlink(missing_ok=True)

    return RestartRequest.from_dict(payload)


def _write_started_marker(
    paths: RestartRequestPaths, request_id: str, helper_pid: int, helper_process_time: float
) -> None:
    write_json_atomic(
        paths.started,
        {
            "requestId": request_id,
            "helperPid": helper_pid,
            "helperProcessTime": helper_process_time,
            "startedAt": _now_iso(),
        },
    )


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Story 1.4 — running-job retrieval and pause
# ---------------------------------------------------------------------------


def _base_url(profile: LaunchProfile) -> str:
    return f"http://{profile.host}:{profile.port}"


def _http_request(
    method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 10.0
) -> tuple[int, dict[str, Any] | None]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            try:
                return resp.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.URLError:
        return 0, None


def _list_running_jobs(profile: LaunchProfile) -> list[dict[str, Any]]:
    """Return the complete list of currently running jobs (all pages).

    Any failure to retrieve the complete list aborts before any pause is
    sent (AD-7/AC-1) — a partial list must never be treated as complete.
    """
    base_url = _base_url(profile)
    jobs: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        path = f"/api/jobs?state={_RUNNING_STATE}&limit=100"
        if cursor:
            path += f"&cursor={cursor}"
        status, body = _http_request("GET", f"{base_url}{path}")
        if status != 200 or body is None:
            raise HelperAbort(RestartPhase.failed, "job_list_failed", status=status)
        jobs.extend(body.get("items", []))
        if not body.get("hasMore"):
            break
        cursor = body.get("cursor")
        if cursor is None:
            break
    return jobs


def _pause_jobs(profile: LaunchProfile, jobs: Sequence[dict[str, Any]], request_id: str) -> list[str]:
    """Send a pause request to every listed job.

    Once the first pause request is sent, the helper always continues
    toward restart (AD-7) — individual failures are recorded, never
    aborted on. A job record missing (or with a non-string) ``id`` is a
    per-job data problem, not a reason to abort the batch and strand the
    remaining jobs unpaused: it is logged and skipped like any other
    per-job failure. Returns the ids of jobs whose pause request failed.
    """
    failed: list[str] = []
    base_url = _base_url(profile)
    for job in jobs:
        job_id = job.get("id")
        if not isinstance(job_id, str):
            log_phase(RestartPhase.pausing, request_id, ok=False, reason="malformed_job_record")
            continue
        status, _ = _http_request("POST", f"{base_url}/api/jobs/{job_id}/pause")
        if status != 204:
            failed.append(job_id)
            log_phase(RestartPhase.pausing, request_id, job_id=job_id, ok=False, status=status)
        else:
            log_phase(RestartPhase.pausing, request_id, job_id=job_id, ok=True)
    return failed


# ---------------------------------------------------------------------------
# Story 1.4 — stop old process, start exactly one replacement
# ---------------------------------------------------------------------------


def _stop_old_process(profile: LaunchProfile, timeout_seconds: float, request_id: str) -> None:
    """Stop only the recorded old PID/creation-time; the helper's own
    session/process group is never included (it was detached at spawn).

    Uses the canonical ``is_identity_alive`` check (0.01s creation-time
    tolerance) before every signal, not an inline looser tolerance — a
    reused PID whose creation time merely happens to fall within a wide
    window must never be terminated/killed as if it were the original
    process (AD-4/Consistency Conventions: "Process ownership: exact
    spawned PID/process handle; process-name scans are not ownership").

    Stop completes only once that identity is absent *and* the configured
    port has no listener (AD-4/Consistency Conventions) — port-release
    proof, not merely "we sent a signal".
    """
    pid = profile.started_pid
    process_time = profile.started_process_time

    if is_identity_alive(pid, process_time):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            psutil.Process(pid).terminate()

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not profile_owns_listener(profile):
            return
        time.sleep(0.25)

    # Escalate once, then re-check for the remainder of the budget.
    if is_identity_alive(pid, process_time):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            psutil.Process(pid).kill()

    deadline = time.monotonic() + max(timeout_seconds, 2.0)
    while time.monotonic() < deadline:
        if not profile_owns_listener(profile):
            return
        time.sleep(0.25)

    raise HelperAbort(RestartPhase.stopping, "old_process_still_bound", pid=pid, port=profile.port)


def _start_replacement(
    profile: LaunchProfile,
    target_source_root: Path,
    nonce: str,
    request_id: str,
) -> subprocess.Popen[bytes]:
    """Start exactly one replacement from the validated target source using
    the recorded native executable and nonsecret runtime arguments.

    ``[profile.executable, "-m", "backend.main", "up", ...]`` is used rather
    than the ``cpl`` console-script shim to avoid depending on PATH
    resolution for the recorded interpreter — ``python -m backend.main``
    triggers the exact same ``if __name__ == "__main__": cli()`` entry point
    (verified against ``backend/main.py``/``backend/cli.py``'s ``up``
    command options: ``--host``, ``--port``, ``--dev``, ``--remote``,
    ``--provider``, ``--tunnel-name``, ``--tunnel-ownership``).
    ``--provider`` is always passed explicitly (never left to the CLI
    default) so a non-default recorded provider (e.g. cloudflare) is
    reproduced exactly. ``--tunnel-ownership`` is likewise replayed exactly
    from ``profile.tunnel_ownership`` when remote access was recorded (AD-8)
    so the replacement never re-derives ownership through the legacy
    auto-detect/process-scan path. Resolvable secret
    references (Dev Notes) need no extra flag: every defined
    ``SecretSource`` kind is either an inherited environment variable
    (``env = dict(os.environ)`` below) or external provider-login state,
    never a value this process must re-supply on the command line.

    The nonce is passed via environment so it never appears in a process
    listing; startup (Story 1.5, ``backend/lifespan.py``) is expected to
    read ``CODEPLANE_RESTART_NONCE`` and correlate it with the ready marker
    it writes after existing recovery and deferred remote validation. The
    helper never calls ``/resume`` — existing startup recovery owns job
    recovery.
    """
    args: list[str] = [
        str(profile.executable),
        "-m",
        "backend.main",
        "up",
        "--host",
        profile.host,
        "--port",
        str(profile.port),
    ]
    if profile.dev:
        args.append("--dev")
    if profile.remote:
        args.append("--remote")
        # Always pass --provider explicitly instead of relying on the CLI's
        # default: the recorded profile may have used a non-default
        # provider (e.g. cloudflare), and defaulting would silently launch
        # the wrong tunnel provider.
        args.extend(["--provider", profile.provider])
        if profile.tunnel_name:
            args.extend(["--tunnel-name", profile.tunnel_name])
        if profile.tunnel_ownership:
            # Replay the exact ownership recorded at original launch time
            # (managed vs. external, AD-8) so the replacement never falls
            # back to the legacy auto-detect/process-scan path for what
            # was originally an externally-owned connector.
            args.extend(["--tunnel-ownership", profile.tunnel_ownership])

    env = dict(os.environ)
    env["CODEPLANE_RESTART_NONCE"] = nonce
    env["CODEPLANE_RESTART_REQUEST_ID"] = request_id

    log_phase(
        RestartPhase.starting, request_id, host=profile.host, port=profile.port, dev=profile.dev, remote=profile.remote
    )

    return subprocess.Popen(  # noqa: S603 - fixed argv, recorded native executable
        args,
        cwd=str(target_source_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(sys.platform != "win32"),
    )


def _wait_for_ready(
    paths: RestartRequestPaths,
    request_id: str,
    child: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> int:
    """Wait for ``<id>.ready.json`` naming the new PID, then require the freshly
    published active launch profile to name that same PID and still own its
    listener. Success requires recovered-process identity, not mere port
    reachability (Story 1.5/AD-4) — the new process publishes its own launch
    profile (Story 1.1, ``backend/cli.py``) only after its listener is bound,
    so re-loading it here re-verifies ownership through the single
    centralized check instead of a second local implementation. Child exit
    before readiness is a hard failure.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise HelperAbort(RestartPhase.starting, "child_exited", exit_code=child.returncode)
        if paths.ready.exists():
            try:
                ready = read_json_file(paths.ready)
            except RestartProtocolError:
                time.sleep(0.2)
                continue
            if ready.get("requestId") == request_id:
                try:
                    new_profile = load_active_profile()
                except LaunchProfileError:
                    time.sleep(0.2)
                    continue
                if new_profile.started_pid == ready.get("pid") and profile_owns_listener(new_profile):
                    return new_profile.started_pid
        time.sleep(0.2)

    raise HelperAbort(RestartPhase.checking_health, "readiness_timeout", timeout_seconds=timeout_seconds)


# ---------------------------------------------------------------------------
# Cleanup (successful vs failed retention, AD-10/Constraints)
# ---------------------------------------------------------------------------


def _cleanup_success(paths: RestartRequestPaths) -> None:
    """Successful request artifacts are removed after terminal logging."""
    for path in (paths.pending, paths.claimed, paths.started, paths.ready):
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Top-level helper entry point
# ---------------------------------------------------------------------------


def run_helper(request_path: Path) -> int:
    """Entry point for ``dev_restart.py --helper <request-path>``.

    stdout/stderr are already bound to the inherited restart-log handle by
    the parent's detached spawn — this function only ever prints/logs; it
    never recomputes or reopens the log path (AD-12).

    Returns the process exit code: 0 on success, 1 on any failure. There is
    no success-shaped fallback (AD-11) — every failure path ends in a
    ``failed`` phase log line and a nonzero return.
    """
    request_path = Path(request_path)
    request_id = request_path.name.split(".")[0]
    helper_pid = os.getpid()
    helper_process_time = psutil.Process(helper_pid).create_time()

    log_phase(RestartPhase.spawned, request_id, helper_pid=helper_pid, helper_process_time=helper_process_time)

    paths = get_request_paths(request_id)

    try:
        lock: RestartLock = acquire_restart_lock(request_id, helper_pid, helper_process_time)
    except RestartLockHeldError as exc:
        log_phase(RestartPhase.failed, request_id, reason="lock_held", detail=str(exc))
        return 1

    try:
        return _run_claimed(request_path, paths, request_id, helper_pid, helper_process_time)
    finally:
        release_restart_lock(lock)


def _run_claimed(
    request_path: Path,
    paths: RestartRequestPaths,
    request_id: str,
    helper_pid: int,
    helper_process_time: float,
) -> int:
    try:
        request = _claim_request(request_path, paths, request_id, helper_pid, helper_process_time)
        _write_started_marker(paths, request_id, helper_pid, helper_process_time)

        time.sleep(request.timeouts.response_grace_seconds)

        log_phase(RestartPhase.pausing, request_id, phase_start=True)
        jobs = _list_running_jobs(request.launch_profile)
        failed_pauses = _pause_jobs(request.launch_profile, jobs, request_id)
        if failed_pauses:
            log_phase(RestartPhase.pausing, request_id, failed_job_ids=failed_pauses)
        time.sleep(request.timeouts.pause_wait_seconds)

        log_phase(
            RestartPhase.stopping,
            request_id,
            pid=request.launch_profile.started_pid,
            port=request.launch_profile.port,
        )
        _stop_old_process(request.launch_profile, request.timeouts.stop_seconds, request_id)

        child = _start_replacement(request.launch_profile, request.target_source_root, request.nonce, request_id)

        log_phase(RestartPhase.checking_health, request_id, child_pid=child.pid)
        new_pid = _wait_for_ready(paths, request_id, child, request.timeouts.readiness_seconds)

        # Local readiness alone is success for a local profile (AD-4: "local
        # profile -> succeeded"). A remote profile additionally requires the
        # recorded tunnel origin to be reachable again before the restart is
        # considered successful (Story 1.6/SPEC.md CAP-6) — origin
        # resolution and the bounded probe are owned entirely by
        # restart_remote; this only wires the phase transition and failure
        # handling around it, never duplicating probe/network logic locally.
        if request.launch_profile.remote:
            log_phase(RestartPhase.checking_remote, request_id, provider=request.launch_profile.provider)
            try:
                replacement_profile = load_active_profile()
            except LaunchProfileError as exc:
                raise HelperAbort(
                    RestartPhase.checking_remote, "remote_profile_unavailable", detail=str(exc)[:500]
                ) from exc
            try:
                target = resolve_remote_probe_target(request.launch_profile, replacement_profile)
                probe_remote_origin(target.origin, request.timeouts.remote_probe_seconds)
            except RemoteProbeError as exc:
                raise HelperAbort(RestartPhase.checking_remote, "remote_probe_failed", detail=str(exc)[:500]) from exc
            log_phase(RestartPhase.checking_remote, request_id, origin_changed=target.changed)

        log_phase(RestartPhase.succeeded, request_id, new_pid=new_pid)
        _cleanup_success(paths)
        return 0
    except HelperAbort as abort:
        log_phase(abort.phase, request_id, reason=abort.reason, **_redact(abort.fields))
        log_phase(RestartPhase.failed, request_id, reason=abort.reason)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level helper boundary must never propagate
        log_phase(RestartPhase.failed, request_id, reason="unexpected_error", detail=str(exc)[:500])
        return 1
