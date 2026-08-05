# Brownfield Constraints

This companion is normative. It preserves the existing local product mode as a first-class contract while Kubernetes-native operation is added.

## Source Context

- `../../../SPEC.md`
- `../../../README.md`
- `../../../docs/architecture.md`
- `../../../docs/configuration.md`
- `../../../docs/guide.md`
- `../../../docs/quick-start.md`
- `../../../docs/security.md`
- `../../../docs/reference/cli.md`
- `../../../docs/reference/job-states.md`
- `../../../docs/reference/sse-events.md`

## Preserved Guarantees

| Area | Load-bearing guarantee |
|---|---|
| Product identity | CodePlane is a control plane that runs, observes, supervises, and reviews coding-agent work; it is not itself an agent model. |
| Local lifecycle | Python package installation and cpl setup, doctor, up, down, restart, info, and version form the workstation lifecycle; graceful shutdown pauses active sessions and startup resumes them in place with reason `server_restart`. |
| Local data | Single-user state, canonical events, telemetry, trails, and metadata use local SQLite under ~/.codeplane; artifacts, config, logs, and VAPID material are local assets. |
| Repository safety | Registered local or cloned Git repositories are allowlisted; managed jobs use isolated Git worktrees and do not execute in the primary checkout. |
| Agent integration | Existing locally installed and authenticated Copilot and Claude CLIs or SDK adapters supply execution; credentials remain local and adapter boundaries normalize sessions. |
| Native mirroring | Native Copilot and Claude CLI sessions can be discovered and ingested without requiring users to launch work through CodePlane. |
| Events and state | Canonical domain events drive persistence, state transitions, live SSE, replay, snapshots, approvals, and audit history. TraceForge envelopes and open dotted `SessionEvent.kind` values are preserved end to end; transport keepalives are distinct from `session.heartbeat`. |
| Remote access | Localhost is the safe default; optional Dev Tunnel or Cloudflare paths add authenticated remote and mobile access without converting CodePlane into a hosted service. |
| Offline posture | Product data and local transcription remain on the workstation by default; network use is explicit for agent providers, Git remotes, tunnels, OTEL export, and other configured integrations. |
| Operator control | Policy evaluation defaults to the `supervised` preset; hard gates, approvals, intervention, cancellation, review, merge or PR or discard resolution, and provenance remain core semantics. |

## Preservation Rules

- Local-daemon installation and operation cannot require Kubernetes, a cloud account, or a central CodePlane service.
- Existing local repositories, local clones, local Git credentials, agent CLI credentials, worktrees, SQLite data, artifact files, tunnels, and offline behavior remain valid supported inputs and assets.
- Native CLI-session mirroring remains a product capability rather than an implementation detail of managed jobs.
- Kubernetes additions may generalize internal boundaries, but may not silently change existing job states, canonical event meaning, approvals, review, resolution, or provenance.
- Persistence and SSE must deliver the TraceForge event envelope and dotted event kind without legacy snake_case translation; transport keepalives must not be persisted or replayed as session heartbeat events.
- Graceful local-daemon shutdown must pause active sessions, and startup must resume them in place using `server_restart`; blanket failure of active jobs on restart is not conformant.
- Mode-specific differences must be visible in product and operator documentation and covered by the conformance matrix.

## Superseded Source Passages

- Runtime behavior and user documentation are authoritative for the `supervised` default and graceful pause/resume restart behavior; contrary root `SPEC.md` passages are retained only as historical source material.
- TraceForge-native envelopes and open dotted event kinds are authoritative; contrary legacy snake_case and heartbeat passages in root `SPEC.md` are retained only as historical source material.

## Traceability

| Preserved concern | Contract coverage |
|---|---|
| Dual first-class modes and local independence | CAP-1, CAP-22, CAP-23, CAP-24 |
| Shared lifecycle, TraceForge events, approvals, restart recovery, review, and audit | CAP-2, CAP-7, CAP-9, CAP-12 |
| Repositories, worktrees, local credentials, and agent locality | CAP-3, CAP-4, CAP-17, CAP-23 |
| SQLite, artifacts, retention, and durability | CAP-5, CAP-19, CAP-24 |
| CLI lifecycle, tunnels, remote and offline access | CAP-10, CAP-13, CAP-22, CAP-24 |
| Security and operator control | CAP-6, CAP-7, CAP-15, CAP-20 |
| Migration without forced replacement | CAP-14, CAP-24 |
