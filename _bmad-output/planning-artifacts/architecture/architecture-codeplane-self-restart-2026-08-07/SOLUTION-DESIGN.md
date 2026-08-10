# CodePlane Developer Restart: Maintainer Design

## Scope

This is internal development tooling for CodePlane maintainers. It must let a CodePlane-managed agent restart the CodePlane instance that is currently supervising it.

It does not provide a supported restart API, uninterrupted remote control, deployment generations, rollback, or high availability.

## Shape

```text
Developer or CodePlane agent
        |
        v
dev_restart.py parent
  1. Read active launch profile
  2. Build frontend
  3. Run lightweight backend preflight
  4. Write helper request
  5. Spawn detached helper
  6. Wait for adoption marker
  7. Return
        |
        v
dev_restart.py --helper
  1. Claim request and lock
  2. Wait short response grace
  3. Pause running jobs
  4. Stop current CodePlane
  5. Start the recorded launch profile
  6. Wait for health
  7. Log result and exit
```

The key property is ordering: **build, spawn, adoption, pause, stop, start**.

## Active Launch Profile

`cpl up` writes `~/.codeplane/run.json` atomically after its launch options are resolved:

```json
{
  "schemaVersion": 1,
  "executable": "C:\\path\\to\\python.exe",
  "workingDirectory": "C:\\path\\to\\active-codeplane",
  "host": "127.0.0.1",
  "port": 8080,
  "dev": false,
  "remote": true,
  "provider": "devtunnel",
  "tunnelOwnership": "managed",
  "tunnelName": "stable-name",
  "passwordSource": {
    "kind": "resolvable",
    "provider": "environment",
    "reference": "CPL_PASSWORD"
  },
  "tunnelCredentialSource": {
    "kind": "resolvable",
    "provider": "provider-login",
    "reference": "devtunnel"
  },
  "startedPid": 1234,
  "startedProcessTime": 1786132800.123,
  "writtenAt": "2026-08-07T20:00:00Z"
}
```

The profile contains no secret values. Each secret source uses exactly one kind:

- `not_required`
- `resolvable`, with a provider and reference
- `unreplayable`

Auto-generated passwords are recorded as `unreplayable`. Remote restart is refused when a required source is `unreplayable`, malformed, or cannot be resolved again from config, environment, `.env`, or authenticated provider state.

The profile preserves runtime options. The restart request separately records a native `targetSourceRoot`, defaulting to the repository containing the invoked `dev_restart.py`. This permits a CodePlane job to apply changes from its own worktree intentionally.

CodePlane restart never translates paths or launches through another operating environment. A Windows instance uses Windows executables and paths. A POSIX instance uses POSIX executables and paths. Platform branching is limited to process detachment and PID handling.

## Parent Mode

Normal invocation remains:

```text
uv run python tools/dev_restart.py
```

Parent mode:

1. Refuses when the profile's started PID plus process creation time does not identify the current listener on its recorded port.
2. Resolves the native `targetSourceRoot` from `--source` or the invoking repository, then runs the recorded executable and target compile/import probe from that source.
3. Refuses when another restart lock belongs to a live helper PID.
4. Validates that remote credentials and stable tunnel identity can be resolved when remote mode is active.
5. Computes and opens the absolute restart log path, then builds the target source frontend while CodePlane remains available.
6. Runs a lightweight backend compile/import preflight against the target source.
7. Atomically writes a secret-free request under `~/.codeplane/dev-restart/`.
8. Starts the same script in private `--helper <request-path>` mode using platform-specific detachment and the inherited log handle.
9. Waits for `<request-id>.started` up to a short timeout.
10. Returns success only after adoption. The message states that restart is continuing in the background and points to the log.

If build, preflight, spawn, or adoption fails, the current server remains running.

## Helper Mode

Helper mode is not a public command. It:

1. Writes `spawned` through the inherited log handle.
2. Creates `restart.lock` with `O_CREAT | O_EXCL`, recording request ID, helper PID, process creation time, and timestamp.
3. Writes helper identity into the request and atomically renames `<id>.pending.json` to `<id>.claimed.json`.
4. Creates `<id>.started.json`.
5. Waits a short grace interval so the parent tool result can be delivered.
6. Retrieves the complete running-job list. Retrieval failure aborts before any pause is sent.
7. Sends every pause request, logs individual failures, and waits `pauseWaitSeconds`. Once the first pause is sent, it always proceeds to restart.
8. Stops the recorded old process and requires both its PID plus creation time to disappear and its port to have no listener. The helper is in a different session/process group and is never targeted.
9. Starts `cpl up` from the validated target source root using the recorded native executable and nonsecret runtime arguments.
10. Redirects child console output to the normal CodePlane log path or null device.
11. Passes a request-specific launch nonce to the child. Startup writes `<id>.ready.json` containing the new PID only after existing startup recovery and deferred remote-access validation complete.
12. Requires the readiness marker PID to own the configured port. For remote mode, it then probes the exact recorded origin under `checking_remote`.
13. Logs the terminal result, removes its request and lock when safe, and exits.

