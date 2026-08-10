---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - '../specs/spec-codeplane-developer-restart/SPEC.md'
  - 'architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md'
  - 'architecture/architecture-codeplane-self-restart-2026-08-07/SOLUTION-DESIGN.md'
---

# CodePlane - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for CodePlane, decomposing the requirements from the canonical developer-restart specification and its adopted architecture companions into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: `cpl up` must atomically write a secret-free active launch profile after all launch options are resolved.

FR2: The active launch profile must record its schema version, native executable, working directory, host, port, development mode, remote mode, provider, tunnel ownership, tunnel identity, started PID, process creation time, secret-source records, and write timestamp.

FR3: Before any disruptive action, parent mode must verify that the active launch profile's PID and process creation time identify the process that owns the configured listener.

FR4: Parent mode must resolve an explicit native target source from `--source`, defaulting to the repository containing the invoked `tools/dev_restart.py`.

FR5: Parent mode must validate that the target source can run with the recorded active executable before handing off the restart.

FR6: For remote mode, parent mode must validate all required secret sources and stable tunnel identity before handing off the restart, refusing malformed, unresolved, or `unreplayable` required sources.

FR7: Parent mode must build the target source frontend before sending any pause request or stopping CodePlane.

FR8: Parent mode must use the recorded active executable to run `compileall` over `backend` and `tools`, then import `backend.app_factory` from the target source before sending any pause request or stopping CodePlane.

FR9: Any active-profile, source, credential, frontend-build, or backend-preflight failure must exit nonzero without disrupting the current listener.

FR10: Parent mode must atomically write a secret-free `<id>.pending.json` request that identifies the validated target source, active launch profile, request ID, and configured phase timeouts.

FR11: Parent mode must resolve and open the absolute restart log once, then spawn the private helper with stdout and stderr bound to that inherited log handle.

FR12: Parent mode must spawn the helper using native detached-process behavior that allows it to survive both the invoking process and the CodePlane process it will stop.

FR13: Parent mode must return success only when the exact request has become `<id>.claimed.json` and the helper has created the matching `<id>.started.json` marker.

FR14: Parent success must report only that the helper adopted the request and that restart continues in the background, including the absolute diagnostic log path.

FR15: Spawn failure or adoption timeout must exit nonzero while leaving the current CodePlane process running.

FR16: Helper mode must create `restart.lock` with create-exclusive semantics and record the request ID, helper PID, helper process creation time, and creation timestamp.

FR17: A later restart invocation may remove a stale lock only when the recorded helper PID plus process creation time is absent; a live helper lock must reject the concurrent restart.

FR18: The helper must claim only the exact pending request passed by its parent, write its identity into that request, atomically rename it to `<id>.claimed.json`, and create `<id>.started.json`.

FR19: After adoption, the helper must wait the configured response-grace interval before attempting to pause jobs.

FR20: The helper must retrieve the complete running-job list before sending any pause request; list retrieval failure must abort while the current server remains running and no job has been paused.

FR21: The helper must send a pause request for every job in the retrieved list, record each individual pause failure, and wait the configured pause interval.

FR22: Once the first pause request has been sent, the helper must continue toward restart despite individual pause failures so it cannot leave a partially paused server serving indefinitely.

FR23: The helper must stop only the old process identified by the active profile and must not target itself or unrelated processes.

FR24: Stop completion must require both absence of the old PID plus process creation time and absence of any listener on the configured port.

FR25: The helper must start exactly one replacement from the validated target source using the recorded native executable, working directory, host, port, development mode, remote mode, provider, tunnel ownership, tunnel identity, and re-resolvable secret sources.

FR26: The helper must pass a request-specific launch nonce to the replacement and redirect replacement console output to the normal CodePlane log path or the native null device.

FR27: The replacement process must create `<id>.ready.json` containing its PID only after existing startup recovery and deferred remote-access validation complete.

FR28: The helper must accept local restart success only when the matching readiness marker exists and its PID owns the configured listener.

FR29: The helper must not send resume requests; existing CodePlane startup recovery remains solely responsible for recovering managed jobs.

FR30: In managed tunnel mode, the replacement must launch the exact recorded provider identity and own the resulting connector process.

FR31: In external tunnel mode, restart must not scan for connector processes and must probe the exact configured hostname.

