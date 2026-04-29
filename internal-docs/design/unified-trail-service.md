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
    step_tracker.on_transcript_event(domain_event)        # structural
```

Each raw `SessionEvent` from the agent adapter is:
1. Translated into a `DomainEvent` by RuntimeService
2. Fed to TrailService (semantic provenance) and StepTracker (structural boundaries)
3. Persisted as a `TrailNodeRow` with deterministic fields filled immediately

### 2.2 Step Completion (Batched)

StepTracker detects step boundaries from structural signals (new `turn_id`, operator message, job start) and emits `step_completed` events via the event bus. TrailService subscribes and creates synthetic `step` trail nodes with Git SHA boundaries and metadata.

### 2.3 Plan Ingestion

When the agent calls plan-management tools (`manage_todo_list`, `TodoWrite`), RuntimeService calls `trail_service.ingest_native_plan()`. TrailService also runs `_infer_plan()` when no native plan exists. Plan data populates `plan_item_*` columns on trail nodes.

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
| `outcome`, `outcome_status` | LLM inference: what was the result? |
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

Nodes flow through states: `pending` → `in_progress` → `done` (or `failed`).

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

**Semantic Enrichment**: `enrichment` (status), `intent`, `rationale`, `outcome`, `outcome_status`, `title`, `plan_item_id`, `plan_item_label`, `plan_item_status`, `activity_id`, `activity_label`, `supersedes`, `tags`

### 5.2 Column Notes

**`kind` vs. `deterministic_kind`**: `kind` is the raw node type at ingestion (`tool_call`, `tool_result`, `transcript_segment`, `step`). `deterministic_kind` is a nullable collapsed classification for grouping — when multiple raw kinds should be treated identically for presentation (e.g., `tool_call` + `tool_result` → `tool_interaction`). When NULL, equals `kind`. Decouples raw classification (stable for replay) from presentation (may evolve).

**`seq` vs. `anchor_seq`**: `seq` is monotonic insertion order — never changes. `anchor_seq` is canonical display order — accounts for retroactive insertions (e.g., a synthetic step node created after its child actions). For most nodes: `anchor_seq == seq`.

**`preceding_context`**: JSON blob. Ring buffer snapshot at node creation time. Self-contained context for enrichment (no joins needed). Storage cost: O(8 entries × 800 chars × node_count). Intentional trade-off: enrichment simplicity over storage efficiency.

### 5.3 CQRS Projections

The trail is the write-side authority. Read-side projections include:

| Projection | Table/Mechanism | Refresh Trigger | Consumers |
|------------|----------------|-----------------|-----------|
| Steps | `steps` table via `StepPersistenceSubscriber` | `step_completed` event | StoryService, MotivationService |
| Activities | `activity_id`/`activity_label` on trail nodes | Enrichment drain | Frontend (activity timeline) |
| Plan items | `plan_item_*` on trail nodes | `agent_plan_updated` event | Frontend (plan overlay) |
| SSE stream | Event bus → SSE push | All trail domain events | Frontend (live updates) |
| Trail API | `TrailRepository` queries | On-demand | Frontend (history), debugging |

All projections are disposable — they can be rebuilt from trail nodes at any time. The `steps` table is a textbook CQRS read-model: `StepPersistenceSubscriber` subscribes to `step_completed` events and writes denormalized step records for StoryService and MotivationService to query.

---

## 6. Downstream Consumers

Every service that needs to understand what the agent did reads from the trail or its projections. This section catalogs all consumers and their access patterns.

### 6.1 Compliant Consumers

These services correctly read adapted projections:

| Service | What it reads | Access pattern |
|---------|--------------|----------------|
| **StoryService** | `telemetry_spans` + `steps` tables | Aggregated timeline for job story view |
| **MotivationService** | `telemetry_spans` table | Progress metrics and pacing |
| **Frontend (SSE)** | Domain events from event bus | Real-time stream of typed events |
| **Frontend (Trail API)** | `TrailNodeRow` via TrailRepository | Paginated node queries for history |
| **ConsoleDashboard** | Domain events from event bus | Terminal display (side-effect-free) |

### 6.2 Violating Consumers

These services bypass the trail and query `EventRepository` directly for raw session events:

**SummarizationService** — queries `transcript_updated` events.
*Migration*: Subscribe to `TurnSummary` domain events or query `trail_nodes` with `kind='transcript_segment'`.

**CostAttributionService** — queries `diff_updated` events.
*Migration*: Read trail nodes with `files` and `step_id` columns. Cost attributed per-step via Git boundaries.

**RuntimeHandoffService** — queries `diff_updated` events during handoff.
*Migration*: Read latest `step` trail nodes for `end_sha` and file manifest.

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

Three phases, executed sequentially. Each phase is independently shippable — the system is correct after every phase, just not fully consolidated until Phase 3.

### Phase 1: Trail Projection Methods

**Goal**: Give consumers trail-backed alternatives to EventRepository queries without changing any consumer yet. Zero behavioral change — purely additive.

#### 1a. `TrailNodeRepository.get_transcript_nodes()`

**File**: `backend/persistence/trail_repo.py`

**Signature**:

```python
async def get_transcript_nodes(
    self,
    job_id: str,
    *,
    roles: list[str] | None = None,
    limit: int | None = None,
) -> list[TrailNodeRow]:
    """Fetch trail nodes that carry transcript content for a job.

    Filters to node kinds that represent agent/operator transcript
    segments (not tool scaffolding, not step boundaries). Ordered by
    (anchor_seq, seq) for chronological replay.

    Used by: SummarizationService (replaces EventRepository.list_by_job
    with kinds=[transcript_updated]).
    """
