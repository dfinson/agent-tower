# Story 1.1: Persist the Active Launch Profile

Status: ready-for-dev

## Story

As a CodePlane developer,
I want `cpl up` to persist the resolved native launch identity,
so that self-restart can reproduce the active instance safely.

## Acceptance Criteria

1. **Given** `cpl up` has resolved its executable, working directory, host, port, development mode, remote options, tunnel configuration, and process identity, **when** the active CodePlane listener has started, **then** `~/.codeplane/run.json` is atomically written with schema version, all resolved runtime and tunnel fields, started PID, process creation time, and write timestamp, and an interrupted write cannot be mistaken for a valid profile.
2. **Given** a launch option does or does not require a secret, **when** its source is serialized in the active profile, **then** its kind is exactly `not_required`, `resolvable`, or `unreplayable`, and the profile contains only provider/reference metadata, never a secret value.
3. **Given** a recorded active profile, **when** restart validation compares it with the configured listener, **then** the profile is accepted only if its recorded PID plus process creation time identifies the process that owns the recorded port, and a stale PID, reused PID, mismatched listener, malformed profile, or unsupported schema is refused.
4. **Given** remote mode requires authentication or tunnel credentials, **when** the source is `unreplayable`, malformed, or cannot be resolved again, **then** restart validation refuses before any disruptive action, and no credential value is written to profile or diagnostic output.
5. **Given** CodePlane is running on Windows or POSIX, **when** the profile is created and validated, **then** executable and working-directory paths remain native to that operating system, and no cross-environment path translation or launcher is introduced.
6. **Given** the active-launch-profile unit tests, **when** they run, **then** they cover atomic creation, required fields, process identity, listener ownership, secret-source validation, stale-profile refusal, and secret redaction, and existing `cpl up` behavior remains compatible.

## Tasks / Subtasks

- [ ] Task 1: Establish one reusable active-launch-profile contract (AC: 1, 2, 3, 4, 5)
  - [ ] Define schema version `1`, required fields, closed secret-source variants, and valid local/remote field combinations.
  - [ ] Resolve the profile path through `get_codeplane_dir() / "run.json"` so `CODEPLANE_HOME` remains authoritative.
  - [ ] Keep schema parsing, serialization, atomic persistence, and validation in one focused internal helper surface. Do not duplicate the contract between `backend/cli.py` and future restart tooling.
- [ ] Task 2: Preserve the provenance of resolved `cpl up` options (AC: 1, 2, 4, 5)
  - [ ] Track whether passwords and tunnel credentials came from environment or `.env`, provider login state, a CLI literal, auto-generation, or were not required.
  - [ ] Build a secret-free immutable profile payload only after effective provider, tunnel handle, authentication mode, host, port, and native paths are resolved.
  - [ ] Persist the actual tunnel identity returned by remote startup, not an unresolved input default.
- [ ] Task 3: Publish the profile only after the listener is bound (AC: 1, 3)
  - [ ] Integrate a post-bind callback or small `uvicorn.Server` subclass that awaits `super().startup()` before writing.
  - [ ] Confirm the server reports started and the current PID owns the configured listener before publishing.
  - [ ] Never write immediately before `server.run()`, because Uvicorn has not bound the socket at that point.
  - [ ] On publication failure, exit startup nonzero, preserve any previously complete profile, and remove only the failed temporary file.
- [ ] Task 4: Implement fail-closed profile validation for later restart use (AC: 3, 4, 5)
  - [ ] Reject missing, unreadable, malformed, incomplete, or unsupported-schema profiles.
  - [ ] Verify live process identity using PID plus `psutil.Process(pid).create_time()`.
  - [ ] Verify that exact identity owns the recorded listener by reusing or extracting existing port-owner logic. Do not use process-name scans.
  - [ ] Reject malformed required secret-source records and required `unreplayable` sources without performing build, pause, or stop work.
- [ ] Task 5: Add focused profile and CLI regression tests (AC: 1-6)
  - [ ] Test every required field and local/remote combination.
  - [ ] Test same-directory temporary write plus atomic replacement, interrupted-write behavior, and temporary-file cleanup.
  - [ ] Test dead PID, reused PID, creation-time mismatch, wrong listener owner, unsupported schema, malformed JSON, and process-inspection errors.
  - [ ] Test secret-source classification and assert serialized profile and errors do not contain representative password or token values.
  - [ ] Preserve existing `cpl up`, `down`, and `restart` tests and CLI behavior.

## Dev Notes

### Implementation Boundary

This story creates the active launch profile and a reusable validator. It does not implement the restart parent/helper flow, job pausing, process replacement, readiness markers, or tunnel relaunch. Those are later stories.