FR32: For a reusable tunnel identity, the helper must probe the recorded origin after local readiness; for a non-reusable identity, it must read the replacement profile, log any changed origin, and probe the newly published origin.

FR33: The helper must log progress using only the phases `spawned`, `pausing`, `stopping`, `starting`, `checking_health`, `checking_remote`, `succeeded`, and `failed`.

FR34: Adoption, response grace, pause wait, stop, readiness, and remote-probe timeouts must use documented defaults, support CLI overrides, and be logged before work begins.

FR35: A post-stop start, readiness, or remote failure must produce a nonzero helper result and log sufficient local diagnostics, including the exact reproducible launch command, for manual recovery.

FR36: Successful restart completion must remove the request, request-specific markers, and lock after terminal logging when safe.

FR37: Failed claimed requests and their markers must remain until explicit cleanup, and abandoned pending requests must never be auto-executed.

FR38: The restart log must rotate at 5 MiB with one backup.

FR39: Launch profiles, requests, markers, locks, and logs must contain no secret values.

FR40: Restart must remain a developer command and private helper mode; it must not add a REST route, MCP tool, frontend control, or other product-facing restart surface.

### NonFunctional Requirements

NFR1: Restart must be native to the current operating system. Windows uses Windows-native executables, paths, process creation, and PID handling; POSIX uses POSIX-native equivalents, with no cross-environment path translation or process launch.