```

**Implementation**:

```python
async with self._session_factory() as session:
    stmt = (
        select(TrailNodeRow)
        .where(TrailNodeRow.job_id == job_id)
        .where(TrailNodeRow.kind.in_(["transcript_segment", "agent_message"]))
    )
    if roles:
        # Filter via JSON field extraction if roles specified
        # TrailNodeRow stores role in the 'phase' or embedded in preceding_context
        # Actual filter TBD based on how role is stored on transcript nodes
        pass
    stmt = stmt.order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

**Data contract**: SummarizationService currently extracts `role`, `content`, and `timestamp` from event payloads. Trail nodes carry `agent_message` (content), `timestamp`, and `phase` (can encode role). The node's `kind` already distinguishes agent vs. operator messages. If the current trail node schema doesn't carry role explicitly, add a `role` column to `TrailNodeRow` — this is a schema addition, not a mutation of existing data.

**Open question**: Verify whether `TrailNodeRow` already encodes the transcript role somewhere (in `kind`, `phase`, or `preceding_context`). If not, this is a schema migration item (1b).

#### 1b. Schema Migration (if needed)

If trail nodes don't carry `role` for transcript segments, add a nullable `role` column:

**File**: `alembic/versions/XXXX_add_role_to_trail_nodes.py`

```python
def upgrade():
    op.add_column("trail_nodes", sa.Column("role", sa.String(20), nullable=True))

def downgrade():
    op.drop_column("trail_nodes", "role")
```

TrailService's node builder must populate `role` on creation. Existing nodes get NULL (acceptable — migration only affects new data; summarization of old jobs uses the `pre_built_transcript` path).

#### 1c. `TrailNodeRepository.get_file_changes_by_step()`

**File**: `backend/persistence/trail_repo.py`

**Signature**:

```python
async def get_file_changes_by_step(
    self,
    job_id: str,
) -> list[TrailNodeRow]:
    """Fetch step-boundary trail nodes that carry file manifests.

    Returns nodes with kind='step' ordered chronologically. Each node's
    `files` JSON array contains the file paths touched in that step.
    `start_sha` and `end_sha` bracket the Git state change.

    Used by: CostAttributionService (replaces EventRepository.list_by_job
    with kinds=[diff_updated]).
    """
```

**Implementation**:

```python
async with self._session_factory() as session:
    stmt = (
        select(TrailNodeRow)
        .where(TrailNodeRow.job_id == job_id)
        .where(TrailNodeRow.kind == "step")
        .where(TrailNodeRow.files.isnot(None))
        .order_by(TrailNodeRow.anchor_seq, TrailNodeRow.seq)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

**Data contract**: CostAttributionService currently extracts `additions` and `deletions` per file from `diff_updated` events. Step nodes carry `files` (list of paths) and Git SHAs (`start_sha`, `end_sha`) but NOT per-file line counts. Two options:

- **Option A (recommended)**: CostAttributionService derives line counts from `git diff --stat start_sha..end_sha` using GitService. This is more accurate than the event payload (which may be stale if multiple diffs fired).
- **Option B**: Embed `additions`/`deletions` per file in the step node's `files` JSON. Requires changing the `files` schema from `["path1", "path2"]` to `[{"path": "path1", "additions": 10, "deletions": 3}, ...]`.

**Decision**: Option A. Keeps trail nodes simpler; cost attribution already runs post-hoc.

#### 1d. `TrailNodeRepository.get_latest_step_boundary()`

**File**: `backend/persistence/trail_repo.py`

**Signature**:

```python
async def get_latest_step_boundary(
    self,
    job_id: str,
) -> TrailNodeRow | None:
    """Fetch the most recent step node for a job.

    Returns the step with the highest seq. Carries `end_sha` (latest
    committed state) and `files` (cumulative file manifest).

    Used by: RuntimeHandoffService (replaces EventRepository.list_by_job
    with kinds=[diff_updated]).
    """