Do not add a REST route, MCP tool, frontend control, database state, daemon, service manager, supervisor, gateway, or rollback mechanism.

### Current State

- `backend/cli.py` resolves host, port, provider, password, tunnel inputs, migrations, remote access, application state, Uvicorn configuration, and signal behavior before calling blocking `server.run()`.
- No `run.json` writer or launch-profile model exists today.
- `get_codeplane_dir()` in `backend/config.py` already honors `CODEPLANE_HOME`; do not hard-code `Path.home() / ".codeplane"`.
- `_find_pids_on_port` and existing platform-specific PID handling already provide listener-owner behavior. Reuse or extract this behavior instead of creating a second process-discovery implementation.
- Existing `cpl up` invariants must remain: `--phone` implies remote mode, provider selection requires remote mode, unsafe no-password combinations are rejected, preflight precedes migrations and binding, app state is configured before serving, and current signal handling remains intact.

### Active Launch Profile Contract

Use camelCase JSON field names exactly as shown:

| Field | Type | Requirement |
| --- | --- | --- |
| `schemaVersion` | integer | Must equal `1`; unknown versions fail closed. |
| `executable` | string | Absolute native path from the active Python executable. |
| `workingDirectory` | string | Absolute native process working directory used by `cpl up`. |
| `host` | string | Final effective bind host. |
| `port` | integer | Final effective listener port. |
| `dev` | boolean | Final development-mode value. |
| `remote` | boolean | Final remote-mode value. |
| `provider` | string | `local`, `devtunnel`, or `cloudflare`. |
| `tunnelOwnership` | string or null | `managed` or `external` when remote; `null` when no tunnel applies. |
| `tunnelName` | string or null | Actual stable tunnel name or hostname after remote startup. |
| `passwordSource` | object | Closed secret-source record. |
| `tunnelCredentialSource` | object | Closed secret-source record. |
| `startedPid` | integer | Current CodePlane server PID. |
| `startedProcessTime` | number | Creation time returned for that PID by `psutil`. |
| `writtenAt` | string | UTC ISO-8601 timestamp. |

If current provider behavior needs additional replay metadata, add only secret-free provider-specific fields required to reproduce the launch. Do not store tokens, passwords, cookies, authorization headers, or a copied environment.

### Secret-Source Classification

Secret-source records are a closed union:

- `{"kind": "not_required"}`
- `{"kind": "resolvable", "provider": "<provider>", "reference": "<reference>"}`
- `{"kind": "unreplayable"}`

Classification rules:

| Effective source | Profile record |
| --- | --- |
| Option not used for the active mode | `not_required` |
| `CPL_PASSWORD` read from `.env` or environment | `resolvable`, provider `environment`, reference `CPL_PASSWORD` |
| `CPL_CLOUDFLARE_TUNNEL_TOKEN` | `resolvable`, provider `environment`, reference `CPL_CLOUDFLARE_TUNNEL_TOKEN` |
| Authenticated Dev Tunnel CLI state | `resolvable`, provider `provider-login`, reference `devtunnel` |
| Literal `--password` value without a durable reference | `unreplayable` |
| Auto-generated password | `unreplayable` |
| External tunnel that CodePlane does not start | Tunnel credential source `not_required` |
| Cloudflare Access replaces CodePlane password auth | Password source `not_required`; preserve only the nonsecret access configuration or its resolvable references needed at restart. |

Never infer that a CLI literal is replayable merely because an environment variable happens to contain the same value. Classify the source actually selected by CLI precedence.

For remote modes:

- `managed` means this `cpl up` invocation started and owns the connector.
- `external` means CodePlane did not start a connector and will later probe the exact configured hostname.
- Record `TunnelHandle.name` or the resolved provider identity, not an omitted `--tunnel-name` input.

### Post-Bind Publication

The locked project versions are Python 3.12+, Uvicorn 0.48.0, and psutil 7.2.2. Do not add or upgrade dependencies for this story.

In Uvicorn 0.48.0, `Server.startup()` runs lifespan startup, creates the listening socket, logs the started address, and then sets `self.started = True`. The safe publication point is after `await super().startup()` returns successfully. A pre-`server.run()` write can publish a false active profile when socket binding or lifespan startup fails.

The publication callback must:

1. Capture `os.getpid()` and its `psutil` creation time.
2. Confirm the exact PID owns the configured port.
3. Write JSON to a uniquely named temporary file in the same directory as `run.json`.
4. Flush the complete JSON and atomically replace `run.json` with `os.replace`.
5. Remove only its own temporary file if writing or replacement fails.

