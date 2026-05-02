---
title: "Trail Service: Canonical Provenance Authority"
status: in-progress
---

# Trail Service: Canonical Provenance Authority

> The trail is the single source of truth for what an agent did, why, and in what order.
> Every downstream service — activity timeline, cost attribution, summarization, story,
> motivation, handoff — consumes adapted projections from the trail. None of them touch
> raw session data.

---

## 1. Core Principle

TrailService is the **sole provenance authority** for every coding agent job. It ingests raw session events, persists enriched trail nodes, and publishes domain events. All downstream services read adapted projections from trail data — never the raw event stream.

This is classical Event Sourcing (Fowler): the canonical event log is the system of record, all application state is derivable from it, and derived projections are disposable read models.

### The Invariant

```
Raw SessionEvents → RuntimeService (translation) → TrailService (provenance) → TrailNodeRow (persisted)
                                                                              → DomainEvents (published)
                                                                                    ↓
                                                              ALL downstream services consume ONLY these
```

**Temporal boundary**: No service may retrospectively query `EventRepository` for raw session events to build derived views. The synchronous feeds during the hot path (RuntimeService → TrailService, RuntimeService → StepTracker) are the ingestion mechanism. Once an event has been processed and a trail node persisted, the raw event is dead to all consumers.

---

## 2. Ingestion: Raw Events to Trail Nodes

### 2.1 The Hot Path

RuntimeService runs a single sequential event loop per job:

```python
async for session_event in agent_session.execute(config, adapter):
    domain_event = _process_agent_event(session_event)   # translate
    trail_service.feed_transcript(role, content, ...)     # provenance
    trail_service.feed_tool_name(tool_name)               # provenance
    step_tracker.on_transcript_event(domain_event)        # structural — also reads
                                                          # step_tracker.current_step()
                                                          # to annotate domain_event
                                                          # with step_number / step_id
```

Each raw `SessionEvent` from the agent adapter is:
1. Translated into a `DomainEvent` by RuntimeService
2. Fed to TrailService (semantic provenance) and StepTracker (structural boundaries)
3. Persisted as a `TrailNodeRow` with deterministic fields filled immediately

### 2.2 Step Completion (Batched)

StepTracker detects step boundaries from structural signals (new `turn_id`, operator message, job start) and emits `step_completed` events via the event bus. TrailService subscribes and creates synthetic `step` trail nodes with Git SHA boundaries and metadata.

### 2.3 Plan Ingestion

When the agent calls plan-management tools (`manage_todo_list`, `TodoWrite`), RuntimeService calls `trail_service.feed_native_plan()`. TrailService also runs `_infer_plan()` when no native plan exists. Plan data populates `plan_item_*` columns on trail nodes.

---

## 3. Two-Layer Architecture: Structure + Enrichment

Every trail node has two layers of data, produced at different times through different mechanisms.

### 3.1 Deterministic Structure (Immediate)

Set at creation time, never mutated. No LLM involved.

| Field | Source |
|-------|--------|
| `kind` | Adapter event type mapping |
| `phase` | RuntimeService phase state machine |
| `step_id`, `turn_id` | StepTracker boundary detection / adapter |
| `start_sha`, `end_sha` | Git auto-commit on step boundary |
| `files` | Tool call argument extraction |
| `tool_names`, `tool_count` | Counted from adapter events |
| `timestamp` | Event arrival time |
| `seq` | Monotonic counter per job |
| `preceding_context` | Ring buffer snapshot (see §4) |
| `agent_message` | Last agent text in step |

### 3.2 Semantic Enrichment (Asynchronous)

Filled by the enrichment drain loop via sister session LLM calls. Initially NULL.

| Field | Source |
|-------|--------|
| `intent` | LLM inference: what did this action accomplish? |
| `rationale` | LLM inference: why did the agent take this action? |
| `outcome` | LLM inference: what was the result? |
| `title` | LLM-generated human-readable title |
| `activity_id`, `activity_label` | Activity boundary inference |
| `plan_item_id`, `plan_item_label`, `plan_item_status` | Plan correlation |

### 3.3 Mutation Rules

Trail nodes follow three mutation classes:

1. **Structural mutation** (changing `kind`, `step_id`, `seq`, etc.) — **forbidden**
2. **Enrichment fill** (writing to initially-NULL semantic columns) — **permitted**, one-time
3. **Semantic revision** (changing already-enriched values) — **uses `supersedes`**: new node replaces old

---

## 4. Enrichment Pipeline

### 4.1 Context Window: Empirical Foundation

The enrichment LLM needs surrounding context to produce useful `intent` and `rationale` for a trail node. The context window was determined empirically through a series of experiments against production data.

#### Ring Buffer

StepTracker maintains a **10-entry ring buffer** per job (`_BUFFER_SIZE = 10`). This is the sliding window of non-delta transcript entries. Excluded roles: `agent_delta`, `reasoning_delta`, `tool_output_delta`, `tool_running` — streaming fragments that carry no standalone meaning.

Each entry's content is truncated at **800 characters** (`_TRANSCRIPT_CONTENT_MAX`).

#### Experiments (tools/)

**`context_window_eval.py`** — Tested window sizes [3, 5, 7, 8, 9, 10, 11, 12, 13, 15, 20, 30] against production step data. Measured four coverage signals per window size:
- **Target file coverage**: Does the window mention files that the step actually wrote?
- **Motivation coverage**: Does it contain problem-identification language explaining *why*?
- **Agent reasoning coverage**: Does it contain substantive agent messages (>20 chars)?
- **Explicit intent coverage**: Does it contain `report_intent` tool calls?

Results at key sizes:
- **Size 5**: 85.0% file coverage, 61.0% motivation
- **Size 10**: 92.5% file coverage, 79.4% motivation

Inflection point: marginal gains drop below 1–2% per additional entry beyond 10.

**`context_snapshot_eval.py`** — Measured information density per buffer position. Positions [-1] through [-8] (most recent 8) carry nearly all signal. Positions [-9] and [-10] rarely contain file mentions or motivation language — storing them wastes tokens and storage.

**`motivation_distance.py`** — Measured how far back you must go to find the causal motivation for a file write. Searches backwards through transcript for problem-identification language (~40 terms: bug, issue, vulnerability, missing, broken, fix, error, etc.) and file-name mentions.

**`content_max_eval.py`** — Validated the 800-char truncation. Measured raw content sizes before truncation, frequency of truncation, and whether truncated tails contain file paths or other important signals.

**`drain_rate_eval_v2.py`** — Modeled parallel enrichment batch processing. Tested batch configurations: (5, 3s), (5, 5s), (10, 3s), (10, 5s), (10, 10s), (20, 5s), (20, 10s), (30, 10s). Measured haiku call latencies: P50, P90, P95. Key finding: parallel batches take `max(N calls)` not `sum`, so batch size affects latency sublinearly.

#### Deployed Values

| Parameter | Value | Source |
|-----------|-------|--------|
| Ring buffer size | 10 entries | `context_window_eval.py` inflection point |
| Snapshot persisted | 8 entries (last 8 of 10) | `context_snapshot_eval.py` density analysis |
| Content truncation | 800 chars/entry | `content_max_eval.py` signal-loss analysis |
| Enrichment batch size | 20 nodes/cycle | `drain_rate_eval_v2.py` + `TrailConfig` |
| Drain loop interval | 10 seconds | `TrailConfig.enrich_interval_seconds` |
| Decisions context | 5 recent decisions | `TrailConfig.enrich_decisions_context` |
| Max retries | 10 | `TrailConfig.enrich_max_retries` |
| Preceding context (adapter-level) | 5 turns | `base_adapter._snapshot_preceding_context()` |

### 4.2 Drain Loop

TrailService runs a background `drain_loop()` that processes pending trail nodes:

```
drain_loop() (every 10s) → drain_enrichment() → SisterSessionManager (gpt-4o-mini)
                                                   │
                                                   ├── _generate_turn_title()
                                                   ├── _resolve_activity_boundary()
                                                   └── _classify_and_emit()
```

**Sister sessions** are per-job cheap LLM sessions. Each enrichment request is self-contained: the target node plus its preceding context snapshot (8 entries) plus the last 5 decisions. No conversational state across calls — each batch is independently processable.

Nodes flow through states: `pending` → `complete` (or `failed`).