```

**Implementation**:

```python
async with self._session_factory() as session:
    stmt = (
        select(TrailNodeRow)
        .where(TrailNodeRow.job_id == job_id)
        .where(TrailNodeRow.kind == "step")
        .order_by(TrailNodeRow.seq.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
```

**Data contract**: RuntimeHandoffService needs changed file paths. The latest step node's `files` gives paths for that step only. For cumulative changed files across all steps, the handoff must union files from all step nodes — use `get_file_changes_by_step()` and union the `files` arrays.

#### 1e. `TrailNodeRepository.get_all_changed_files()`

**File**: `backend/persistence/trail_repo.py`

Convenience method that unions file paths across all step nodes:

```python
async def get_all_changed_files(self, job_id: str) -> list[str]:
    """Return sorted unique file paths changed across all steps in a job."""
    step_nodes = await self.get_file_changes_by_step(job_id)
    paths: set[str] = set()
    for node in step_nodes:
        if node.files:
            for path in json.loads(node.files):
                if isinstance(path, str):
                    paths.add(path)
                elif isinstance(path, dict):
                    p = path.get("path", "")
                    if p:
                        paths.add(p)
    return sorted(paths)
```

#### 1f. Testing

**File**: `backend/tests/unit/test_trail_repo_projections.py`

For each new method:
- Insert known trail nodes via `create_many()`
- Call projection method
- Assert correct filtering, ordering, and data extraction
- Test empty-job case (returns `[]` or `None`)
- Test mixed node kinds (only `step`/`transcript_segment` returned)

---

### Phase 2: Migrate Consumers

**Goal**: Switch each violating service from EventRepository to TrailNodeRepository. Each service is migrated independently — order doesn't matter.

#### 2a. CostAttributionService

**File**: `backend/services/cost_attribution.py`  
**Method**: `_compute_attribution()` (~line 333)

**Current code** (to replace):

```python
from backend.persistence.event_repo import EventRepository
event_repo = EventRepository(session)
diff_events = await event_repo.list_by_job(
    job_id, kinds=[DomainEventKind.diff_updated], limit=100,
)
if diff_events:
    changed_files = diff_events[-1].payload.get("changed_files", [])
    for f in changed_files:
        diff_added += f.get("additions", 0)
        diff_removed += f.get("deletions", 0)
```

**New code**:

```python
from backend.persistence.trail_repo import TrailNodeRepository
trail_repo = TrailNodeRepository(self._session_factory)
latest_step = await trail_repo.get_latest_step_boundary(job_id)
if latest_step and latest_step.end_sha and latest_step.start_sha:
    # Derive accurate line counts from Git
    diff_stat = await git_service.diff_stat(
        worktree_path, latest_step.start_sha, latest_step.end_sha
    )
    diff_added = diff_stat.additions
    diff_removed = diff_stat.deletions
```

**Fallback**: If GitService is unavailable (worktree already cleaned up), fall back to counting files from step nodes. The cost attribution is best-effort anyway — it stores stats, not billing data.

**Impact**: CostAttributionService currently has a `try/except` around the diff extraction. Same error handling applies.

**Testing**: Existing `test_cost_attribution.py` — update fixtures to provide trail nodes instead of EventRepository mocks. Add test for the fallback path (no step nodes → zero counts).

#### 2b. RuntimeHandoffService

**File**: `backend/services/runtime_handoff.py`  
**Function**: `load_handoff_context_for_job()` (~line 25)

**Current code** (to replace):

```python
from backend.persistence.event_repo import EventRepository
from backend.services.summarization_service import extract_changed_files
event_repo = EventRepository(session)
diff_events = await event_repo.list_by_job(job.id, kinds=[DomainEventKind.diff_updated])
changed_files = extract_changed_files(diff_events)
```

**New code**:

```python
from backend.persistence.trail_repo import TrailNodeRepository
trail_repo = TrailNodeRepository(session_factory)
changed_files = await trail_repo.get_all_changed_files(job.id)
```

**Impact**: The function signature stays the same — it returns `tuple[str | None, list[str]]`. Only the internal data source changes.

**Edge case**: If the job has no trail nodes yet (e.g., crashed before first step completed), `get_all_changed_files()` returns `[]`. This matches the current behavior when no `diff_updated` events exist.

**Testing**: Update `test_runtime_handoff.py` fixtures to provide trail nodes. The handoff function's callers don't change.

#### 2c. SummarizationService — `summarize_and_store()`

**File**: `backend/services/summarization_service.py`  
**Method**: `summarize_and_store()` (~line 155)

This is the most complex migration because the service builds a cleaned transcript from raw event payloads.

**Current code** (transcript path):

```python
transcript_events = await event_repo.list_by_job(
    job_id, kinds=[DomainEventKind.transcript_updated],
)
cleaned_turns = _clean_transcript(transcript_events)
transcript_text = _format_transcript(cleaned_turns)
```

**Current code** (changed files path):

```python
diff_events = await event_repo.list_by_job(
    job_id, kinds=[DomainEventKind.diff_updated],
)
changed_files = extract_changed_files(diff_events)
```

**New code** (changed files — straightforward):

```python
trail_repo = TrailNodeRepository(self._session_factory)
changed_files = await trail_repo.get_all_changed_files(job_id)
```

**New code** (transcript — requires adaptation):

The `_clean_transcript()` function operates on `DomainEvent` payloads with `role`, `content`, `timestamp` fields. Trail nodes carry `agent_message` and `timestamp` but role handling differs.

Two approaches:

**Approach A (recommended)**: Write a `_clean_transcript_from_trail()` that operates on trail nodes instead of events:

```python
def _clean_transcript_from_trail(nodes: list[TrailNodeRow]) -> list[TranscriptTurn]:
    """Build cleaned transcript turns from trail nodes."""
    seen: set[str] = set()
    result = []
    for node in nodes:
        content = (node.agent_message or "").strip()
        if not content:
            continue
        # Determine role from node kind or embedded metadata
        role = _role_from_node(node)
        if role not in ("agent", "operator"):
            continue
        key = f"{role}:{content}"
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "role": role,
            "content": content,
            "timestamp": node.timestamp.isoformat() if node.timestamp else "",
        })
    return result