The helper does not call `/resume`. Existing startup recovery owns job recovery.

## Cross-Platform Detachment

### POSIX

Spawn with `start_new_session=True`, detached stdin, and stdout/stderr bound to the parent's already-open log handle. Verification must prove the helper survives:

- termination of the invoking shell/tool process,
- interruption of the managed agent, and
- process-group termination of the CodePlane listener.

### Windows

Spawn with `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, detached stdin, and no inherited handles except the explicit log handle. Verification must prove the same survival properties and confirm that stopping the listener PID cannot include the helper.

The implementation may centralize these differences in a small `_spawn_detached_helper()` function. No service manager is required.

## Remote Behavior

Remote restart is deliberately basic:

- The current MCP, SSE, WebSocket, and browser connections will disconnect.
- `managed` tunnel mode starts the exact recorded provider identity and owns its connector process.
- `external` tunnel mode performs no process scan and probes the exact recorded hostname.
- The remote user reconnects or refreshes manually.
- If the previous tunnel had no reusable identity, the parent warns that the URL may change; the helper reads the replacement profile, logs the new origin, and probes it.
- There is no remote progress endpoint while CodePlane is down.

When the restart was initiated through a remote managed agent, the last reliable result is the parent's `helper adopted request` response. Completion is determined by reconnecting or checking the local log.

## Failure Behavior

| Failure | Result |
| --- | --- |
| Frontend build fails | Parent exits nonzero; current server remains running. |
| Backend preflight fails | Parent exits nonzero; current server remains running. |
| Active launch profile missing or stale | Parent refuses restart. |
| Target source is invalid or cannot run with the recorded executable | Parent refuses before helper spawn. |
| Remote credentials cannot be re-resolved | Parent refuses restart. |
| Helper cannot detach or adopt request | Parent exits nonzero; current server remains running. |
| Running-job list fails | Helper aborts before sending any pause. |
| Individual pause request fails | Helper records the job and continues restart; startup recovery handles jobs left running. |
| Server does not stop | Helper logs remaining listener PID and exits nonzero. |
| New server exits or misses readiness timeout | Helper logs the exact launch command and exits nonzero; developer recovers locally. |
| Tunnel does not return | Local CodePlane may still be healthy; helper logs tunnel/startup diagnostics. |

There is no automated rollback. That is an accepted tradeoff for developer-only tooling.

## Existing Recovery Limitation

Most running managed jobs are recovered by `RuntimeService.recover_on_startup()`. Existing plan-mode jobs interrupted while `waiting_for_approval` are intentionally failed because their in-memory approval context cannot be reconstructed. The developer restart command does not change that behavior.

## Files Changed by Implementation

```text
tools/dev_restart.py
  parent/helper split, request handshake, detachment, logging

backend/cli.py
  atomic secret-free active launch profile with process identity

backend/lifespan.py
  request-specific readiness marker after recovery and remote validation

backend/tests/unit/test_dev_restart.py
  parent ordering, handshake, launch preservation, failure behavior

backend/tests/unit/test_cli.py
  active launch profile behavior
```

No new API route, MCP tool, database migration, frontend component, daemon, gateway, or service-manager integration is required.

## Acceptance Evidence

- Build failure leaves the current listener healthy.
- Parent success is impossible until the helper has adopted the exact pending request and can write through the inherited log handle.
- The helper survives termination of the invoking agent process on Windows and POSIX.
- The helper survives CodePlane server process-group termination.
- The initiating managed job is paused only after helper adoption.
- Restart uses the explicit validated target source, defaulting to the invoking CodePlane worktree.
- Host, port, dev mode, remote provider, and stable tunnel identity survive restart.
- Stale run profiles whose PID/process time do not own the port are refused.
- Auto-generated or otherwise unreplayable remote passwords are refused.
- Remote restart refuses credentials that cannot be re-resolved.
- Success requires the new PID's readiness marker after existing startup recovery and remote validation, plus that PID owning the port.
- Start or health failure produces a nonzero helper result and a reproducible local recovery command.
- Concurrent restart attempts are rejected by the lock.
- Request, profile, marker, and logs contain no secret values.

## Accepted Tradeoffs

- Remote clients disconnect.
- The initiating session may not receive a final completion message.
- Random tunnel URLs may change.
- Plan-mode approval waits may fail through existing recovery behavior.
- A failed restart may require a local terminal.
- Updating the helper itself is not guaranteed.