NFR2: On POSIX, the helper must use a new session with detached stdin; on Windows, it must use `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, detached stdin, and inherit no handle except the explicit restart log handle.

NFR3: Automated evidence on both native Windows and POSIX must prove that the helper survives invoking-process termination, managed-agent interruption, and CodePlane listener process-group termination.

NFR4: Every failure before the first pause request must preserve availability of the existing CodePlane listener.

NFR5: All phase waits must be bounded. Defaults are 5 seconds for adoption, 2 seconds for response grace, 10 seconds for pause wait, 15 seconds for stop, 60 seconds for readiness, and 30 seconds for remote probing.

NFR6: Process ownership decisions must use PID plus process creation time and, where required, listener ownership. Process-name scans must not be used as ownership evidence.

NFR7: Diagnostic output must be deterministic, local, secret-free, and sufficient to distinguish handoff, pause, stop, launch, local readiness, remote readiness, and terminal failure.

NFR8: Diagnostic errors must be redacted and must never expose passwords, tunnel tokens, cookies, authorization headers, secret values, or the full process environment.

NFR9: Profile, request, claim, marker, and lock writes that establish protocol state must be atomic or create-exclusive as specified so interrupted writes cannot be mistaken for valid state.

NFR10: Backend preflight must not install or synchronize dependencies, mutate runtime state, or use a different Python environment from the recorded active executable.

NFR11: Existing `RuntimeService.recover_on_startup()` behavior must remain authoritative and unchanged, including the documented failure of plan-mode jobs interrupted while `waiting_for_approval`.

NFR12: Temporary browser, SSE, WebSocket, MCP, and tunnel disconnections are acceptable; the design must not imply uninterrupted remote availability or remote progress reporting.

NFR13: Post-stop failure may require local-terminal recovery. The implementation must not add automated rollback, a service manager, supervisor, gateway, lifecycle database, or deployment-generation mechanism.

NFR14: The restart protocol must support exactly one active helper and reject rather than queue concurrent restart attempts.

NFR15: The implementation must use existing project tooling, including `uv` for Python interactions, and must preserve existing CodePlane CLI and startup-recovery compatibility.

### Additional Requirements

- Preserve the mandatory execution order: build, backend preflight, detached spawn, helper adoption, job pause, old-process stop, replacement start, readiness verification.
- Store the active launch profile at `~/.codeplane/run.json` and the restart protocol files under `~/.codeplane/dev-restart/`.
- Store restart diagnostics at the absolute path `~/.codeplane/logs/dev-restart.log`; the helper must use the inherited handle rather than recomputing that path.
- Keep parent mode and private `--helper` mode in `tools/dev_restart.py`, with platform-specific detachment centralized in a small helper where practical.
- Extend `backend/cli.py` to write the active launch profile only after launch options and process identity are known.
- Extend startup integration in `backend/lifespan.py` to publish the request-specific readiness marker after startup recovery and deferred remote validation.
- Reuse existing runtime pause and startup-recovery behavior rather than creating a second recovery coordinator.
- Treat tunnel ownership as explicit `managed` or `external` state; do not infer connector ownership from broad process reuse or process scans.
- Use secret-source kind values exactly as `not_required`, `resolvable`, or `unreplayable`.
- Use a UUID only to correlate each request, marker set, and related log entries.
- Define stop completion as old process identity absent plus configured port unbound.
- Define start completion as matching ready-marker PID owning the configured port.
- Record log entries with timestamp, helper PID, server PID when known, host, port, phase, exit code, and redacted error.
- Keep request and marker files as diagnostic evidence only; no startup scanner may discover and execute abandoned requests.
- Add unit coverage in `backend/tests/unit/test_dev_restart.py` for ordering, exact request adoption, launch-profile preservation, lock behavior, failures, marker validation, and secret redaction.
- Add unit coverage in `backend/tests/unit/test_cli.py` for atomic active-launch-profile creation, required fields, process identity, and secret-source handling.
- Add native Windows and POSIX process-level tests proving helper and log-handle survival across initiator and listener termination.
- Verify that build or preflight failure leaves the existing listener healthy and that parent success cannot occur before exact helper adoption.
- Verify remote managed, external, reusable-origin, non-reusable-origin, and credential-refusal behavior.
- No starter template, database migration, API versioning, frontend component, daemon, gateway, or service-manager setup is required.

### UX Design Requirements

Not applicable. This developer-only command has no frontend or user-interface scope, and no UX design contract was provided.

### FR Coverage Map

FR1: Epic 1 - Persist the resolved active launch profile.
FR2: Epic 1 - Record complete secret-free runtime and process identity.
FR3: Epic 1 - Refuse stale profiles that do not own the listener.
FR4: Epic 1 - Select an explicit native target source.
FR5: Epic 1 - Validate target-source compatibility with the active executable.
FR6: Epic 1 - Validate replayable remote secrets and tunnel identity.
FR7: Epic 1 - Build the frontend before disruption.
FR8: Epic 1 - Compile and import-preflight the backend before disruption.
FR9: Epic 1 - Preserve the listener on preparation failure.
FR10: Epic 1 - Write the atomic secret-free pending request.
FR11: Epic 1 - Open and inherit the absolute restart log handle.
FR12: Epic 1 - Spawn a native detached helper.
FR13: Epic 1 - Require exact claim and started-marker adoption.
FR14: Epic 1 - Report adopted background execution accurately.
FR15: Epic 1 - Preserve the server on spawn or adoption failure.
FR16: Epic 1 - Acquire the create-exclusive helper lock.
FR17: Epic 1 - Reject concurrency and recover only identity-proven stale locks.
FR18: Epic 1 - Claim only the parent's exact pending request.
FR19: Epic 1 - Allow the parent response grace interval.
FR20: Epic 1 - Retrieve all running jobs before pausing.
FR21: Epic 1 - Pause every listed job and record individual failures.
FR22: Epic 1 - Continue restart after the first pause request.
FR23: Epic 1 - Stop only the recorded old process.
FR24: Epic 1 - Prove process absence and port release.
FR25: Epic 1 - Start exactly one replacement with preserved runtime options.
FR26: Epic 1 - Pass the launch nonce and redirect child output.
FR27: Epic 1 - Publish readiness after recovery and remote validation.
FR28: Epic 1 - Verify ready-marker PID listener ownership.
FR29: Epic 1 - Leave job recovery solely to startup recovery.
FR30: Epic 1 - Restore the exact managed tunnel provider identity.
FR31: Epic 1 - Probe external tunnel hostname without process scans.
FR32: Epic 1 - Probe reusable or newly published tunnel origins.
FR33: Epic 1 - Emit bounded canonical diagnostic phases.
FR34: Epic 1 - Apply logged, overridable phase timeouts.
FR35: Epic 1 - Preserve reproducible post-stop failure diagnostics.
FR36: Epic 1 - Remove successful request artifacts safely.
FR37: Epic 1 - Retain failed evidence and never auto-run abandoned requests.
FR38: Epic 1 - Rotate the restart log at the configured bound.
FR39: Epic 1 - Keep all restart artifacts secret-free.
FR40: Epic 1 - Keep restart as developer tooling, not a product surface.

## Epic List

### Epic 1: Safe Developer Self-Restart

A CodePlane developer or managed agent can safely hand restart execution to a native detached helper, replace the supervising CodePlane instance with the intended source and preserved runtime configuration, restore configured local or remote operation, and diagnose failures without adding product infrastructure.

**FRs covered:** FR1-FR40

## Epic 1: Safe Developer Self-Restart

A CodePlane developer or managed agent can safely hand restart execution to a native detached helper, replace the supervising CodePlane instance with the intended source and preserved runtime configuration, restore configured local or remote operation, and diagnose failures without adding product infrastructure.

### Story 1.1: Persist the Active Launch Profile

As a CodePlane developer,
I want `cpl up` to persist the resolved native launch identity,
So that self-restart can reproduce the active instance safely.

**Requirements:** FR1-FR6, FR39

**Acceptance Criteria:**

**Given** `cpl up` has resolved its executable, working directory, host, port, development mode, remote options, tunnel configuration, and process identity
**When** the active CodePlane listener has started
**Then** `~/.codeplane/run.json` is atomically written with schema version, all resolved runtime and tunnel fields, started PID, process creation time, and write timestamp
**And** an interrupted write cannot be mistaken for a valid profile.

**Given** a launch option does or does not require a secret
**When** its source is serialized in the active profile
**Then** its kind is exactly `not_required`, `resolvable`, or `unreplayable`
**And** the profile contains only provider/reference metadata, never a secret value.

**Given** a recorded active profile
**When** restart validation compares it with the configured listener
**Then** the profile is accepted only if its recorded PID plus process creation time identifies the process that owns the recorded port
**And** a stale PID, reused PID, mismatched listener, malformed profile, or unsupported schema is refused.

**Given** remote mode requires authentication or tunnel credentials
**When** the source is `unreplayable`, malformed, or cannot be resolved again
**Then** restart validation refuses before any disruptive action
**And** no credential value is written to profile or diagnostic output.

**Given** CodePlane is running on Windows or POSIX
**When** the profile is created and validated
**Then** executable and working-directory paths remain native to that operating system
**And** no cross-environment path translation or launcher is introduced.

**Given** the active-launch-profile unit tests
**When** they run
**Then** they cover atomic creation, required fields, process identity, listener ownership, secret-source validation, stale-profile refusal, and secret redaction
**And** existing `cpl up` behavior remains compatible.

### Story 1.2: Prepare Restart Without Outage

As a CodePlane developer,
I want restart preparation to finish while the current server remains available,
So that invalid code or configuration cannot cause an avoidable outage.

**Requirements:** FR4-FR10, FR34, FR39

**Acceptance Criteria:**

**Given** parent mode is invoked with or without `--source`
**When** it resolves the restart target
**Then** it uses the explicit source or defaults to the repository containing the invoked `tools/dev_restart.py`
**And** the resolved path is native, absolute, and validated as a CodePlane source tree.

**Given** a valid active profile and target source
**When** parent mode prepares the restart
**Then** it runs the frontend build before any helper spawn, pause request, or stop request
**And** a build failure exits nonzero while the existing listener remains healthy.

**Given** the frontend build succeeds
**When** backend preflight runs
**Then** the recorded active executable runs `compileall` over `backend` and `tools`, then imports `backend.app_factory` from the target source
**And** preflight neither synchronizes dependencies nor mutates runtime state.

**Given** remote mode is active
**When** parent mode validates restart preparation
**Then** it resolves every required secret source and validates the recorded tunnel identity
**And** malformed, unresolved, or `unreplayable` required sources fail before any outage.

**Given** all preparation checks pass
**When** parent mode creates the restart request
**Then** it atomically writes `<id>.pending.json` with the request ID, validated target source, launch-profile reference or snapshot, and configured phase timeouts
**And** the request contains no secret values.

**Given** any profile, source, credential, build, preflight, or request-write failure
**When** parent mode exits
**Then** it has sent no pause or stop request and the original listener remains available
**And** focused tests verify ordering and listener preservation for each failure class.

### Story 1.3: Hand Off to a Detached Helper

As a CodePlane developer or managed agent,
I want the restart request adopted by an independent native helper,
So that restart continues after both the initiator and supervising server are interrupted.

**Requirements:** FR11-FR18, FR33-FR34, FR38-FR39

**Acceptance Criteria:**

**Given** a prepared pending request
**When** parent mode begins handoff
**Then** it resolves and opens the absolute restart log once and spawns private `--helper <request-path>` mode with stdout and stderr bound to that handle
**And** the helper never recomputes the log path from its environment.

**Given** POSIX execution
**When** the helper is spawned
**Then** it uses `start_new_session=True`, detached stdin, and the explicit inherited log handle
**And** it survives initiator termination and CodePlane process-group termination.

**Given** Windows execution
**When** the helper is spawned
**Then** it uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, detached stdin, and no inherited handle except the explicit log handle
**And** it survives initiator termination and listener termination.

**Given** the helper starts
**When** it adopts the request
**Then** it writes `spawned`, creates `restart.lock` with `O_CREAT | O_EXCL`, records request ID plus helper PID and process creation time, writes its identity into the request, atomically renames pending to claimed, and creates the matching started marker
**And** it claims only the exact request path passed by its parent.

**Given** an existing restart lock
**When** another restart is attempted
**Then** a live recorded helper identity rejects the attempt
**And** the lock is removed as stale only when that exact PID plus process creation time is absent.

**Given** the parent is waiting for adoption
**When** the configured adoption timeout expires or spawn fails
**Then** parent mode exits nonzero and the existing CodePlane listener remains running
**And** no claimed file or started marker from a different request can satisfy acceptance.

**Given** the exact request is claimed and its started marker exists
**When** parent mode reports success
**Then** it says only that the helper adopted the request and restart continues in the background
**And** it includes the absolute restart log path without claiming that restart completed.

### Story 1.4: Pause Jobs and Replace CodePlane

As a CodePlane developer,
I want the adopted helper to quiesce managed jobs and replace only the active CodePlane process,
So that self-restart proceeds without losing its coordinator or targeting unrelated processes.

**Requirements:** FR19-FR26, FR29, FR33-FR35

**Acceptance Criteria:**

**Given** the helper has adopted the request
**When** the configured response-grace interval elapses
**Then** it retrieves the complete running-job list before sending any pause request
**And** list retrieval failure terminates the helper before any job is paused or the server is stopped.

**Given** a complete running-job list
**When** the helper enters `pausing`
**Then** it sends one pause request for every listed job, records each individual failure, and waits the configured pause interval
**And** after the first pause request it continues toward restart despite individual pause failures.

**Given** pause processing has completed
**When** the helper enters `stopping`
**Then** it targets only the old PID plus process creation time recorded in the validated profile
**And** the helper, unrelated processes, and processes found only by name are never targeted.

**Given** a stop request has been sent
**When** stop completion is evaluated
**Then** both the old process identity must be absent and the configured port must have no listener
**And** timeout logs the remaining process or listener identity and exits nonzero without starting a replacement.

**Given** stop completion is proven
**When** the helper enters `starting`
**Then** it starts exactly one replacement from the validated target source using the recorded native executable, working directory, host, port, development mode, remote mode, provider, tunnel ownership, tunnel identity, and resolvable secret references
**And** it passes the request-specific launch nonce and redirects child output to the normal CodePlane log or native null device.

**Given** jobs were paused or remained running after individual pause failures
**When** the replacement starts
**Then** the helper sends no resume request
**And** existing startup recovery remains the only recovery authority, including existing plan-mode approval limitations.

### Story 1.5: Prove Recovery and Local Readiness

As a CodePlane developer,
I want restart completion based on recovered-process identity rather than port reachability alone,
So that I can trust that the intended replacement is ready.

**Requirements:** FR27-FR29, FR33-FR35, FR39

**Acceptance Criteria:**

**Given** the helper starts a replacement with a request-specific launch nonce
**When** CodePlane startup runs
**Then** `backend/lifespan.py` associates startup with that request without creating general restart orchestration state
**And** normal startup without a restart nonce remains unchanged.

**Given** replacement startup is in progress
**When** existing startup recovery has not completed
**Then** no request-specific ready marker exists
**And** an open port alone cannot satisfy restart success.

**Given** startup recovery and any configured deferred remote-access validation complete
**When** readiness is published
**Then** the replacement atomically writes `<id>.ready.json` containing its PID and request correlation
**And** the marker contains no secret value.

**Given** the helper enters `checking_health`
**When** it reads the ready marker
**Then** it accepts local readiness only if the marker matches the request and its PID owns the configured listener
**And** stale markers, unrelated PIDs, child exit, and readiness timeout produce a nonzero result.

**Given** existing plan-mode jobs were interrupted while `waiting_for_approval`
**When** startup recovery runs
**Then** their documented failure behavior remains unchanged
**And** developer restart does not reconstruct approval context or send duplicate resume calls.

**Given** local startup or readiness verification fails after the old server stopped
**When** the helper records terminal failure
**Then** it logs the exact reproducible launch command and relevant process, port, marker, and exit diagnostics
**And** it makes no success-shaped fallback or automated rollback attempt.

### Story 1.6: Restore Configured Remote Access

As a remotely connected CodePlane developer,
I want restart to restore the configured tunnel behavior,
So that I can reconnect after the expected temporary interruption.

**Requirements:** FR30-FR35

**Acceptance Criteria:**

**Given** the active profile records `managed` tunnel ownership
**When** the replacement starts
**Then** it launches the exact recorded provider identity and owns the resulting connector process
**And** broad process scans or unrelated existing connectors are not treated as ownership evidence.

**Given** the active profile records `external` tunnel ownership
**When** remote validation runs
**Then** CodePlane starts no connector and performs no connector process scan
**And** the helper probes the exact configured hostname.

**Given** the tunnel has a reusable identity
**When** local readiness is established and the helper enters `checking_remote`
**Then** it probes the recorded origin within the configured remote timeout
**And** success requires that exact origin to respond as expected.

**Given** the tunnel has no reusable identity
**When** restart preparation and replacement startup occur
**Then** the parent warns that the origin may change, the replacement profile publishes the new origin, and the helper logs and probes that origin
**And** no unchanged-origin guarantee is reported.

**Given** local CodePlane is ready but remote validation or probing fails
**When** the helper records the result
**Then** it distinguishes local readiness from remote failure and logs provider, ownership mode, expected origin, and redacted diagnostics
**And** remote clients are expected to reconnect manually after MCP, SSE, WebSocket, browser, or tunnel interruption.

### Story 1.7: Harden Diagnostics and Native Restart Evidence

As a CodePlane maintainer,
I want bounded, secret-free diagnostics and cross-platform restart evidence,
So that the developer-only feature is supportable without product infrastructure.

**Requirements:** FR33-FR40

**Acceptance Criteria:**

**Given** any helper execution
**When** progress is logged
**Then** phase is one of `spawned`, `pausing`, `stopping`, `starting`, `checking_health`, `checking_remote`, `succeeded`, or `failed`
**And** each entry includes timestamp, helper PID, server PID when known, host, port, exit code when applicable, and a redacted error.

**Given** restart begins
**When** timeout configuration is resolved
**Then** defaults are 5 seconds adoption, 2 seconds response grace, 10 seconds pause wait, 15 seconds stop, 60 seconds readiness, and 30 seconds remote probe
**And** each value is CLI-overridable and logged before work begins.

**Given** restart logging exceeds 5 MiB
**When** the next entry is written
**Then** the log rotates with exactly one backup
**And** the active inherited handle continues to produce usable diagnostics.

**Given** helper execution succeeds
**When** terminal success is logged
**Then** the request, request-specific markers, and lock are removed when safe
**And** no active helper can lose its concurrency protection prematurely.

**Given** a claimed restart fails
**When** the helper exits
**Then** the claimed request and request-specific markers remain until explicit cleanup
**And** no startup path scans or executes abandoned pending or claimed requests.

**Given** profiles, requests, locks, markers, logs, and failure commands are inspected
**When** secret-redaction tests run
**Then** they contain no passwords, tunnel tokens, cookies, authorization headers, secret values, or full environment dumps
**And** required diagnostic fields remain available.

**Given** native Windows and POSIX process-level test environments
**When** the restart handoff is exercised
**Then** tests prove helper and log-handle survival after initiator termination, managed-agent interruption, and listener process-group termination
**And** stopping the recorded listener cannot include the helper.

**Given** the complete developer-restart change
**When** architectural scope is reviewed
**Then** it adds no REST route, MCP tool, frontend control, database migration, daemon, gateway, supervisor, service-manager integration, deployment generation, or automated rollback
**And** all FRs, NFRs, and architecture requirements are covered by focused unit and process-level tests.
