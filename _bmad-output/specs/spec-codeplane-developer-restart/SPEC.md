---
id: SPEC-codeplane-developer-restart
companions:
  - '../../planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md'
  - '../../planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/SOLUTION-DESIGN.md'
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate.

# CodePlane Developer Restart

## Why

CodePlane developers need a managed CodePlane agent to restart the CodePlane instance supervising it after frontend or backend changes. The current in-process flow can pause or terminate the initiator before restart completes, drops remote launch settings, and can take down a working server before build failure is known.

## Capabilities

- **CAP-1**
  - **intent:** A developer can prepare a CodePlane restart without disrupting the running instance.
  - **success:** Frontend build and backend compile/import preflight finish before any pause or stop, and every preparation failure leaves the current listener healthy.

- **CAP-2**
  - **intent:** A developer or managed CodePlane agent can hand restart execution to a process that survives both the initiator and the server.
  - **success:** Parent success occurs only after the detached helper claims the exact request, writes through the inherited log handle, and creates `<id>.started.json`; survival is demonstrated on Windows and POSIX.

- **CAP-3**
  - **intent:** A restart applies the intended native CodePlane source while preserving active runtime options.
  - **success:** The helper launches the explicit target source with the recorded native executable, working directory, host, port, development mode, remote provider, and tunnel settings; profile validity requires its recorded PID plus process creation time to own the current listener, and stale profiles or unresolved required secrets are refused before outage.

- **CAP-4**
  - **intent:** The detached helper can quiesce managed jobs and replace the current CodePlane process.
  - **success:** It obtains the complete running-job list before pausing, records individual pause failures, stops only the recorded old process, proves the port is unbound, and starts exactly one replacement.

- **CAP-5**
  - **intent:** A developer can distinguish completed restart recovery from simple port reachability.
  - **success:** The replacement writes a request-specific readiness marker only after startup recovery and deferred remote validation, and the helper verifies that marker PID owns the configured port.

- **CAP-6**
  - **intent:** A remotely accessed development instance can restore its configured tunnel behavior after restart.
  - **success:** Managed mode relaunches the recorded provider identity, external mode probes the exact hostname without process scans, and a changed non-reusable origin is logged for manual reconnection.

- **CAP-7**
  - **intent:** A developer can diagnose restart progress and prevent concurrent helpers without adding product infrastructure.
  - **success:** Pending, claimed, started, and ready files; one PID-plus-creation-time lock; bounded phase logs; stale-lock checks; and secret-free diagnostics behave deterministically.

## Constraints

- This is developer-only tooling. Add no REST route, MCP tool, frontend restart control, lifecycle database, gateway, supervisor, service manager, deployment generation, or automated rollback.
- Restart is native to the current operating system. Windows uses Windows-native paths and processes; POSIX uses POSIX-native paths and processes.
- Existing startup recovery remains authoritative. The helper never sends resume calls, and documented plan-mode `waiting_for_approval` failure behavior remains unchanged.
- Stale launch profiles, invalid target source, unreplayable required secrets, preparation failure, spawn failure, adoption timeout, lock conflict, or running-job-list failure must leave the current server running.
- After the first pause request, the helper continues toward restart while recording individual pause failures so it cannot leave a partially paused server serving indefinitely.
- Python interactions use existing project tooling through `uv`; the detached replacement uses the recorded active Python executable without dependency synchronization.
- Default timeouts are 5 seconds for adoption, 2 seconds for response grace, 10 seconds for pause wait, 15 seconds for stop, 60 seconds for readiness, and 30 seconds for remote probing. Each is CLI-overridable and logged.
- Backend preflight uses the recorded active executable to run `compileall` over `backend` and `tools`, then imports `backend.app_factory` from the target source without installing dependencies or mutating runtime state.
- Successful request artifacts are removed after terminal logging. Failed claimed requests and markers remain for diagnosis until explicit cleanup. The restart log rotates at 5 MiB with one backup.

## Non-goals

- Continuous remote availability or progress reporting during restart.
- Automatic rollback or recovery after post-stop failure.
- Restarting across operating-system environments or translating paths between them.
- Changing existing job restart-recovery semantics.
- Supporting restart as a general operator or end-user product feature.

## Success signal

A managed CodePlane agent runs the developer restart command, receives confirmation that the helper adopted the request, is interrupted with the other jobs, and later resumes after the replacement process publishes its readiness marker. The same flow passes on native Windows and POSIX, while every pre-outage failure leaves the original server available.

## Assumptions

- Manual local recovery after a post-stop failure is acceptable because only CodePlane developers use this command.
- Temporary browser, SSE, WebSocket, and MCP disconnects are acceptable; remote developers reconnect manually.