```

**Approach B**: Query trail nodes and reconstruct `DomainEvent`-like dicts, then pass to existing `_clean_transcript()`. Preserves existing code but is a leaky abstraction.

**Decision**: Approach A. The existing `_clean_transcript()` can remain for backward compatibility (used in the `pre_built_transcript` code path). The new function replaces only the EventRepository-backed path.

**Note**: `summarize_and_store()` already accepts `pre_built_transcript` and `pre_built_changed_files` kwargs. The EventRepository path is the fallback when these aren't provided. After migration, this fallback uses TrailNodeRepository instead.

#### 2d. SummarizationService — `save_snapshot_to_disk()`

**File**: `backend/services/summarization_service.py`  
**Method**: `save_snapshot_to_disk()` (~line 213)

Same pattern as `summarize_and_store()` — queries `transcript_updated` and `diff_updated` events. The snapshot building logic is more detailed (preserves tool_call metadata, tool_name, tool_display, tool_intent, tool_success).

**Current code**:

```python
transcript_events = await event_repo.list_by_job(job_id, kinds=[DomainEventKind.transcript_updated])
diff_events = await event_repo.list_by_job(job_id, kinds=[DomainEventKind.diff_updated])
changed_files = extract_changed_files(diff_events)
```

**New code** (changed files):

```python
trail_repo = TrailNodeRepository(self._session_factory)
changed_files = await trail_repo.get_all_changed_files(job_id)
```

**New code** (transcript snapshot):

The snapshot builder needs richer data than the summarization prompt — it preserves `tool_name`, `tool_display`, `tool_intent`, `tool_success` per turn. Trail nodes carry `tool_names` (JSON array) but not the per-call display/intent/success metadata.

**Options**:

1. **Embed tool metadata in trail nodes**: Add `tool_metadata` JSON column to `TrailNodeRow` that carries per-call details. Requires schema migration + node builder change.

2. **Read from `preceding_context`**: Each trail node's `preceding_context` JSON blob contains the ring buffer snapshot, which includes `tool_name`, `tool_args` per entry. This data is already there — just not in a convenient shape.

3. **Defer this migration**: `save_snapshot_to_disk()` is a cold-path operation (runs once at job end). It can continue reading EventRepository while the hot-path consumers migrate first. Mark it as a follow-up item.

**Decision**: Option 3 for now. Migrate `summarize_and_store()` first. `save_snapshot_to_disk()` is the last consumer and can be migrated when trail nodes carry sufficient tool metadata. Add a `# TODO(trail-migration): migrate to TrailNodeRepository` comment.