### 4.3 Enrichment Failure

| Failure | Recovery |
|---------|----------|
| Timeout / rate limit | Node stays `pending`, retried next cycle (up to 10 retries) |
| Unparseable response | Node marked `failed`, skipped. UI degrades gracefully. |
| LLM contradicts deterministic trigger | Deterministic trigger wins (hard-coded priority in `_resolve_activity_boundary()`) |

Enrichment failure is never catastrophic. Structure remains intact. Semantic fields degrade to "unavailable."

---

## 5. Data Model

### 5.1 TrailNodeRow (Canonical Record)

The `trail_nodes` table is the single persisted artifact. Columns grouped by category:

**Identity & Ordering**: `id`, `job_id`, `seq`, `anchor_seq`, `parent_id`, `timestamp`

**Deterministic Facts**: `kind`, `deterministic_kind`, `phase`, `step_id`, `turn_id`, `files`, `start_sha`, `end_sha`, `tool_names`, `tool_count`, `duration_ms`, `preceding_context`, `agent_message`, `span_ids`

**Semantic Enrichment**: `enrichment` (status), `intent`, `rationale`, `outcome`, `title`, `plan_item_id`, `plan_item_label`, `plan_item_status`, `activity_id`, `activity_label`, `supersedes`, `tags`

### 5.2 Column Notes

**`kind` vs. `deterministic_kind`**: Both columns carry values from the same taxonomy. `deterministic_kind` is set at creation and never changes — it records what the node builder classified the step as. `kind` starts equal to `deterministic_kind` but may be overwritten by the enricher to a semantic kind when enrichment produces a reclassification (e.g., a `modify` node that the enricher determines was really a `backtrack`).

**Deterministic kinds** (set by NodeBuilder at creation): `goal`, `explore`, `modify`, `shell`, `request`, `summarize`, `delegate`.

**Semantic kinds** (set by Enricher asynchronously): `plan`, `insight`, `decide`, `backtrack`, `verify`.

The `_classify_step()` function in NodeBuilder returns `modify` (files written), `explore` (read-only file access), or `shell` (command execution). `goal` is the initial job node. `request` is an operator approval interaction. `summarize` is a session-end summary node. `delegate` is a sub-agent spawn.

**`seq` vs. `anchor_seq`**: `seq` is monotonic insertion order — never changes. `anchor_seq` is canonical display order — accounts for retroactive insertions (e.g., a synthetic step node created after its child actions). For most nodes: `anchor_seq == seq`.

**`preceding_context`**: JSON blob. Ring buffer snapshot at node creation time. Self-contained context for enrichment (no joins needed). Storage cost: O(8 entries × 800 chars × node_count). Intentional trade-off: enrichment simplicity over storage efficiency.

### 5.3 CQRS Projections

The trail is the write-side authority. Read-side projections include:

| Projection | Table/Mechanism | Refresh Trigger | Consumers |
|------------|----------------|-----------------|-----------|
| Steps | `steps` table via `StepPersistenceSubscriber` | `step_completed` event | Frontend (step diff view) |
| Activities | `activity_id`/`activity_label` on trail nodes | Enrichment drain | Frontend (activity timeline) |
| Plan items | `plan_item_*` on trail nodes | `agent_plan_updated` event | Frontend (plan overlay) |
| SSE stream | Event bus → SSE push | All trail domain events | Frontend (live updates) |
| Trail API | `TrailRepository` queries | On-demand | Frontend (history), debugging |
| Changed files | `TrailNodeRepository.get_all_changed_files()` | On-demand | RuntimeHandoff, CostAttribution |

All projections are disposable — they can be rebuilt from trail nodes at any time. The `steps` table is a textbook CQRS read-model: `StepPersistenceSubscriber` subscribes to `step_completed` events and writes denormalized step records.

---

## 6. Downstream Consumers

Every service that needs to understand what the agent did reads from the trail or its projections. This section catalogs all consumers and their access patterns.

### 6.1 Compliant Consumers

These services correctly read adapted projections:

| Service | What it reads | Access pattern |
|---------|--------------|----------------|
| **RuntimeHandoffService** | `TrailNodeRepository.get_all_changed_files()` | Changed file manifest for session handoff |
| **Frontend (SSE)** | Domain events from event bus | Real-time stream of typed events |
| **Frontend (Trail API)** | `TrailNodeRow` via TrailRepository | Paginated node queries for history |
| **ConsoleDashboard** | Domain events from event bus | Terminal display (side-effect-free) |

### 6.2 Violating Consumers

These services bypass the trail and access raw data directly:

**CostAttributionService** — executes raw SQL directly on the `trail_nodes` table (`SELECT SUM(diff_additions) ... FROM trail_nodes`) instead of going through `TrailNodeRepository`. This bypasses the repository abstraction.
*Migration*: Add `TrailNodeRepository.get_diff_line_counts()` and call it instead.

**SummarizationService** (`save_snapshot_to_disk`) — queries `EventRepository` for `transcript_updated` and `diff_updated` events to build session snapshots. Needs per-turn tool metadata (`tool_display`, `tool_intent`, `tool_success`) that trail nodes don't carry yet.
*Migration*: Deferred — requires trail nodes to carry per-tool-call metadata (see §13.3). Already has a `TODO(trail-migration)` comment.

**StoryService** — runs 6 raw SQL queries against `job_telemetry_spans`, `trail_nodes`, `steps`, `jobs`, `job_telemetry_summary`, and `approvals`. Builds narrative from raw span data, extracting snippets from `tool_args_json` and deduplicating file writes by file+step. The most complex violator.
*Migration*: Deferred — `write` sub-nodes now exist (§13.1). Consumer migration to read from `TrailNodeRepository.get_write_nodes_for_job()` instead of raw SQL on `job_telemetry_spans` is next.

**MotivationService** — runs an independent drain loop parsing `preceding_context` and `tool_args_json` from `job_telemetry_spans`. Produces `motivation_summary` (file-level) and `edit_motivations` (edit-level). Duplicates work the trail enricher should own.
*Migration*: Fold into trail enrichment (see §13.2). `write` sub-nodes now exist (§13.1); ready for enricher absorption.

**JobService** — wraps `EventRepository` and exposes `list_events_by_job()`, `get_latest_progress_preview()`, and `list_latest_progress_previews()`. Used by API routes (`job_artifacts.py`) to serve transcript, diff, plan step, progress headline, and log events to the frontend.
*Migration*: Phased. Infrastructure events (`log_line_emitted`) are acceptable per §6.3. Provenance events (`transcript_updated`, `diff_updated`, `plan_step_updated`, `progress_headline`) need trail-backed API endpoints. Requires per-turn transcript data in trail.

**SSE Manager** — queries `EventRepository` for replay on client reconnect (`list_after()`, `list_latest_progress_previews()`). Fills initial state for late-joining clients.
*Migration*: Deferred — SSE replay is the event bus's read model and currently depends on the raw event store's auto-increment cursor for ordering. Replacing this requires trail to publish replayable event IDs.

**job_artifacts.py** (`search_transcript`) — directly injects `EventRepository` via DI for full-text transcript search. Searches `content`, `tool_name`, `tool_display` fields in `transcript_updated` event payloads.
*Migration*: Requires a search projection on trail nodes or a dedicated search index.

### 6.3 Acceptable Exception: RuntimeTelemetry

RuntimeTelemetry queries `EventRepository` for `log_line_emitted` events. This is acceptable because log lines are **infrastructure telemetry**, not semantic provenance.

**Provenance boundary test**: "Would removing this event change our understanding of what the agent decided and why?" If no, it is infrastructure.

| Event | Classification | Rationale |
|-------|---------------|-----------|
| `transcript_updated` | Provenance | Agent reasoning — semantic |
| `tool_call` | Provenance | Agent decision — semantic |
| `diff_updated` | Provenance | Workspace state change — semantic |
| `log_line_emitted` | Infrastructure | Process stdout/stderr — operational |
| `session_heartbeat` | Infrastructure | Liveness signal — operational |

---

## 7. Implementation Plan

Three phases, executed sequentially. Phases 1 and 2b are complete. Each phase is independently shippable — the system is correct after every phase, just not fully consolidated until Phase 3.

### Phase 1: Trail Projection Methods ✅ COMPLETE