Do not delete an older complete profile before replacement. If the current process later exits, its persisted PID, creation time, and listener ownership make that profile safely stale.

### Validation Rules

Validation must fail closed on:

- Missing or unsupported `schemaVersion`.
- Missing fields, wrong field types, invalid enum values, or impossible local/remote combinations.
- Missing process, PID reuse, creation-time mismatch, access denied during inspection, or listener-owner mismatch.
- Malformed required secret-source records.
- A required source with kind `unreplayable`.

Use native paths and native process APIs only. Do not translate Windows paths to POSIX or POSIX paths to Windows.

### Architecture Compliance

- Keep the feature developer-only and file-backed.
- Treat `run.json` as diagnostic launch identity, not product orchestration state.
- Persist source references, never secret values.
- Use exact process identity and listener ownership, never process names.
- Existing startup recovery remains untouched.
- No database migration or API contract change is needed.

### Library and Framework Requirements

- Use existing Python standard-library JSON, filesystem, datetime, and temporary-file APIs.
- Use existing psutil for process creation time and listener inspection.
- Use the locked Uvicorn startup lifecycle; do not introduce a server wrapper dependency.
- Continue using `uv` for all project Python commands.

### File Structure Requirements

Expected changes:

- **Update:** `backend/cli.py` for provenance capture and post-bind publication wiring.
- **Update:** `backend/tests/unit/test_cli.py` for CLI integration and regression coverage.
- **Preferred focused helper:** add one internal module under `backend/services/` for launch-profile schema, atomic persistence, and validation if keeping all logic in `backend/cli.py` would force future tooling to import CLI command code.
- **If a helper module is added:** add a focused unit test file under `backend/tests/unit/`.

Do not modify `tools/dev_restart.py` beyond what is strictly necessary to exercise a reusable validator. Parent/helper orchestration belongs to later stories.

### Testing Requirements

- Follow existing `pytest`, `CliRunner`, `unittest.mock.patch`, and `Test<Feature>` class conventions.
- Mock process and listener inspection deterministically; do not depend on the developer machine's active port table in unit tests.
- Add platform-parametrized cases for native Windows and POSIX paths without translating between them.
- Assert atomic behavior by observing the final file and replacement call, not by accepting a partially written intermediate file.
- Use representative sentinel secrets and assert they are absent from serialized JSON, raised errors, and captured CLI output.
- Keep targeted tests independent of real tunnel providers and authenticated provider state.

### Project Structure Notes

This is a brownfield CLI change. Reuse existing configuration paths, remote-provider enums, tunnel handles, process ownership helpers, and test conventions. The only justified new module is a small internal launch-profile boundary that prevents schema and validation duplication in later restart stories.

No previous story implementation exists. There are no prior-story learnings or file changes to carry forward.

### Latest Technical Information

- Python `os.replace` provides replacement semantics across supported native operating systems when source and destination are on the same filesystem. Create the temporary file beside `run.json`.
- psutil `Process.create_time()` is the required secondary identity key that protects against PID reuse.
- Uvicorn 0.48.0 sets `Server.started` only after its startup method has created listener sockets. Publish after successful `super().startup()`, not from ASGI lifespan startup and not before `server.run()`.

### Project Context Reference

No `project-context.md` file exists. Follow repository instructions, the canonical SPEC, architecture spine, solution design, and this story.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-11-Persist-the-Active-Launch-Profile`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#Capabilities`]
- [Source: `_bmad-output/specs/spec-codeplane-developer-restart/SPEC.md#Constraints`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-5-Restart-preserves-the-active-launch-profile`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/ARCHITECTURE-SPINE.md#AD-12-Evidence-stays-local-and-secret-free`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-self-restart-2026-08-07/SOLUTION-DESIGN.md#Active-Launch-Profile`]
- [Source: `backend/cli.py` `up`, remote resolution, and Uvicorn startup sections]
- [Source: `backend/config.py#get_codeplane_dir`]
- [Source: `backend/services/sharing/tunnel_service.py` `RemoteProvider`, `TunnelHandle`, and `start_remote_access`]
- [Source: `backend/tests/unit/test_cli.py`]
- [Source: `pyproject.toml` Python, Uvicorn, and psutil constraints]
- [Source: `uv.lock` Uvicorn 0.48.0 and psutil 7.2.2]
- [External: Python `os.replace` documentation, https://docs.python.org/3/library/os.html#os.replace]
- [External: Uvicorn 0.48.0 `Server.startup`, https://github.com/encode/uvicorn/blob/0.48.0/uvicorn/server.py]

## Dev Agent Record

### Agent Model Used

To be completed by the dev agent.

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed, comprehensive developer guide created.

### File List