#### 2e. Testing Strategy

Each migration needs:
- **Unit test update**: Replace EventRepository mocks with TrailNodeRepository mocks. Assert same output shape.
- **Integration test**: End-to-end with SQLite: create job → feed events → let TrailService persist nodes → call migrated service → verify result.
- **Regression test**: Run the existing test suite after each migration. No test should break if the migration is correct.

---

### Phase 3: Enforce Boundary

**Goal**: Make the invariant machine-checkable. Prevent future regressions.

#### 3a. Architectural Import Guard

**File**: `backend/tests/test_architecture.py`

```python
import ast
import pathlib

# Modules that are ALLOWED to import EventRepository
ALLOWED_EVENT_REPO_CONSUMERS = {
    "backend/persistence/event_repo.py",          # itself
    "backend/services/trail/service.py",           # rehydration on session_resumed
    "backend/services/trail/node_builder.py",      # rehydration on session_resumed
    "backend/services/runtime_service.py",         # hot path event processing
    "backend/services/runtime_telemetry.py",       # infrastructure: log_line_emitted
    "backend/api/trail.py",                        # API endpoint (reads via repo)
    # Temporary exceptions (remove after Phase 2d):
    "backend/services/summarization_service.py",   # save_snapshot_to_disk only
}

def test_event_repo_import_boundary():
    """No service outside the allowlist may import EventRepository."""
    violations = []
    backend = pathlib.Path("backend")
    for py_file in backend.rglob("*.py"):
        rel = str(py_file)
        if rel in ALLOWED_EVENT_REPO_CONSUMERS:
            continue
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                if "EventRepository" in names or "event_repo" in module:
                    violations.append(f"{rel}:{node.lineno}")
    assert not violations, (
        f"EventRepository imported outside allowlist:\n" +
        "\n".join(f"  {v}" for v in violations)
    )
```

**Maintenance**: When `save_snapshot_to_disk()` is migrated (Phase 2d follow-up), remove `summarization_service.py` from `ALLOWED_EVENT_REPO_CONSUMERS`.

#### 3b. CI Integration

Add `test_architecture.py` to the standard pytest run. No special configuration needed — it's a regular test that parses ASTs. Runs in <1 second.

#### 3c. Documentation

Add a one-line comment at the top of `EventRepository`:

```python
class EventRepository:
    """Raw event persistence. Direct consumers: RuntimeService, TrailService,
    RuntimeTelemetry (log lines). All other services must use
    TrailNodeRepository projections. See internal-docs/design/unified-trail-service.md §6."""
```

---

### Phase Summary

| Phase | Scope | Files changed | Risk | Shippable alone? |
|-------|-------|---------------|------|-------------------|
| 1 | Add projection methods to TrailNodeRepository | `trail_repo.py`, new test file | None — purely additive | Yes |
| 2a | Migrate CostAttributionService | `cost_attribution.py`, test updates | Low — fallback preserved | Yes |
| 2b | Migrate RuntimeHandoffService | `runtime_handoff.py`, test updates | Low — same output contract | Yes |
| 2c | Migrate SummarizationService (summarize) | `summarization_service.py`, new helper | Medium — transcript shape change | Yes |
| 2d | Migrate SummarizationService (snapshot) | Deferred — needs trail schema work | N/A | Follow-up |
| 3 | Import guard + CI | `test_architecture.py`, `event_repo.py` | None — test only | Yes |

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
- Nodes with `enrichment='in_progress'` reset to `'pending'` (in-flight request assumed lost)
- Drain loop resumes and resubmits pending nodes
- StepTracker starts fresh (forward-only state)
- Sister sessions are stateless per-batch — no conversational context to lose

---

## 10. Design Constraints

1. **No raw event leakage**: No service outside TrailService/RuntimeService may query `EventRepository` for provenance events. (Infrastructure events excepted per §6.3.)

2. **No enrichment on hot path**: LLM calls never block event processing. Structure is synchronous; meaning is asynchronous.

3. **Deterministic facts are immutable**: Once a trail node's structural fields are set, they never change.

4. **Enrichment fill, not mutation**: Semantic columns are written once from NULL. Revisions create new nodes via `supersedes`.

5. **No event bus feedback loops**: No subscriber of TrailService-published events may trigger actions that feed back into TrailService's ingestion path.

6. **Single-writer ordering**: Each job has exactly one sequential RuntimeService event loop. `seq` is trivially ordered — no locks, no races. Multi-agent would require Lamport timestamps.

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