**Status**: Shipped. All projection methods exist in `backend/persistence/trail_repo.py` with tests in `backend/tests/unit/test_trail_repo_projections.py`.

Implemented methods:
- `get_transcript_nodes(job_id, *, limit)` — nodes carrying conversational content
- `get_file_changes_by_step(job_id)` — step nodes with file manifests (kinds: `modify`, `shell`, `explore`)
- `get_latest_step_boundary(job_id)` — most recent step node with file info
- `get_all_changed_files(job_id)` — union of file paths across all steps
- `get_diff_line_counts(job_id)` — aggregate `diff_additions`/`diff_deletions` sums

Note: The original design proposed filtering by `kind='step'` and `kind='transcript_segment'`. Those kinds don't exist. Actual step kinds are `modify`, `shell`, `explore`. Transcript content lives on `agent_message` and `intent` fields, not on a separate node kind.

---

### Phase 2: Migrate Consumers

**Goal**: Switch each violating service from raw access to TrailNodeRepository. Each service is migrated independently.

#### 2a. CostAttributionService ✅ COMPLETE

**File**: `backend/services/cost_attribution.py`
**Method**: `_compute_attribution()` (~line 333)

**What changed**: Replaced inline raw SQL (`SELECT SUM(diff_additions) ... FROM trail_nodes`) with `TrailNodeRepository.get_diff_line_counts(job_id)`. The function signature now accepts a `session_factory` parameter to construct the repository.

**Before** (raw SQL):

```python
from sqlalchemy import text as sa_text
result = await session.execute(
    sa_text(
        "SELECT COALESCE(SUM(diff_additions), 0) AS added, "
        "COALESCE(SUM(diff_deletions), 0) AS removed "
        "FROM trail_nodes WHERE job_id = :job_id"
    ),
    {"job_id": job_id},
)
```

**After** (repository):

```python
from backend.persistence.trail_repo import TrailNodeRepository
trail_repo = TrailNodeRepository(session_factory)
diff_added, diff_removed = await trail_repo.get_diff_line_counts(job_id)
```

#### 2b. RuntimeHandoffService ✅ COMPLETE

**Status**: Already migrated. `runtime_handoff.py` uses `TrailNodeRepository.get_all_changed_files()`. No `EventRepository` import exists in this file.

#### 2c. SummarizationService — `save_snapshot_to_disk()` ⏳ DEFERRED

**File**: `backend/services/summarization_service.py`
**Reason**: The snapshot builder preserves per-turn tool metadata (`tool_name`, `tool_display`, `tool_intent`, `tool_success`) from `transcript_updated` events. The columns exist on `TrailNodeRow` (migration 0029) but are NULL — NodeBuilder does not yet handle `transcript_updated` events with `role='tool_call'` to populate them. Blocked on §13.3.

The method already has a `# TODO(trail-migration)` comment. The `changed_files` path could be migrated independently using `get_all_changed_files()`, but the transcript path remains blocked.

#### 2d. StoryService ✅ COMPLETE

**Implementation**: `_build_references()` migrated from raw SQL on `job_telemetry_spans` to SQLAlchemy queries on `TrailNodeRow` write sub-nodes. `_build_trail_beats()` migrated from raw SQL to SQLAlchemy queries on semantic trail nodes. Staleness guard updated to check `trail_nodes` (write_summary IS NULL) instead of `job_telemetry_spans` (motivation_summary IS NULL). Removed dead `_extract_snippet()` function (now pre-computed on write sub-nodes).

#### 2e. MotivationService ✅ COMPLETE

**Implementation**: Both motivation passes folded into `TrailEnricher` (§13.2). The old MotivationService continues running on telemetry spans for backward compatibility. New trail-based drains operate on write sub-nodes.

#### 2f. JobService / API Routes — ℹ️ NO MIGRATION NEEDED

**Analysis**: `JobService.list_events_by_job()` serves raw event payloads to frontend API routes (`/transcript`, `/diff`, `/steps`, `/timeline`). These are infrastructure events (progress_headline, transcript_updated, log_line) not provenance data. Per §6.3, infrastructure events remain in EventRepository. No migration needed.

#### 2g. SSE Manager — ℹ️ NO MIGRATION NEEDED

**Analysis**: SSE replay depends on `EventRepository.list_after()` which uses the raw event store's auto-increment `db_id` as a cursor. These are infrastructure/real-time events (state changes, progress updates, log lines). Per §6.3, infrastructure events remain in EventRepository. No migration needed.

---

### Phase 3: Enforce Boundary ✅ COMPLETE

**Status**: Shipped. Architecture test exists at `backend/tests/unit/test_architecture.py`.

The test parses ASTs and verifies that only allowlisted modules import `EventRepository`. Test files are excluded. The current allowlist includes all modules that legitimately use `EventRepository` today:

```python
ALLOWED_EVENT_REPO_CONSUMERS = {
    "backend/persistence/event_repo.py",          # self
    "backend/services/trail/service.py",           # rehydration on session_resumed
    "backend/services/trail/node_builder.py",      # rehydration on session_resumed
    "backend/services/runtime_service.py",         # hot-path event translation
    "backend/services/runtime_telemetry.py",       # infrastructure: log_line_emitted
    "backend/services/summarization_service.py",   # deferred Phase 2c
    "backend/di.py",                               # DI wiring
    "backend/lifespan.py",                         # lifecycle wiring
    "backend/api/job_artifacts.py",                # deferred Phase 2f
    "backend/services/job_service.py",             # deferred Phase 2f
    "backend/services/sse_manager.py",             # deferred Phase 2g
}
```

As deferred migrations complete, entries are removed from the allowlist.

---

### Phase Summary

| Phase | Scope | Status | Files changed |
|-------|-------|--------|---------------|
| 1 | Trail projection methods | ✅ Done | `trail_repo.py`, `test_trail_repo_projections.py` |
| 2a | CostAttribution: raw SQL → repo | ✅ Done | `cost_attribution.py`, `trail_repo.py` |
| 2b | RuntimeHandoff → trail repo | ✅ Done | `runtime_handoff.py` |
| 2c | SummarizationService snapshot | ⏳ Deferred | Needs per-tool metadata populated on write sub-nodes |
| 2d | StoryService | ⏳ Deferred | Write sub-nodes exist; needs consumer migration |
| 2e | MotivationService | ⏳ Deferred | Write sub-nodes exist; fold into enricher (§13.2) |
| 2f | JobService / API routes | ⏳ Deferred | Needs per-turn trail data |
| 2g | SSE Manager replay | ⏳ Deferred | Needs replayable trail cursor |
| 3 | Import guard test | ✅ Done | `test_architecture.py` |

```python
class EventRepository:
    """Raw event persistence. Direct consumers: RuntimeService, TrailService,
    RuntimeTelemetry (log lines). All other services must use
    TrailNodeRepository projections. See internal-docs/design/unified-trail-service.md §6."""
```

---

## 8. System Relationships

### RuntimeService

The **adapter translator**. Converts raw `SessionEvent` objects into `DomainEvent` objects. Owns: event processing loop, phase state machine, approval orchestration, Git operations (via GitService). Does NOT own provenance.

### StepTracker

A **structural pre-processor**. Operates on already-translated DomainEvents — never queries EventRepository. Detects step boundaries (turn changes, operator messages) and emits `step_completed` events. Does not assign semantic meaning, group into activities, or manage plans.

### Event Bus

The **distribution fabric**. TrailService publishes domain events; subscribers receive adapted projections. Stateless notification channel.

### SisterSessionManager

The **enrichment substrate**. Provides per-job cheap LLM sessions (gpt-4o-mini) that TrailService uses for semantic inference. No independent knowledge of the trail.

---

## 9. Lifecycle

### 9.1 Wiring (lifespan.py)

```python
trail_service = TrailService(session_factory, event_bus, sister_sessions, config)
event_bus.subscribe(trail_service.handle_event)
asyncio.create_task(trail_service.drain_loop())
```

### 9.2 Recovery

On crash recovery (`session_resumed`):
- TrailService reconstructs `_TrailJobState` from persisted trail nodes (event sourcing replay)
- Nodes with `enrichment='failed'` are eligible for retry by the drain loop
- Drain loop resumes and resubmits pending nodes
- StepTracker starts fresh (forward-only state)
- Sister sessions are stateless per-batch — no conversational context to lose

**Lossy recovery**: Reconstruction from trail nodes is incomplete. The following transient state is lost on crash: `recent_messages`, `recent_tool_intents`, `recent_tool_names`, `tool_call_count`, `current_phase`, `last_classified_plan_item`, and `sister_consecutive_failures`. Post-recovery, plan classification and activity boundary detection degrade because these context buffers are empty. This is a known gap (see §13.5).

---

## 10. Design Constraints

1. **No raw event leakage**: No service outside TrailService/RuntimeService may query `EventRepository` for provenance events. (Infrastructure events excepted per §6.3.)

2. **No enrichment on hot path**: LLM calls never block event processing. Structure is synchronous; meaning is asynchronous.

3. **Deterministic facts are immutable**: Once a trail node's structural fields are set, they never change.

4. **Enrichment fill, not mutation**: Semantic columns are written once from NULL. Revisions create new nodes via `supersedes`.

5. **No event bus feedback loops**: No subscriber of TrailService-published events may trigger actions that feed back into TrailService's ingestion path.

6. **Single-writer ordering**: Each job has exactly one sequential RuntimeService event loop. `seq` is trivially ordered — no locks, no races. Multi-agent would require Lamport timestamps. **Caveat**: `asyncio.ensure_future()` in `_classify_and_emit()` and `_refine_activity_label()` creates fire-and-forget tasks that mutate `TrailJobState` concurrently (`plan_steps`, `active_idx`, `activities`, `activity_steps`). Two rapid `step_completed` events can trigger overlapping state mutations. This is a known gap (see §13.4).

---

## 11. Appendix: Event Sourcing Alignment

| Fowler Concept | CodePlane Equivalent |
|----------------|---------------------|
| Event Log | `trail_nodes` table (append-only, ordered by `seq`) |
| Application State | `_TrailJobState` in-memory (derivable from trail) |
| Event Processor | `TrailService.handle_event()` |
| Complete Rebuild | Replay from trail nodes on `session_resumed` |
| Temporal Query | Query trail nodes by timestamp/seq range |
| External Gateway | SisterSessionManager (stateless per-batch, safe for replay) |
| Snapshot | Latest `step_completed` node as implicit checkpoint |
| CQRS Read Model | `steps` table, Zustand store, TrailRepository queries |
| CQRS Write Model | TrailService command handlers (`feed_*`, `handle_event`) |

---

## 12. Appendix: Domain Event Taxonomy

Events published by the trail subsystem:

| Event | Producer | Trigger |
|-------|----------|---------|
| `StepStarted` | TrailService | New step boundary |
| `StepCompleted` | StepTracker → TrailService | Step closes |
| `StepTitleGenerated` | TrailService (drain) | Enrichment produces title |
| `StepGroupUpdated` | TrailService (drain) | Activity boundary resolved |
| `PlanStepUpdated` | TrailService | Agent plan change |
| `AgentPlanUpdated` | TrailService | Full plan snapshot |
| `StepEntriesReassigned` | TrailService | Retroactive regrouping |
| `TurnSummary` | TrailService (drain) | Turn summarized |
| `ExecutionPhaseChanged` | RuntimeService | Phase transition |
| `ProgressHeadline` | TrailService | High-level status |

---

## 13. Known Gaps & Future Work

### 13.1 Write Sub-Nodes (Granularity Bridge) — ✅ IMPLEMENTED

Trail nodes are per-step — one node per `step_completed` event. Telemetry spans are per-tool-call — one span per `file_write`, `shell_exec`, etc. A single step can have multiple file writes. Trail knows "which files" (the `files` JSON array) but not "what changed in each file."

**Implementation**: A `write` node kind, created as children of `modify` nodes during `_on_step_completed`. One per `file_write` telemetry span. Columns added to `trail_nodes` (migration 0029): `tool_name`, `snippet`, `is_retry`, `error_kind`, `write_summary`, `edit_motivations`, `tool_display`, `tool_intent`, `tool_success`. NodeBuilder queries `TelemetrySpansRepository.file_write_spans_for_step()` and batch-inserts write sub-nodes via `TrailNodeRepository.create_many()`. Projection methods: `get_write_nodes_for_step()`, `get_write_nodes_for_job()`.

**Unblocked consumers**: StoryService (per-file snippets), MotivationService (per-edit motivations), SummarizationService (per-tool metadata columns exist, need population).

### 13.2 MotivationService Absorption — ✅ IMPLEMENTED

MotivationService runs an independent drain loop on `job_telemetry_spans`, duplicating the trail enricher's cognitive work at a different granularity. Two passes: file-level (`preceding_context` → `motivation_summary`) and edit-level (`tool_args` → `edit_motivations`).

**Implementation**: Both passes folded into `TrailEnricher`. File-level motivations are enrichment on `write` sub-nodes via `drain_write_summaries()`. Edit-level motivations are enrichment on `write` sub-nodes via `drain_edit_motivations()`. The old MotivationService drain loop runs in parallel for backward compatibility on telemetry spans. New `TrailNodeRepository` methods: `get_unsummarized_write_nodes()`, `get_unenriched_edit_write_nodes()`, `set_write_summary()`, `set_edit_motivations()`.

### 13.3 Per-Tool Metadata on Trail Nodes

`SummarizationService.save_snapshot_to_disk()` preserves per-turn tool metadata: `tool_display`, `tool_intent`, `tool_success`. Trail nodes carry `tool_names` (JSON array of names) but not the per-call display/intent/success metadata.

**Decision**: Derive from `write` sub-nodes (§13.1). Each `write` node already carries `tool_name` and per-call context. Columns `tool_display`, `tool_intent`, `tool_success` exist on `trail_nodes` (added in migration 0029). Currently NULL — population requires NodeBuilder to handle `transcript_updated` events with `role='tool_call'` to extract tool metadata. SummarizationService migration (Phase 2c) is blocked pending this.

### 13.4 Fire-and-Forget Concurrency — ✅ IMPLEMENTED

`asyncio.ensure_future()` in `_classify_and_emit()` and `_refine_activity_label()` creates unguarded concurrent mutations on `TrailJobState`. Two rapid `step_completed` events race on `plan_steps`, `active_idx`, `activities`, and `activity_steps`.

**Implementation**: Converted fire-and-forget to awaited calls in both `node_builder.py` and `activity_tracker.py`. Removed `import asyncio` from both modules.

### 13.5 Split-Brain Recovery — ✅ IMPLEMENTED

`TrailJobState` is reconstructed from persisted trail nodes on `session_resumed`, but recovery is lossy. The following transient state cannot be recovered: `recent_messages`, `recent_tool_intents`, `recent_tool_names`, `tool_call_count`, `current_phase`, `last_classified_plan_item`, `sister_consecutive_failures`.

**Implementation**: Added `trail_state_snapshot` TEXT column to `jobs` table (migration 0030). `TrailJobState.to_snapshot()` / `from_snapshot()` serialize/deserialize all transient state including context buffers. Snapshot saved on every `step_completed` and on terminal events. On `session_resumed`, snapshot is loaded first (lossless) with fallback to lossy reconstruction.

### 13.6 Activity Label Persistence — ✅ IMPLEMENTED

`_refine_activity_label()` updates the in-memory `Activity.label` and emits an SSE event, but the refined label is never written back to the `trail_nodes` rows that belong to that activity. The `activity_label` column on those nodes remains stale.

**Implementation**: Added `_persist_activity_label()` method to `ActivityTracker`. After SSE publish, issues `UPDATE trail_nodes SET activity_label = :new WHERE job_id = :jid AND activity_id = :aid`.

### 13.7 Shallow Activity Boundaries — ✅ IMPLEMENTED

Activity boundaries are detected solely by `assigned_plan_step_id` change. This misses: file cluster shifts (agent moves from backend to frontend files), operator redirects (chat message changes focus), and semantic intent shifts. When no plan exists, no boundaries are detected at all.

**Implementation**: Multi-signal boundary detection in `_resolve_activity_boundary()`:
1. **Plan step change** (original signal, unchanged)
2. **Operator redirect** — operator messages tracked in `recent_messages` buffer with `[operator]` prefix; triggers new activity on next step
3. **File cluster divergence** — compares top-level directories of current vs. previous files; no overlap triggers new activity
4. NodeBuilder populates `recent_messages` from `transcript_updated` events with operator/user role
