# CodeRecon × CodePlane Integration — Design Document

> **Status**: Draft  
> **Date**: 2026-04-22  
> **Scope**: Full lifecycle integration of CodeRecon's structural code intelligence into CodePlane's agent supervision platform  
> **References**: [CodeRecon SDK Spec](../../../coderecon/docs/SPEC-sdk-stdio.md)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [CodeRecon Technical Foundation](#3-coderecon-technical-foundation)
4. [Integration Architecture: SDK Over Stdio](#4-integration-architecture-sdk-over-stdio)
5. [Daemon Lifecycle Management](#5-daemon-lifecycle-management)
6. [Repository Onboarding](#6-repository-onboarding)
7. [Index Health & Freshness](#7-index-health--freshness)
8. [Lifecycle Stage Integration Map](#8-lifecycle-stage-integration-map)
9. [Agent Tool Provisioning](#9-agent-tool-provisioning)
10. [Review UX: The Verification Dashboard](#10-review-ux-the-verification-dashboard)
11. [The Multi-Session Reality](#11-the-multi-session-reality)
12. [Structural Story Generation](#12-structural-story-generation)
13. [Event Bridge: CodeRecon → CodePlane → Frontend](#13-event-bridge-coderecon--codeplane--frontend)
14. [Data Flow Diagrams](#14-data-flow-diagrams)
15. [API Surface](#15-api-surface)
16. [Frontend Architecture](#16-frontend-architecture)
17. [Repository Settings & Configuration](#17-repository-settings--configuration)
18. [Migration Strategy](#18-migration-strategy)
19. [Open Questions](#19-open-questions)

---

## 1. Executive Summary

CodePlane supervises coding agents. CodeRecon understands code structure. Integrating them transforms CodePlane from "here's a git diff, good luck" to "here's what changed structurally, what it affects, and how confident we are about the impact."

The integration touches **every stage** of a job's lifecycle — not just review. CodeRecon helps during repo onboarding (first index), task planning (`recon`), execution (agent-facing tools, live re-indexing), review (semantic diff, blast radius, community clustering), merge (confidence scoring), and analytics (structural complexity tracking).

**The key architectural decision**: CodeRecon exports a **Python SDK** that communicates with a **global daemon child process over stdio**. CodePlane spawns the daemon at startup and owns its lifecycle. Communication uses a lightweight NDJSON protocol — not MCP, not HTTP. The daemon is the same `GlobalDaemon` that powers `recon up`, managing a multi-repo catalog with lazy repo activation, file watchers, background indexers, and worktree-partitioned indexes.

**The ripple effect**: Adding a repository to CodePlane triggers a full structural index build — Tree-sitter parsing of every source file, import resolution, reference classification, Tantivy full-text indexing, SPLADE vector encoding. This is a significant user-facing experience with progress indication, language detection, and potential minutes of initial indexing for large repos. Every screen that touches repositories participates in structural intelligence.

---

## 2. Problem Statement

### The Review Problem

When a coding agent completes a job, the reviewer sees:

```
┌─────────────────────────────────────────────────────┐
│  FILES CHANGED (14)                                  │
│                                                      │
│  ☐ src/api/handlers.py         +45 -12              │
│  ☐ src/api/middleware.py       +23 -0               │
│  ☐ src/core/validator.py       +67 -31              │
│  ☐ src/core/rate_limiter.py    +89 -0   (new)       │
│  ☐ src/models/request.py       +8 -3               │
│  ☐ src/models/response.py      +5 -2               │
│  ☐ tests/test_handlers.py      +34 -5              │
│  ☐ tests/test_validator.py     +41 -8              │
│  ☐ config/settings.yaml        +3 -1               │
│  ☐ docs/api.md                 +22 -4              │
│  ☐ .env.example                +2 -0               │
│  ☐ requirements.txt            +1 -0               │
│  ☐ Makefile                    +4 -0               │
│  ☐ README.md                   +8 -2               │
│                                                      │
│  [Full Diff in Monaco Editor ──────────────────────] │
└─────────────────────────────────────────────────────┘
```

This is a flat list. Every file looks equally important. The reviewer must:

1. **Mentally triage** — which files matter? Which can I skip?
2. **Guess at impact** — does changing `validator.py` break anything?
3. **Hope tests cover it** — are the test changes sufficient?
4. **Read everything linearly** — no structural understanding

CodePlane's behavioral review signals (WS1-WS7) help with heuristics:

| Signal | What it tells you | Limitation |
|--------|-------------------|------------|
| WS1 (churn sort) | Files the agent edited most | High churn ≠ high risk |
| WS2 (blast radius) | Files read but not written | Read ≠ affected |
| WS5 (test co-mods) | Source/test file pairs | Only catches co-edits, not missing coverage |
| WS6 (complexity tier) | Overall review difficulty | Coarse (quick/standard/deep) |

These are **behavioral signals** — they describe what the agent *did*. They don't describe what the code *means*.

### The Gap

**Structural intelligence**. The ability to say:

- "This function's **signature changed** — it has 12 call sites, 3 of which we can't statically verify"
- "This is a **new method** with zero existing callers — additive, safe by construction"
- "This body change is inside a function that **only tests call** — low risk"
- "These 4 files form a **dependency cycle** that the agent just introduced"
- "These changes cluster into **2 unrelated concerns** that the developer crammed into one session"

That's what CodeRecon provides.

### Circles of impact

This integration is not contained to the diff view. It radiates outward:

```
                         ┌──────────────┐
                         │ REPO SETUP   │ ← Adding a repo = building a full index
                         │              │   Progress bars, language detection,
                         └──────┬───────┘   error handling, re-index triggers
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
             ┌──────────┐ ┌──────────┐ ┌──────────┐
             │ JOB START│ │ EXECUTION│ │  REVIEW  │
             │ pre-recon│ │ live idx │ │ sem-diff │
             │ context  │ │ agent    │ │ triage   │
             │ packet   │ │ tools    │ │ blast    │
             └─────┬────┘ └────┬─────┘ └────┬─────┘
                   │           │            │
                   ▼           ▼            ▼
             ┌──────────┐ ┌──────────┐ ┌──────────┐
             │  STORY   │ │ MERGE    │ │ANALYTICS │
             │ enriched │ │ confid-  │ │ struct   │
             │ narrative│ │ ence     │ │ metrics  │
             └──────────┘ └──────────┘ └──────────┘
                                │
                                ▼
                         ┌──────────────┐
                         │ REPO HEALTH  │ ← Dashboard: cycles, communities,
                         │              │   drift, complexity trends
                         └──────────────┘
```

---

## 3. CodeRecon Technical Foundation

### 3.1 What CodeRecon Is

CodeRecon is a **repository control plane** that converts a codebase into structured, queryable facts. It builds a multi-tier index from source code and exposes it through tool interfaces.

Core principle: **Agent decides → CodeRecon executes deterministically → Structured result**. No LLM in the loop for factual queries. LLMs are only used for ranking relevance, never for asserting facts about code structure.

### 3.2 The Tiered Index

```
┌─────────────────────────────────────────────────────────────┐
│                      CodeRecon Index                         │
│                                                              │
│  ┌─── Tier 0: Lexical (Tantivy) ─────────────────────────┐ │
│  │  Full-text search over symbol names, docstrings,       │ │
│  │  comments, file content. BM25 + language-aware         │ │
│  │  tokenization. Sub-millisecond retrieval.              │ │
│  │  Stored at: <repo>/.recon/tantivy/                     │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─── Tier 1: Structural (Tree-sitter + SQLite) ─────────┐ │
│  │  10 fact types extracted via Tree-sitter grammars.     │ │
│  │  Syntax-only — no type inference, no semantic          │ │
│  │  resolution. But covers 90+ languages.                 │ │
│  │  Stored at: <repo>/.recon/index.db                     │ │
│  │                                                        │ │
│  │  Fact Types:                                           │ │
│  │  ┌──────────────────┬────────────────────────────────┐ │ │
│  │  │ DefFact          │ function/class/variable defs   │ │ │
│  │  │ RefFact          │ identifier occurrences + tier  │ │ │
│  │  │ ScopeFact        │ lexical scopes (nesting)       │ │ │
│  │  │ ImportFact       │ import statements (resolved)   │ │ │
│  │  │ ExportSurface    │ public API per build unit      │ │ │
│  │  │ ExportEntry      │ individual exported names      │ │ │
│  │  │ LocalBindFact    │ same-file identifier bindings  │ │ │
│  │  │ TypeAnnotation   │ type annotations (source-level)│ │ │
│  │  │ TypeMemberFact   │ class/struct fields            │ │ │
│  │  │ File             │ file metadata + content hash   │ │ │
│  │  └──────────────────┴────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─── Tier 2: Type-Aware (Pass 3) ───────────────────────┐ │
│  │  MemberAccessFact   — obj.field.method() chains       │ │
│  │  InterfaceImplFact  — trait/interface implementations  │ │
│  │  ReceiverShapeFact  — duck-type inference              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─── Tier 3: Behavioral (Tool Execution) ────────────────┐ │
│  │  TestTarget         — test files & runners             │ │
│  │  TestCoverageFact   — coverage links (test↔def)        │ │
│  │  IndexedLintTool    — available linters                │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─── Ranking Models (LightGBM + TinyBERT) ──────────────┐ │
│  │  gate.lgbm          — query classification             │ │
│  │  file_ranker.lgbm   — LambdaMART file ranking          │ │
│  │  ranker.lgbm        — LambdaMART definition ranking    │ │
│  │  cutoff.lgbm        — optimal result count prediction  │ │
│  │  TinyBERT           — cross-encoder re-ranking         │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Reference Tier System

Every `RefFact` (identifier occurrence) is classified into a **confidence tier** at index time:

```
PROVEN ──────── Same-file lexical bind with LocalBindFact certainty=CERTAIN
   │            "We can prove this reference resolves to this definition"
   │
STRONG ──────── Cross-file with explicit ImportFact + ExportSurface trace
   │            "Import chain is unambiguous and fully resolved"
   │
ANCHORED ────── Ambiguous but grouped in AnchorGroup (bounded ambiguity)
   │            "Could be one of N definitions, but N is small and known"
   │
SEMANTIC ────── Resolved via SPLADE+CE semantic matching
   │            "Best-effort neural match — no syntactic proof"
   │
UNKNOWN ─────── Cannot classify
                "Dynamic dispatch, eval, metaprogramming, or unsupported pattern"
```

**Why this matters for review**: A function signature change with 12 PROVEN references is safe — every call site is statically known. The same change with 3 UNKNOWN references means the reviewer **must manually verify** those 3 sites because CodeRecon can't guarantee they'll work after the change.

### 3.4 The Worktree Column Key

CodeRecon indexes **once per repository**, not once per worktree. The SQLite schema uses `worktree_id` as a partition column:

```sql
CREATE TABLE files (
    id          INTEGER PRIMARY KEY,
    worktree_id INTEGER NOT NULL DEFAULT 0,   -- partition key
    path        TEXT NOT NULL,
    content_hash TEXT,
    language_family TEXT,
    line_count  INTEGER,
    indexed_at  REAL,
    UNIQUE(worktree_id, path)                 -- same file, different worktrees
);

CREATE TABLE def_facts (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER REFERENCES files(id),
    worktree_id INTEGER NOT NULL DEFAULT 0,   -- denormalized for query speed
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    lexical_path TEXT,
    def_uid     TEXT NOT NULL,
    signature_text TEXT,
    ...
);
```

This means:

```
Repository: my-project/
├── .recon/index.db          ← ONE index database
├── main branch (worktree_id=0)
│   └── files, defs, refs indexed with worktree_id=0
├── .codeplane-worktrees/
│   ├── job-abc/ (worktree_id=1)
│   │   └── files, defs, refs indexed with worktree_id=1
│   └── job-def/ (worktree_id=2)
│       └── files, defs, refs indexed with worktree_id=2
```

When CodePlane creates a worktree for job-abc, CodeRecon registers it as worktree_id=1 in the same index. Queries for job-abc's structural state include `WHERE worktree_id = 1`. Cross-worktree comparison (e.g., what changed between main and job-abc's branch) is a JOIN across worktree IDs.

### 3.5 Incremental Indexing

CodeRecon doesn't re-index the entire repository on every change. The reconcile loop:

```
1. Compute current HEAD sha
2. For each tracked file:
   a. Compute content_hash (blake2b of file bytes)
   b. Compare to stored content_hash in index
   c. Classify: ADDED | MODIFIED | DELETED | UNCHANGED
3. Bulk-update file rows
4. Re-parse only ADDED + MODIFIED files through Tree-sitter
5. Update Tantivy index with changed documents
6. Advance epoch counter
```

**Dirty detection granularity**: File-level (content hash). Not line-level. If any byte changes, the entire file is re-parsed. This is fast because Tree-sitter parsing is sub-millisecond per file for most languages.

### 3.6 Semantic Diff Pipeline

The `semantic_diff` tool is the cornerstone of the review integration. Here's what it actually does, step by step:

```
Input: base_sha, target_sha (or worktree HEAD)

Step 1: Snapshot Collection
├── For base_sha: extract DefFact snapshots from git blob
│   (parse the old version of each changed file through Tree-sitter)
└── For target_sha: read DefFacts from the index
    (already parsed and stored)

Step 2: Structural Change Engine
├── Build identity maps: (kind, lexical_path) → DefSnapshot
│   for both base and target
├── For each identity key:
│   ├── In target but not base → "added"
│   ├── In base but not target → "removed"
│   ├── Same key, different signature_hash → "signature_changed"
│   ├── Same key, same sig, but hunk intersects body → "body_changed"
│   └── Same key, different name → "renamed"
└── Non-grammar files classified by extension (docs, config, etc.)

Step 3: Blast-Radius Enrichment
├── For each structural change with a def_uid:
│   ├── Query all RefFacts WHERE target_def_uid = this.def_uid
│   ├── Classify refs by ref_tier (PROVEN/STRONG/ANCHORED/UNKNOWN)
│   ├── Group referencing files
│   ├── Identify affected test files
│   └── Compute behavior_change_risk from tier distribution
└── Assemble SemanticDiffResult

Output: SemanticDiffResult
├── structural_changes[]
│   ├── path, kind, name, change type
│   ├── structural_severity (breaking/non-breaking/additive)
│   ├── behavior_change_risk (high/medium/low)
│   ├── old_sig, new_sig (for signature changes)
│   └── impact{}
│       ├── reference_count
│       ├── ref_tiers: {proven: N, strong: N, anchored: N, unknown: N}
│       ├── referencing_files[]
│       └── affected_test_files[]
├── non_structural_changes[]
│   └── path, status, category (docs/config/build)
├── summary (human-readable one-liner)
├── breaking_summary (null if no breaking changes)
└── scope: {mode, base_sha, target_sha, files_parsed, languages_analyzed}
```

### 3.7 Graph Analysis

CodeRecon builds two directed graphs from its index:

**File Graph** (from ImportFact):
```
Edge A → B means: file A imports something from file B

Built from:
  SELECT DISTINCT f.path, i.resolved_path
  FROM import_facts i
  JOIN files f ON f.id = i.file_id
  WHERE i.resolved_path IS NOT NULL
```

**Definition Graph** (from RefFact → DefFact):
```
Edge A → B means: definition A references definition B

Built from:
  SELECT r.target_def_uid, sd.def_uid AS source_def_uid
  FROM ref_facts r
  JOIN def_facts sd ON sd.file_id = r.file_id
    AND r.start_line BETWEEN sd.start_line AND sd.end_line
  WHERE r.target_def_uid IS NOT NULL
```

Available analyses:
- **Tarjan SCC** (`graph_cycles`): Finds circular dependencies. Returns strongly connected components with size > 1.
- **Louvain Communities** (`graph_communities`): Detects module clusters in the undirected projection. Uses PageRank to select a representative node per community.
- **Reachability** (`recon_impact`): Traverses the reference graph from a symbol outward. Returns all paths that lead to/from it.

### 3.8 The Recon Tool (Task-Aware Discovery)

The `recon` tool is CodeRecon's primary retrieval interface. Given a natural-language task description, it returns ranked code locations.

```
Input: task description + optional seeds (symbol names) + pins (file paths)

Pipeline:
┌─────────────────────────────────────────────────────────┐
│  1. HARVEST (parallel retrievers)                        │
│     ├── Term Match: Tantivy search for symbol names      │
│     ├── Lexical: Full-text search for keywords           │
│     ├── Graph Expansion: Follow DefFact→DefFact edges    │
│     ├── Symbol Seeding: Agent-provided seed names        │
│     └── Merge via Reciprocal Rank Fusion (RRF)           │
│                                                          │
│  2. GATE (LightGBM classifier)                           │
│     └── Classify query: OK | UNSAT | BROAD | AMBIG       │
│         (If not OK → return early with hint)             │
│                                                          │
│  3. FILE RANKING (LambdaMART Stage 1)                    │
│     └── Score files → prune to top ~20                   │
│         Force-include seed/pin files                     │
│                                                          │
│  4. CROSS-ENCODER (TinyBERT re-ranking)                  │
│     └── Score filtered candidates semantically           │
│                                                          │
│  5. DEF RANKING (LambdaMART Stage 2)                     │
│     └── Score individual definitions within kept files   │
│                                                          │
│  6. CUTOFF (LightGBM predictor)                          │
│     └── Predict optimal result count                     │
│                                                          │
│  7. SNIPPET EXTRACTION                                   │
│     └── Full source for top results, signatures for rest │
└─────────────────────────────────────────────────────────┘

Output:
{
  "recon_id": "abc123",
  "gate": "OK",
  "results": [
    {
      "def_uid": "src/core.py::Coordinator::reconcile",
      "path": "src/core.py",
      "kind": "method",
      "name": "reconcile",
      "start_line": 100,
      "end_line": 150,
      "score": 0.95,
      "snippet": "def reconcile(self) -> ReconcileResult:\n    ...",
      "symbol_source": "query"
    }
  ],
  "metrics": {
    "total_candidates_scored": 500,
    "retriever_coverage": { "term_match": 45, "lexical": 120, "graph": 80 },
    "top_score": 0.95,
    "score_drop_at": 3
  },
  "hints": ["Sharp score drop at position 3"]
}
```

**Heuristic fallback**: When LightGBM models aren't available, the pipeline skips stages 2-6 and uses RRF fusion with elbow cutoff (largest score gap = natural boundary).

### 3.9 Scaffolds

A **scaffold** is CodeRecon's compact structural representation of a file:

```json
{
  "path": "src/api/handlers.py",
  "language": "python",
  "total_lines": 342,
  "indexed": true,
  "imports": [
    "fastapi: APIRouter, Depends, HTTPException",
    "pydantic: BaseModel",
    "..services.validator: validate_request"
  ],
  "symbols": [
    "class CreateHandler [15-120]",
    "  method __init__(self, db, validator) [20-30]",
    "  method handle(self, request) -> Response [35-80]",
    "    function _validate_fields(data) [45-60]",
    "  method _audit_log(self, action, user) [90-120]",
    "class UpdateHandler [130-230]",
    "  method handle(self, id, request) -> Response [140-200]",
    "function health_check() -> dict [300-310]"
  ]
}
```

Scaffolds convey **what a file contains** without showing the implementation. Hierarchical nesting via indentation (based on line-range containment). This is 10-50x more compact than showing the full source code while preserving the structural skeleton.

### 3.10 Checkpoint

The `checkpoint` tool runs a lint → test → commit → push pipeline:

```json
{
  "status": "passed",
  "stages": {
    "lint":   { "status": "passed", "fixed": 3 },
    "test":   { "status": "passed", "passed": 12, "failed": 0, "duration_seconds": 2.3 },
    "commit": { "status": "committed", "hash": "abc1234...", "message": "fix: update API" },
    "push":   { "status": "pushed", "branch": "main" }
  },
  "test_debt": {
    "source_files_changed": 2,
    "test_files_changed": 0,
    "missing_test_updates": [
      { "source": "src/api.py", "test_file": "tests/test_api.py" }
    ]
  }
}
```

### 3.11 Refactoring

CodeRecon provides index-backed refactoring with certainty classification:

```
refactor_rename("handle_request", "process_request")
  → Preview:
    {
      "refactor_id": "rf_a1b2c3",
      "status": "previewed",
      "preview": {
        "files_affected": 5,
        "high_certainty_count": 9,
        "medium_certainty_count": 2,
        "low_certainty_count": 1,
        "verification_required": true,
        "edits": [
          {
            "path": "src/router.py",
            "hunks": [
              { "old": "handle_request", "new": "process_request",
                "line": 42, "certainty": "high" },
              { "old": "handle_request", "new": "process_request",
                "line": 78, "certainty": "medium" }
            ]
          }
        ]
      }
    }
```

---

## 4. Integration Architecture: SDK Over Stdio

### 4.1 Why Not In-Process

An in-process import of CodeRecon's `IndexCoordinatorEngine` directly into CodePlane was considered and rejected. The SDK provides a better model: **child process over stdio**.

| Factor | In-process import | SDK over stdio |
|--------|-------------------|----------------|
| **Dependency coupling** | Tight — CodePlane imports CodeRecon internals | Loose — SDK client uses only stdlib |
| **Process isolation** | Shared GIL, shared memory, shared crash domain | Separate process — daemon crash doesn't kill CodePlane |
| **Version independence** | Must pin exact CodeRecon version | SDK wire format is stable; daemon can upgrade independently |
| **Resource management** | CodePlane's event loop handles indexing, parsing, Tantivy writes | Daemon has its own event loop, thread pool, memory budget |
| **SQLite contention** | WAL mode helps but shared-process writes contend with reads | Daemon owns SQLite exclusively; no contention |
| **Global daemon** | Each CodePlane instance creates its own index state | One daemon serves all consumers; shared catalog |

### 4.2 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          CodePlane Backend                                │
│                                                                          │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐                  │
│  │ RuntimeSvc   │   │ DiffService  │   │ StoryService │                  │
│  │ (job mgmt)   │   │ (git diff)   │   │ (narrative)  │                  │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                  │
│         │                  │                   │                          │
│         │    ┌─────────────┴───────────────────┘                         │
│         │    │                                                            │
│         ▼    ▼                                                            │
│  ┌──────────────────────────────────────────────────────────┐            │
│  │          CodeReconService (thin wrapper)                  │            │
│  │                                                          │            │
│  │  self._sdk = CodeRecon()         # SDK client            │            │
│  │  self._sdk.start()               # spawns daemon         │            │
│  │  self._handles: dict[str, RepoHandle]                    │            │
│  │                                                          │            │
│  │  Typed methods:                                          │            │
│  │    semantic_diff(repo, base, target) → DiffResult        │            │
│  │    recon(repo, task) → ReconResult                       │            │
│  │    impact(repo, symbol) → ImpactResult                   │            │
│  │    communities(repo) → CommunitiesResult                 │            │
│  │    cycles(repo) → CyclesResult                           │            │
│  │    scaffold(repo, file) → ScaffoldResponse               │            │
│  │    checkpoint(repo, files) → CheckpointResult            │            │
│  └──────────────┬───────────────────────────────────────────┘            │
│                 │ stdio (NDJSON)                                          │
│                 ▼                                                         │
│  ┌──────────────────────────────────────────────────────────┐            │
│  │          CodeRecon Daemon (child process)                 │            │
│  │                                                          │            │
│  │  GlobalDaemon                                            │            │
│  │  ├── Catalog (~/.coderecon/catalog.db)                   │            │
│  │  ├── RepoSlots (lazy-activated per repo)                 │            │
│  │  │   ├── IndexCoordinatorEngine (SQLite + Tantivy)       │            │
│  │  │   ├── BackgroundIndexer (reconcile loop)              │            │
│  │  │   ├── FileWatcher (inotify/polling)                   │            │
│  │  │   ├── FreshnessGate (stale/fresh tracking)            │            │
│  │  │   └── WorktreeSlots (per-worktree state)              │            │
│  │  │       ├── AppContext (ops, session, gate)              │            │
│  │  │       └── MutationRouter                              │            │
│  │  └── SessionManager                                      │            │
│  │                                                          │            │
│  │  Sends events on stdout:                                 │            │
│  │    index.progress, index.complete, freshness.stale/fresh │            │
│  │    watcher.changes, repo.activated, daemon.ready         │            │
│  └──────────────────────────────────────────────────────────┘            │
│                                                                          │
│  ┌──────────────────┐                                                    │
│  │  Agent Adapter    │ ──── stdio ───→ [Coding Agent Process]            │
│  │  (Claude/Copilot) │                                                   │
│  └──────────────────┘                                                    │
│                                                                          │
│         │  SSE                                                           │
│         ▼                                                                │
│  ┌──────────────────┐                                                    │
│  │  React Frontend   │                                                   │
│  └──────────────────┘                                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.3 The Stdio Protocol

Communication between `CodeReconService` and the daemon uses **NDJSON** (newline-delimited JSON). Not MCP. Not HTTP. A private, minimal wire format.

**Request** (CodePlane → daemon stdin):
```json
{"id": "r1", "method": "semantic_diff", "params": {"repo": "my-project", "base": "abc123", "target": "def456", "worktree": "job-abc"}}
```

**Response** (daemon stdout → CodePlane):
```json
{"id": "r1", "result": {"structural_changes": [...], "summary": "..."}}
```

**Event** (daemon stdout → CodePlane, interleaved with responses):
```json
{"event": "index.progress", "data": {"repo": "my-project", "worktree": "main", "phase": "indexing", "indexed": 847, "total": 2103}}
```

The SDK client's read loop distinguishes events (have `event` field) from responses (have `id` field). Events fire registered callbacks; responses resolve pending futures.

### 4.4 The CodeReconService

```python
class CodeReconService:
    """Manages CodeRecon daemon lifecycle and provides typed access to tools.

    This is the single integration surface between CodePlane and CodeRecon.
    All CodeRecon access goes through this service — no other CodePlane code
    imports from coderecon directly.
    """

    def __init__(self, config: CodePlaneConfig):
        from coderecon import CodeRecon
        self._sdk = CodeRecon(home=config.coderecon_home)
        self._handles: dict[str, RepoHandle] = {}
        self._event_callbacks: list[Callable] = []

    async def start(self):
        """Start the daemon child process. Called from lifespan."""
        await self._sdk.start()
        # Wire daemon events → CodePlane event bus
        self._sdk.on("index.*", self._on_index_event)
        self._sdk.on("freshness.*", self._on_freshness_event)
        self._sdk.on("watcher.*", self._on_watcher_event)
        self._sdk.on("repo.*", self._on_repo_event)

    async def stop(self):
        """Shut down the daemon. Called from lifespan."""
        await self._sdk.stop()

    # ── Repo Management ──────────────────────────────────────

    async def register_repo(self, repo_path: Path) -> RegisterResult:
        """Register a repo with the daemon and trigger initial indexing.

        This is called when an operator adds a repo to CodePlane.
        The daemon will start full indexing — progress events stream
        back via the event bus.
        """
        result = await self._sdk.register(str(repo_path))
        handle = self._sdk.repo(result.repo)
        self._handles[str(repo_path)] = handle
        return result

    async def unregister_repo(self, repo_path: Path):
        """Remove a repo from the daemon catalog."""
        await self._sdk.unregister(str(repo_path))
        self._handles.pop(str(repo_path), None)

    def _handle(self, repo_path: Path) -> RepoHandle:
        """Get the repo-bound handle, raising if not registered."""
        key = str(repo_path)
        if key not in self._handles:
            raise RepoNotIndexed(f"Repo {repo_path} not registered with CodeRecon")
        return self._handles[key]

    # ── Tool Methods (delegates to repo-bound handle) ────────

    async def recon(self, repo_path: Path, task: str,
                    seeds: list[str] | None = None) -> ReconResult:
        return await self._handle(repo_path).recon(task=task, seeds=seeds or [])

    async def semantic_diff(self, repo_path: Path, base: str,
                            target: str | None = None,
                            worktree: str = "main") -> DiffResult:
        return await self._handle(repo_path).semantic_diff(
            base=base, target=target, worktree=worktree)

    async def impact(self, repo_path: Path, symbol: str,
                     worktree: str = "main") -> ImpactResult:
        return await self._handle(repo_path).recon_impact(
            target=symbol, justification="Review drill-down",
            worktree=worktree)

    async def communities(self, repo_path: Path,
                          worktree: str = "main") -> CommunitiesResult:
        return await self._handle(repo_path).graph_communities(worktree=worktree)

    async def cycles(self, repo_path: Path,
                     worktree: str = "main") -> CyclesResult:
        return await self._handle(repo_path).graph_cycles(worktree=worktree)

    async def scaffold(self, repo_path: Path, file_path: str,
                       worktree: str = "main") -> MapResult:
        return await self._handle(repo_path).recon_map(
            include=["structure"], worktree=worktree)

    async def checkpoint(self, repo_path: Path,
                         changed_files: list[str],
                         worktree: str = "main",
                         **kwargs) -> CheckpointResult:
        return await self._handle(repo_path).checkpoint(
            changed_files=changed_files, worktree=worktree, **kwargs)

    async def reindex(self, repo_path: Path, worktree: str = "main"):
        """Trigger manual re-index of a worktree."""
        await self._sdk.reindex(str(repo_path), worktree=worktree)

    async def status(self, repo_path: Path | None = None) -> StatusResult:
        repo = str(repo_path) if repo_path else None
        return await self._sdk.status(repo=repo)

    async def catalog(self) -> list[CatalogEntry]:
        return await self._sdk.catalog()

    # ── Agent Tool Export ────────────────────────────────────

    def agent_tools(self, repo_path: Path,
                    worktree: str = "main") -> list[dict]:
        """Return CodeRecon tools formatted for the agent's LLM.

        These are passed to the agent via SessionConfig.tools or
        injected into the MCP server list.
        """
        return self._handle(repo_path).as_openai_tools(worktree=worktree)

    def agent_tool_definitions(self, repo_path: Path,
                               worktree: str = "main") -> list:
        """Return framework-agnostic tool definitions."""
        return self._handle(repo_path).tool_definitions(worktree=worktree)

    # ── Event Bridging ───────────────────────────────────────

    async def _on_index_event(self, event):
        """Bridge CodeRecon index events to CodePlane's event bus."""
        # Transforms daemon events into CodePlane DomainEvents
        # See §13 for full mapping
        ...

    async def _on_freshness_event(self, event):
        ...

    async def _on_watcher_event(self, event):
        ...

    async def _on_repo_event(self, event):
        ...
```

### 4.5 Lifespan Integration

```python
# In CodePlane's lifespan.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing CodePlane startup ...

    # Start CodeRecon daemon as child process
    coderecon = CodeReconService(config)
    await coderecon.start()
    app.state.coderecon = coderecon

    # Re-register any repos that were previously configured
    for repo in await repo_repository.list_repos():
        if repo.coderecon_enabled:
            try:
                await coderecon.register_repo(Path(repo.path))
            except Exception as e:
                log.warning("coderecon.register_failed", repo=repo.path, error=str(e))

    yield

    # Shutdown daemon
    await coderecon.stop()
```

---

## 5. Daemon Lifecycle Management

### 5.1 Startup Sequence

```
CodePlane starts
       │
       ▼
CodeReconService.start()
       │
       ├── sdk.start() spawns: recon up --stdio
       │       │
       │       ▼
       │   Daemon initializes GlobalDaemon
       │   Daemon loads catalog from ~/.coderecon/catalog.db
       │   Daemon emits: {"event": "daemon.ready", "data": {"version": "...", "repos": [...]}}
       │       │
       │       ▼
       │   SDK receives daemon.ready → start() returns
       │
       ├── Wire event callbacks (index.*, freshness.*, watcher.*, repo.*)
       │
       └── For each previously-registered repo:
               │
               ├── sdk.register(repo_path) [no-op if already in catalog]
               │       │
               │       ▼
               │   Daemon lazy-activates repo:
               │     - Loads existing index from .recon/index.db
               │     - Starts BackgroundIndexer (reconcile loop)
               │     - Starts FileWatcher (inotify on main worktree)
               │     - Emits: repo.activated
               │
               └── Discover and register any CodePlane worktrees
                       │
                       ▼
                   For each active job's worktree:
                     sdk calls with worktree=<job-wt-name>
                     Daemon lazy-activates worktree slot
```

### 5.2 Shutdown

The daemon shuts down when its stdin closes (CodePlane process exited) or on explicit `sdk.stop()`:

```python
async def stop(self):
    # Close stdin → daemon receives EOF → graceful shutdown
    self._sdk._process.stdin.close()
    try:
        await asyncio.wait_for(self._sdk._process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        self._sdk._process.terminate()
        await self._sdk._process.wait()
```

The daemon emits `{"event": "daemon.stopping", "data": {"reason": "eof"}}` before exiting.

### 5.3 Crash Recovery

If the daemon crashes unexpectedly:

```python
# In CodeReconService._read_loop error handler:
async def _on_daemon_crash(self, exit_code: int):
    log.error("coderecon.daemon_crashed", exit_code=exit_code)

    # Publish degraded-mode event to frontend
    await self._event_bus.publish(DomainEvent(
        kind="coderecon_unavailable",
        payload={"reason": "daemon_crash", "exit_code": exit_code},
    ))

    # Attempt restart with backoff
    for attempt in range(3):
        await asyncio.sleep(2 ** attempt)
        try:
            await self._sdk.start()
            # Re-register repos
            for repo_path in self._handles:
                await self._sdk.register(repo_path)
            log.info("coderecon.daemon_recovered", attempt=attempt)
            await self._event_bus.publish(DomainEvent(
                kind="coderecon_available",
            ))
            return
        except Exception:
            continue

    log.error("coderecon.daemon_unrecoverable")
    # CodePlane continues without CodeRecon — graceful degradation
```

### 5.4 Graceful Degradation

All CodeRecon-dependent features are optional. When the daemon is unavailable:

- **Diff view**: Falls back to git-diff-only mode (no structural overlays)
- **Story**: Generated without structural context
- **Review signals**: WS1-WS7 still work (they don't depend on CodeRecon)
- **Merge**: Proceeds without confidence score
- **Pre-recon**: Skipped; agent starts without context packet

The frontend shows a subtle indicator:

```
┌──────────────────────────────────────────────┐
│  ⚠ Structural analysis unavailable           │
│  CodeRecon daemon is not running.             │
│  Review signals and git diff are still active.│
│  [Restart Daemon]                             │
└──────────────────────────────────────────────┘
```

---

## 6. Repository Onboarding

### 6.1 What "Add Repo" Means

Adding a repository triggers a **full structural index build** alongside the standard git configuration. This means:

1. Tree-sitter parsing of every source file (90+ languages)
2. Import resolution across files
3. Reference classification (PROVEN/STRONG/ANCHORED/UNKNOWN)
4. Tantivy full-text indexing
5. SPLADE sparse vector encoding
6. Cross-file export surface materialization
7. Optionally: lint tool discovery, test target detection

For a medium repo (2,000 files), this takes **5-15 seconds**. For a large repo (20,000+ files), it can take **30-90 seconds**.

### 6.2 The Onboarding Flow

```
┌──────────────────────────────────────────────────────────────┐
│  ADD REPOSITORY                                               │
│                                                              │
│  Path: /home/user/projects/my-app                    [Browse]│
│  Branch: main                                                │
│                                                              │
│  [Add Repository]                                            │
└──────────────────────────────────────────────────────────────┘

         │ User clicks "Add Repository"
         ▼

┌──────────────────────────────────────────────────────────────┐
│  INDEXING REPOSITORY                                          │
│                                                              │
│  my-app                                                      │
│  /home/user/projects/my-app                                  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Phase: Parsing source files                          │   │
│  │  ████████████████████░░░░░░░░░░░░░░░░░░░░  847/2103   │   │
│  │                                                       │   │
│  │  Languages detected:                                  │   │
│  │  Python: 412 files │ TypeScript: 201 │ Go: 234        │   │
│  │  YAML: 89 │ Markdown: 45 │ Other: 122                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Pipeline:                                            │   │
│  │  ✓ Reconcile (file discovery)                         │   │
│  │  ● Parsing source files (847/2103)                    │   │
│  │  ○ Resolving cross-file imports                       │   │
│  │  ○ Classifying references                             │   │
│  │  ○ Encoding search vectors                            │   │
│  │  ○ Building full-text index                           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Elapsed: 4.2s                                               │
│                                                              │
│  [Cancel]                                                    │
└──────────────────────────────────────────────────────────────┘

         │ Indexing completes
         ▼

┌──────────────────────────────────────────────────────────────┐
│  REPOSITORY INDEXED                                           │
│                                                              │
│  my-app — Ready                                              │
│                                                              │
│  ┌── Index Summary ──────────────────────────────────────┐  │
│  │  Files: 2,103  │  Symbols: 18,420  │  Duration: 8.3s  │  │
│  │  Languages: Python, TypeScript, Go, YAML, Markdown     │  │
│  │                                                        │  │
│  │  Structural Health:                                    │  │
│  │  ├── 3 dependency cycles detected                      │  │
│  │  ├── 8 module communities identified                   │  │
│  │  ├── 142 exported API surfaces                         │  │
│  │  └── 94% of references classified as PROVEN or STRONG  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  [View Repository Health]  [Start a Job]  [Done]             │
└──────────────────────────────────────────────────────────────┘
```

### 6.3 Event Stream During Onboarding

The daemon streams index events over stdout. CodePlane's event bridge converts them to SSE events for the frontend:

```
Daemon event:                          CodePlane SSE event:
─────────────                          ────────────────────
index.started                    →     repo_indexing_started
  {repo, mode: "full", file_count}       {repoId, fileCount}

index.progress                   →     repo_indexing_progress
  {repo, phase, indexed, total,          {repoId, phase, indexed, total,
   files_by_ext}                          languageBreakdown}

index.phase                      →     repo_indexing_phase
  {repo, phase: "resolving_cross_file"}  {repoId, phase: "Resolving imports"}

index.complete                   →     repo_indexing_complete
  {repo, stats: {files_processed,        {repoId, stats, health}
   symbols_indexed, duration_ms}}

index.error                      →     repo_indexing_error
  {repo, error}                          {repoId, error}
```

### 6.4 Index Pipeline Phases

The user-facing phase names map to internal daemon phases:

| Internal Phase | User-Facing Label | Description |
|----------------|-------------------|-------------|
| `indexing` | Parsing source files | Tree-sitter extraction of structural facts |
| `resolving_cross_file` | Resolving imports | Cross-file import/export resolution |
| `resolving_refs` | Classifying references | Reference tier assignment (PROVEN→UNKNOWN) |
| `resolving_types` | Analyzing types | Type annotation and member resolution |
| `encoding_splade` | Encoding search vectors | SPLADE sparse vector encoding for ranking |
| `semantic_resolve` | Semantic resolution | Neural reference matching |
| `semantic_neighbors` | Building neighbor graph | Proximity graph construction |
| `doc_chunk_linking` | Linking documentation | Doc ↔ code association |

### 6.5 Handling Large Repos

For repos over 10,000 files:

1. **Non-blocking onboarding**: The repo is added immediately. Indexing runs in the background. Jobs can start before indexing completes — they'll use degraded mode (no structural analysis) until the index is ready.

2. **Progressive availability**: As phases complete, capabilities unlock:
   - After `indexing` phase: scaffolds available
   - After `resolving_refs`: blast radius available
   - After `encoding_splade`: `recon()` search available
   - After all phases: full structural analysis available

3. **The frontend shows progressive state**:

```
┌─────────────────────────────────────────────────────────┐
│  my-app — Indexing (67%)                                 │
│                                                          │
│  Available now:                                          │
│  ✓ File scaffolds      ✓ Symbol search                  │
│  ○ Blast radius        ○ Semantic diff                   │
│  ○ Community detection ○ Full recon search               │
│                                                          │
│  Jobs can start — structural analysis will be available  │
│  when indexing completes.                                │
└─────────────────────────────────────────────────────────┘
```

### 6.6 Re-Indexing

Operators can trigger a re-index from the repo settings page:

- **Incremental re-index**: Re-scans for changed files only. Fast (seconds). Happens automatically via file watcher.
- **Full re-index**: Drops existing index and rebuilds from scratch. Use when the index seems corrupted or after upgrading CodeRecon. Shows the same progress UI as initial onboarding.

---

## 7. Index Health & Freshness

### 7.1 Freshness Model

CodeRecon tracks freshness per worktree via the `FreshnessGate`:

```
FRESH ──── Index matches the current HEAD + working tree
   │       All queries return accurate results
   │
STALE ──── Files have changed since last reconcile
   │       Queries may return outdated results
   │       Reconcile + index_dirty needed
   │
UNINDEXED ── Worktree registered but never indexed
             No data available
```

The daemon emits `freshness.stale` and `freshness.fresh` events. CodePlane bridges these to the frontend.

### 7.2 Freshness in the UI

A subtle indicator on every page that uses structural data:

```
Index: ● Fresh                         Index: ● Stale (3 files changed)
       (results are current)                  (reconciling...)
```

When stale, the indicator shows how many files changed and whether reconciliation is in progress.

### 7.3 Repo Health Dashboard

The repo detail page includes a health section:

```
┌──────────────────────────────────────────────────────────────┐
│  REPOSITORY HEALTH: my-app                                    │
│                                                              │
│  Index Status: ● Fresh                                       │
│  Last indexed: 2 minutes ago                                 │
│  Files: 2,103 │ Symbols: 18,420 │ Languages: 5               │
│                                                              │
│  ┌── Structural Health ──────────────────────────────────┐   │
│  │                                                        │   │
│  │  Reference Quality:                                    │   │
│  │  ████████████████████████████████████░░░░  94% verified │   │
│  │  PROVEN: 12,340 │ STRONG: 4,560 │ ANCHORED: 890       │   │
│  │  UNKNOWN: 1,120 (6%)                                   │   │
│  │                                                        │   │
│  │  Dependency Cycles: 3                                  │   │
│  │  ├── handlers.py ↔ middleware.py ↔ auth.py  (size 3)   │   │
│  │  ├── models.py ↔ serializers.py              (size 2)   │   │
│  │  └── config.py ↔ settings.py ↔ env.py       (size 3)   │   │
│  │                                                        │   │
│  │  Module Communities: 8                                 │   │
│  │  api_layer (12 files) │ models (8 files) │ auth (6)    │   │
│  │  config (4) │ utils (3) │ tests (22) │ ...             │   │
│  │                                                        │   │
│  │  [View Full Graph]  [Export Graph]                      │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── Actions ─────────────────────────────────────────────┐  │
│  │  [Re-index (incremental)]  [Full Re-index]  [Settings] │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

This gives operators visibility into the structural state of their codebase *before* any agent job runs.

---

## 8. Lifecycle Stage Integration Map

CodeRecon's capabilities map to **every stage** of a job's lifecycle, not just review.

### 8.1 Pre-Execution: Task Planning with `recon`

**When**: Operator submits a task prompt. Before the agent starts.

**What CodeRecon does**: Run `recon(task=prompt_text)` against the repository to identify relevant code locations.

**Why**: Without CodeRecon, the agent starts with just a text prompt and must discover relevant files itself. A pre-computed "context packet" of ranked code locations gives the agent a head start.

```
Operator types: "Add rate limiting to the /api/v2/upload endpoint"

CodeRecon recon() returns:
  1. src/api/v2/upload.py::UploadHandler::handle (score: 0.95)
     snippet: "async def handle(self, request: UploadRequest) -> ..."
  2. src/api/middleware.py::RateLimiter (score: 0.88)
     sig: "class RateLimiter:"
  3. src/core/config.py::RATE_LIMITS (score: 0.82)
     snippet: "RATE_LIMITS = { 'default': 100, ... }"
  4. tests/test_upload.py::TestUploadHandler (score: 0.79)
     sig: "class TestUploadHandler:"

→ These locations are injected into the agent's initial context
→ Agent skips the "grep around trying to find the right files" phase
→ Saves 2-5 turns of exploration
```

**Integration point**: `RuntimeService.start_job()` calls `coderecon.recon(task=prompt)` and includes the results in the agent's initial prompt or as MCP context.

**Gate handling**: If the gate returns `UNSAT` (query too vague) or `BROAD` (would match everything), the context packet is skipped and the agent discovers files on its own. The gate result is logged for diagnostics.

### 8.2 During Execution: Live Structural Awareness

**When**: Agent is running. Files are being written.

**What CodeRecon does**: On each `file_changed` event, the daemon's file watcher detects the change and triggers incremental re-indexing. The agent can also call CodeRecon tools directly.

#### 8.2.1 Agent-Facing Tools

CodePlane provides CodeRecon tools to the agent via `CodeReconService.agent_tools()`. These are repo-bound and worktree-scoped:

```python
# In RuntimeService.start_job():
coderecon_tools = coderecon_service.agent_tools(
    repo_path=job.repo_path,
    worktree=job.worktree_name,
)

session_config = SessionConfig(
    workspace_path=worktree_path,
    prompt=prompt,
    tools=existing_tools + coderecon_tools,   # merged into agent's tool set
    ...
)
```

The agent sees these as regular function-calling tools:

```
Agent thinks: "I need to rename this function. What calls it?"

Agent calls: recon_impact(target="handle_request", justification="renaming")
Response: {
  "references": [
    { "path": "src/router.py", "line": 42, "certainty": "high" },
    { "path": "src/middleware.py", "line": 78, "certainty": "medium" },
    { "path": "tests/test_api.py", "line": 15, "certainty": "high" }
  ],
  "total_references": 8,
  "files_affected": 3,
  "ref_tier_breakdown": { "proven": 5, "strong": 2, "anchored": 1 }
}

→ Agent updates all 8 references
→ Agent flags the "medium" certainty one for special attention
```

The agent can also use:
- `recon(task="...")` — find relevant code for a subtask
- `recon_impact(target="...")` — blast radius before making a change
- `refactor_rename(symbol, new_name)` — index-backed rename with certainty
- `checkpoint(changed_files, lint=True, tests=True)` — lint + test + commit
- `graph_cycles()` — check if a new cycle was introduced

#### 8.2.2 Progress Checkpoints with Structural Diff

When the agent completes a logical step, CodePlane can run `semantic_diff(last_checkpoint_sha, current_HEAD)` to get a structural summary of what just changed:

```
After step 3 of 5:
  structural_changes:
    - added: RateLimiter class (new, 0 refs — safe)
    - body_changed: handle() in UploadHandler (12 refs, all proven)
    - signature_changed: config.RATE_LIMITS (4 refs, 1 unknown)

→ This feeds into the step-level view in the review UX
→ Reviewer can see structural impact per step, not just per job
```

**Integration point**: `RuntimeService.start_job()` calls `coderecon.recon(task=prompt)` and includes the results in the agent's initial prompt or as MCP context.

#### 8.2.3 Cycle Detection During Execution

After each significant commit or step, run `graph_cycles()`. If the agent introduced a new dependency cycle:

```
New cycle detected:
  src/api/handlers.py → src/core/validator.py → src/api/handlers.py

This cycle was NOT present before the agent started.
```

This is surfaced as a warning event during execution (not just at review time).

### 8.3 Post-Execution: The Review Experience

This is the primary integration point (detailed in §10).

### 8.4 Resolution: Merge Confidence

**When**: Operator decides to merge/create PR.

**What CodeRecon does**: Final structural validation.

```
Operator clicks "Merge"

CodePlane runs semantic_diff one last time (in case of late changes):
  Result: {
    breaking_summary: null,
    structural_changes: [...],     // All body_changed, all refs proven
    non_structural_changes: [...]  // docs, config only
  }

  → Confidence: HIGH
  → Auto-merge is safe

OR:

  Result: {
    breaking_summary: "signature changed with 3 UNKNOWN refs",
    ...
  }

  → Confidence: LOW
  → Show warning: "3 references could not be statically verified"
  → Operator must explicitly confirm
```

### 8.5 Post-Resolution: Repository Health Analytics

**When**: After the job is resolved (merged, discarded, etc.).

**What CodeRecon does**: Update the repo health dashboard.

- **Structural complexity metrics**: How many breaking changes did this job introduce?
- **Blast radius history**: Track blast radius over time per repository
- **Cycle debt**: Is the codebase accumulating circular dependencies? Did this merge add or remove cycles?
- **Community drift**: Are module boundaries getting blurrier? Did this job touch files in more communities than typical?
- **Reference quality trend**: Is the UNKNOWN reference percentage growing? (Sign of increasing dynamic dispatch or metaprogramming)

---

## 9. Agent Tool Provisioning

### 9.1 The Problem

The coding agent needs CodeRecon tools available in its session. But CodeRecon tools require a `repo` and `worktree` context that the agent shouldn't have to specify per-call — it's always working in one repo and one worktree.

### 9.2 The Solution: Pre-Bound Tools

The SDK's `RepoHandle` pre-binds `repo` and `worktree`:

```python
handle = sdk.repo("my-project", worktree="job-abc")

# These callables have repo + worktree pre-bound
# The agent only sees: recon(task="..."), not recon(repo="...", worktree="...", task="...")
tools = handle.as_openai_tools()
```

CodePlane's `CodeReconService.agent_tools()` returns these pre-bound tools.

### 9.3 Tool Selection

Not all CodeRecon tools should be available to every agent. The operator can configure which tools are exposed:

```python
# Default tool set for agents:
DEFAULT_AGENT_TOOLS = [
    "recon",           # Find relevant code
    "recon_impact",    # Blast radius
    "recon_map",       # Repository structure overview
    "checkpoint",      # Lint + test + commit
]

# Extended tool set (opt-in):
EXTENDED_AGENT_TOOLS = DEFAULT_AGENT_TOOLS + [
    "refactor_rename",  # Index-backed rename
    "refactor_move",    # Index-backed file move
    "graph_cycles",     # Cycle detection
    "semantic_diff",    # Structural diff of own changes
]
```

### 9.4 Tool Usage Tracking

When the agent calls a CodeRecon tool, the invocation is logged as a telemetry span (like any other tool call). This feeds into:

- **Review signals**: "Agent used `recon_impact` before renaming → it checked blast radius"
- **Story enrichment**: "Used structural search to find related middleware"
- **Analytics**: How often do agents use structural tools? Do they reduce retries?

---

## 10. Review UX: The Verification Dashboard

### 10.1 The Design

The review experience is reorganized around **structural categories**, not a flat file list:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  JOB: "Add rate limiting to upload endpoint"          ● review         │
│  Agent: claude-sonnet  │  14 files  │  Session 1 of 1                  │
│                                                                         │
│  ┌─── TRIAGE BAR ──────────────────────────────────────────────────┐   │
│  │                                                                  │   │
│  │  🔴 1 breaking    🟡 3 body changes    🟢 2 additive    ⚪ 8 other │   │
│  │  ──────────────────────────────────────────────────────────────  │   │
│  │  ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │   │
│  │  ^                                                               │   │
│  │  Review progress: 1/6 structural changes reviewed                │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─── STRUCTURAL CHANGES ───────────────────────────────────────────┐  │
│  │                                                                   │  │
│  │  ▼ BREAKING (1)                                        MUST CHECK │  │
│  │  ┌────────────────────────────────────────────────────────────┐   │  │
│  │  │  ⬡ config.RATE_LIMITS  ─ signature_changed               │   │  │
│  │  │    src/core/config.py:28                                   │   │  │
│  │  │    old: RATE_LIMITS: dict[str, int] = {"default": 100}    │   │  │
│  │  │    new: RATE_LIMITS: RateLimitConfig = RateLimitConfig()   │   │  │
│  │  │                                                            │   │  │
│  │  │    Impact: 4 references                                    │   │  │
│  │  │    ├── 2 proven  (src/api/middleware.py, src/core/app.py)  │   │  │
│  │  │    ├── 1 strong  (src/api/v2/upload.py)                   │   │  │
│  │  │    └── 1 unknown (src/plugins/custom_limiter.py) ⚠        │   │  │
│  │  │                                                            │   │  │
│  │  │    Tests: src/tests/test_config.py ✓ covers this          │   │  │
│  │  │           src/tests/test_plugins.py ✗ NOT updated          │   │  │
│  │  │                                                            │   │  │
│  │  │    [View Diff]  [View Impact Graph]  [View in Story]       │   │  │
│  │  └────────────────────────────────────────────────────────────┘   │  │
│  │                                                                   │  │
│  │  ▼ BODY CHANGES (3)                                    SHOULD CHECK │  │
│  │  ┌────────────────────────────────────────────────────────────┐   │  │
│  │  │  ⬡ UploadHandler.handle()  ─ body_changed  risk: medium   │   │  │
│  │  │    src/api/v2/upload.py:35-80                              │   │  │
│  │  │    12 refs (all proven) │ 2 test files cover this          │   │  │
│  │  │    [View Diff]  [Scaffold]                                 │   │  │
│  │  │                                                            │   │  │
│  │  │  ⬡ validate_upload()  ─ body_changed  risk: low            │   │  │
│  │  │    src/api/v2/upload.py:85-120                             │   │  │
│  │  │    3 refs (all proven) │ tests cover this                  │   │  │
│  │  │                                                            │   │  │
│  │  │  ⬡ TestUploadHandler.test_rate_limit()  ─ body_changed     │   │  │
│  │  │    tests/test_upload.py:45-90                              │   │  │
│  │  │    0 refs (test file — only called by runner)              │   │  │
│  │  └────────────────────────────────────────────────────────────┘   │  │
│  │                                                                   │  │
│  │  ▶ ADDITIVE (2)                                      LIKELY FINE  │  │
│  │    RateLimiter class (new, 89 lines, 0 existing refs)             │  │
│  │    RateLimitConfig dataclass (new, 12 lines, 0 existing refs)     │  │
│  │                                                                   │  │
│  │  ▶ NON-STRUCTURAL (8)                                  GLANCE     │  │
│  │    docs/api.md, .env.example, requirements.txt, Makefile,         │  │
│  │    README.md, config/settings.yaml, tests/conftest.py,            │  │
│  │    tests/test_rate_limiter.py                                     │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌─── COMMUNITY CLUSTERS ───────────────────────────────────────────┐  │
│  │  api_layer (5 files) ─── config (2 files) ─── tests (4 files)   │  │
│  │  [1 new cycle detected: handlers.py ↔ middleware.py]             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌─── NAVIGATION ──────────────────────────────────────────────────┐   │
│  │  [Read Story]  [Timeline View]  [Full Diff]  [Ask About Code]   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Triage Categories

| Category | Criteria | Reviewer Action | Visual |
|----------|----------|-----------------|--------|
| **BREAKING** | `structural_severity == "breaking"` — signature changes, removals | Must review the diff + verify all UNKNOWN refs | 🔴 Red |
| **BODY CHANGES** | `change == "body_changed"` — implementation modified, signature intact | Should review, especially if refs include UNKNOWN | 🟡 Yellow |
| **ADDITIVE** | `change == "added"` and `reference_count == 0` — new code with no existing callers | Likely fine — scan the scaffold | 🟢 Green |
| **NON-STRUCTURAL** | Docs, config, build files, test-only changes | Glance — scaffold view sufficient | ⚪ Gray |

### 10.3 Risk Scoring Per Change

Each structural change gets a composite risk score:

```
risk = f(structural_severity, ref_tier_distribution, test_coverage)

Where:
  structural_severity:
    breaking = 1.0, body_changed = 0.5, added = 0.1, non_structural = 0.0

  ref_tier_penalty:
    (unknown_refs / total_refs) * 0.4 +
    (anchored_refs / total_refs) * 0.1

  test_coverage_bonus:
    -0.2 if all affected test files were updated
    +0.1 per affected test file NOT updated

  risk = clamp(severity + ref_tier_penalty + test_coverage_bonus, 0, 1)
```

### 10.4 Drill-Down: Impact Graph View

When the reviewer clicks "View Impact Graph" on a breaking change:

```
┌──────────────────────────────────────────────────────────┐
│  IMPACT: config.RATE_LIMITS                              │
│                                                          │
│          ┌─────────────────────┐                         │
│          │ config.RATE_LIMITS  │ ← CHANGED               │
│          │ (signature_changed) │                         │
│          └──────┬──────────────┘                         │
│                 │                                         │
│       ┌─────────┼────────────┬──────────────┐            │
│       ▼         ▼            ▼              ▼            │
│  ┌─────────┐ ┌────────┐ ┌────────┐ ┌─────────────────┐  │
│  │middleware│ │ app.py │ │upload.py│ │custom_limiter.py│  │
│  │PROVEN ✓ │ │PROVEN ✓│ │STRONG ✓│ │ UNKNOWN ⚠      │  │
│  │line 42  │ │line 18 │ │line 65 │ │ line 12        │  │
│  └─────────┘ └────────┘ └────────┘ └─────────────────┘  │
│                                                          │
│  Tests:                                                  │
│  ✓ test_config.py (covers config.RATE_LIMITS directly)   │
│  ✗ test_plugins.py (covers custom_limiter.py — NOT       │
│    updated in this job)                                  │
│                                                          │
│  [Click any node to view that file's diff]               │
└──────────────────────────────────────────────────────────┘
```

### 10.5 Scaffold View for Low-Risk Files

For ADDITIVE and NON-STRUCTURAL categories, show the scaffold instead of the full diff:

```
┌──────────────────────────────────────────────────────────┐
│  📄 src/core/rate_limiter.py (NEW — 89 lines)            │
│                                                          │
│  imports:                                                │
│    asyncio, time                                         │
│    collections: defaultdict                              │
│    dataclasses: dataclass, field                         │
│                                                          │
│  symbols:                                                │
│    @dataclass                                            │
│    class RateLimitConfig [8-19]                          │
│      field requests_per_minute: int = 100                │
│      field burst_size: int = 10                          │
│      field window_seconds: float = 60.0                  │
│                                                          │
│    class RateLimiter [22-89]                             │
│      method __init__(self, config) [25-32]               │
│      method check(self, key) -> bool [35-58]             │
│      method _cleanup_window(self, key) [60-72]           │
│      method reset(self, key) [74-80]                     │
│      method stats(self) -> dict [82-89]                  │
│                                                          │
│  [Expand to Full Diff ▸]                                 │
└──────────────────────────────────────────────────────────┘
```

### 10.6 Community Clustering

The Louvain communities provide a grouping layer on top of the file list:

```
This job touches files in 3 detected communities:

  api_layer (5 files):
    src/api/v2/upload.py, src/api/middleware.py,
    src/api/handlers.py, src/api/__init__.py,
    src/core/validator.py

  config (2 files):
    src/core/config.py, config/settings.yaml

  tests (4 files):
    tests/test_upload.py, tests/test_config.py,
    tests/test_rate_limiter.py, tests/conftest.py
```

The reviewer can collapse/expand communities to navigate by concern rather than by file.

### 10.7 Cycle Warnings

If `graph_cycles()` detects cycles that weren't present before the job:

```
⚠ NEW DEPENDENCY CYCLE INTRODUCED

  src/api/handlers.py
    └── imports from src/core/validator.py
        └── imports from src/api/handlers.py   ← CYCLE

  This cycle did NOT exist before this job.
  The agent's changes created a circular dependency.

  Recommendation: Extract shared types to a separate module.
```

---

## 11. The Multi-Session Reality

### 11.1 The Problem

A "job" in CodePlane is not necessarily one task. Real developer behavior includes:

1. **Session handoffs**: Agent reaches review → operator sends "also fix the typo in README" → new session starts (session_count increments)
2. **Direction changes**: Agent is working on feature A → operator says "actually, forget that, do B instead" → same job, completely different task
3. **Scope creep**: "Add rate limiting" becomes "add rate limiting AND refactor the config system AND update the docs AND fix that bug I noticed"
4. **Unrelated tasks**: Developer crams unrelated fixes into one session because it's convenient

Example of a multi-session job:

```
Job: "Add rate limiting"
├── Session 1: Agent adds rate limiting (review)
│   └── Operator: "looks good but also fix the imports in utils.py"
├── Session 2: Agent fixes imports (review)
│   └── Operator: "while you're at it, that validator has a bug"
└── Session 3: Agent fixes validator bug (review → merged)

Final diff: 14 files changed
  - 6 files: rate limiting (the original task)
  - 3 files: import cleanup (session 2 add-on)
  - 3 files: validator bugfix (session 3 add-on)
  - 2 files: overlapping (touched in multiple sessions)
```

The reviewer sees **one flat diff of 14 files**. The structural categories (breaking/body/additive/non-structural) help, but they don't tell you which files belong to which task.

### 11.2 Session Segmentation with CodeRecon

CodeRecon's `semantic_diff` can run per-session to segment changes:

```
Session boundaries (from job's session_count + git log):
  Session 1: commits c1..c4  (sha range)
  Session 2: commits c5..c7
  Session 3: commits c8..c10

For each session:
  semantic_diff(session_start_sha, session_end_sha)

Results:

Session 1 — "Add rate limiting" (original task):
  structural_changes:
    added: RateLimiter, RateLimitConfig
    body_changed: UploadHandler.handle(), validate_upload()
    signature_changed: config.RATE_LIMITS
  communities: [api_layer, config]

Session 2 — "Fix imports" (operator add-on):
  structural_changes:
    body_changed: utils.py (3 functions, import reordering only)
  communities: [utils]

Session 3 — "Fix validator bug" (operator add-on):
  structural_changes:
    body_changed: Validator.validate_fields() — risk: high
      (12 refs, 2 unknown)
    body_changed: test_validator.py
  communities: [validation]
```

### 11.3 The Session Timeline View

```
┌─────────────────────────────────────────────────────────────────────┐
│  SESSION TIMELINE                                                    │
│                                                                      │
│  ┌─── Session 1: "Add rate limiting" ─────────────────────────────┐ │
│  │  Duration: 12 min │ 8 turns │ 6 files │ 1 breaking change      │ │
│  │                                                                 │ │
│  │  Structural:                                                    │ │
│  │  🔴 config.RATE_LIMITS signature changed (4 refs, 1 unknown)    │ │
│  │  🟡 UploadHandler.handle() body changed (12 refs, all proven)   │ │
│  │  🟢 RateLimiter class added (new, 0 refs)                       │ │
│  │  🟢 RateLimitConfig dataclass added (new, 0 refs)               │ │
│  │                                                                 │ │
│  │  [Expand Session ▸]                                             │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─── Session 2: "Fix imports in utils.py" ───────────────────────┐ │
│  │  Duration: 3 min │ 2 turns │ 3 files │ 0 breaking changes      │ │
│  │                                                                 │ │
│  │  All body_changed, all refs proven, import-only edits           │ │
│  │  Risk: LOW — cosmetic restructuring                             │ │
│  │                                                                 │ │
│  │  [Expand Session ▸]                                             │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─── Session 3: "Fix validator bug" ─────────────────────────────┐ │
│  │  Duration: 5 min │ 4 turns │ 3 files │ 0 breaking (but risky)  │ │
│  │                                                                 │ │
│  │  🟡 Validator.validate_fields() body changed                    │ │
│  │     12 refs, 2 UNKNOWN ⚠ — reviewer must verify                │ │
│  │                                                                 │ │
│  │  [Expand Session ▸]                                             │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─── CROSS-SESSION CONCERNS ─────────────────────────────────────┐ │
│  │  ⚠ 2 files touched in multiple sessions:                       │ │
│  │    src/core/config.py — session 1 (signature change) +         │ │
│  │                         session 3 (body change)                │ │
│  │    tests/conftest.py  — session 1 (new fixture) +              │ │
│  │                         session 3 (fixture update)             │ │
│  │                                                                 │ │
│  │  These files accumulated changes across sessions.               │ │
│  │  The combined diff may not match either session's intent.       │ │
│  │  Review the final state carefully.                              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  [View Combined Diff]  [View Story]  [View by Community]            │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.4 Direction Change Detection

With CodeRecon's community analysis, we detect when sessions pivot to unrelated concerns:

**Detection heuristic**: If a session's structural changes touch a community that has **zero overlap** with the previous session's communities, it's a direction change.

```python
def detect_direction_changes(
    session_diffs: list[SessionSemanticDiff],
    communities: list[Community],
) -> list[DirectionChange]:
    changes = []
    for i in range(1, len(session_diffs)):
        prev_communities = get_communities_for_files(
            session_diffs[i-1].changed_files, communities)
        curr_communities = get_communities_for_files(
            session_diffs[i].changed_files, communities)

        overlap = prev_communities & curr_communities
        if not overlap:
            changes.append(DirectionChange(
                from_session=i, to_session=i + 1,
                from_communities=prev_communities,
                to_communities=curr_communities,
                is_unrelated=True))
        elif len(curr_communities - prev_communities) > 0:
            changes.append(DirectionChange(
                from_session=i, to_session=i + 1,
                added_communities=curr_communities - prev_communities,
                is_scope_expansion=True))
    return changes
```

### 11.5 File Ownership Across Sessions

When a file is modified in multiple sessions, the final diff is a composite. CodeRecon can decompose this:

```
src/core/config.py touched in sessions 1 and 3:

Session 1 changes (semantic_diff c0..c4):
  config.RATE_LIMITS: signature_changed
    dict[str, int] → RateLimitConfig

Session 3 changes (semantic_diff c7..c10):
  config.VALIDATOR_TIMEOUT: body_changed
    default value 30 → 60

Combined: Both changes present in final diff
  But they're UNRELATED — different symbols, different concerns

Annotation in diff viewer:
  Line 28: RATE_LIMITS = RateLimitConfig()    [Session 1 — rate limiting]
  Line 45: VALIDATOR_TIMEOUT = 60              [Session 3 — validator fix]
```

### 11.6 The "Messy Session" Warning

When CodeRecon detects multiple unrelated concerns in a single session (without even multiple sessions):

```python
def detect_messy_session(
    semantic_diff: SemanticDiffResult,
    communities: list[Community],
) -> MessySessionWarning | None:
    touched_communities = get_communities_for_changes(
        semantic_diff.structural_changes, communities)
    if len(touched_communities) >= 3:
        return MessySessionWarning(
            community_count=len(touched_communities),
            communities=touched_communities,
            suggestion="This session touches multiple unrelated areas. "
                       "Consider splitting into separate reviews.")
    return None
```

---

## 12. Structural Story Generation

### 12.1 Baseline Story Architecture

The story pipeline without CodeRecon:

```
  1. Collect file_write spans chronologically
  2. Extract motivation_summary per span
  3. Build numbered reference list: [[1]] path/to/file.py — "motivation"
  4. Send to LLM with instruction to weave narrative
  5. LLM generates prose with [[N]] markers
  6. Markers rendered as InlineDiffBlock components
```

The LLM sees: *"File X was written with motivation Y."* It doesn't know **what** changed structurally or **what** the change impacts.

### 12.2 Structurally-Enriched Story

With CodeRecon, the story prompt includes structural facts:

```
Baseline prompt context per change:
  [[3]] src/core/config.py — "Update rate limit configuration"

Structurally-enriched prompt context:
  [[3]] src/core/config.py — "Update rate limit configuration"
  STRUCTURAL: signature_changed config.RATE_LIMITS
    dict[str, int] → RateLimitConfig (type change)
    Impact: 4 references across 3 files
    Risk: 1 UNKNOWN reference in src/plugins/custom_limiter.py
    Test gap: tests/test_plugins.py was NOT updated
```

The LLM can now generate:

> I changed `RATE_LIMITS` from a plain dictionary to a `RateLimitConfig` dataclass [[3]]. This is a **breaking change** — the type went from `dict[str, int]` to a structured config object. Four call sites reference this constant: three are statically verified (middleware, app startup, and the upload handler), but the plugin system's reference in `custom_limiter.py` uses dynamic attribute access and **could not be automatically verified**. Note that `test_plugins.py` was not updated in this session.

Compare to what the LLM generates without structural context:

> I updated the rate limit configuration in config.py [[3]] to use a more structured approach.

The first version is a **review document**. The second is a placeholder.

### 12.3 Per-Session Story Chapters

For multi-session jobs, the story can be segmented:

```
## Session 1: Rate Limiting

The main task was adding rate limiting to the upload endpoint. [narrative with [[N]] refs]

## Session 2: Import Cleanup (operator request)

After review, the operator asked to clean up imports in utils.py. [narrative]

## Session 3: Validator Bugfix (operator request)

The operator noticed a validation bug during review. [narrative]

---
**Cross-session note**: `config.py` was modified in both sessions 1 and 3
for unrelated reasons. The final state combines rate limit config changes
with a validator timeout adjustment.
```

---

## 13. Event Bridge: CodeRecon → CodePlane → Frontend

### 13.1 The Three-Layer Event Pipeline

```
CodeRecon Daemon              CodePlane Backend              React Frontend
(stdout NDJSON)               (event bus)                   (SSE)
────────────────              ────────────────              ──────────────

index.started           →     DomainEvent(                →  SSE: repo_indexing_started
                               kind="coderecon_index_started")

index.progress          →     DomainEvent(                →  SSE: repo_indexing_progress
  {phase, indexed,             kind="coderecon_index_progress",
   total, files_by_ext}        payload={phase, pct, langs})

index.phase             →     (merged into progress)
  {phase: "resolving_refs"}

index.complete          →     DomainEvent(                →  SSE: repo_indexing_complete
  {stats}                      kind="coderecon_index_complete",
                               payload={stats, health})

index.error             →     DomainEvent(                →  SSE: repo_indexing_error
  {error}                      kind="coderecon_index_error")

freshness.stale         →     DomainEvent(                →  SSE: repo_freshness_changed
  {repo, worktree}             kind="coderecon_freshness",    {fresh: false, pending: N}
                               payload={fresh: false})

freshness.fresh         →     DomainEvent(                →  SSE: repo_freshness_changed
  {repo, worktree}             kind="coderecon_freshness",    {fresh: true}
                               payload={fresh: true})

watcher.changes         →     (triggers reconcile_worktree,
  {repo, worktree, count}      no frontend event — internal)

repo.activated          →     DomainEvent(                →  SSE: repo_coderecon_ready
  {repo, worktrees}            kind="coderecon_repo_ready")

analysis.tier1.complete →     DomainEvent(                →  (no frontend event —
  {diagnostics}                kind="coderecon_lint_complete")  available via API)

analysis.tier2.complete →     DomainEvent(                →  (no frontend event —
  {passed, failed}             kind="coderecon_test_complete")  available via API)
```

### 13.2 Frontend Event Handling

```typescript
// In the SSE event dispatcher:
case "repo_indexing_progress":
  store.setIndexingProgress(payload.repoId, {
    phase: payload.phase,
    percent: payload.pct,
    languages: payload.langs,
  });
  break;

case "repo_indexing_complete":
  store.setIndexingComplete(payload.repoId, payload.stats);
  break;

case "repo_freshness_changed":
  store.setFreshness(payload.repoId, payload.fresh);
  break;

case "structural_analysis_ready":
  store.setAnalysis(payload.jobId, payload.analysis);
  break;
```

### 13.3 Job-Scoped Events

When a job transitions to `review` state, CodePlane runs structural analysis and emits:

```
structural_analysis_ready
  Payload: { jobId, summary, triageCounts, riskScore }
  When: Job reaches review state and analysis completes

structural_analysis_session
  Payload: { jobId, sessionNumber, summary, directionChange }
  When: Per-session analysis completes (for multi-session jobs)
```

---

## 14. Data Flow Diagrams

### 14.1 Repo Onboarding

```
Operator clicks "Add Repository"
       │
       ▼
┌──────────────┐     ┌──────────────────┐
│ RepoService   │────►│ CodeReconService  │
│ create_repo() │     │ register_repo()  │
└──────┬───────┘     └────────┬─────────┘
       │                      │ NDJSON over stdio
       │                      ▼
       │             ┌──────────────────┐
       │             │ CodeRecon Daemon  │
       │             │ register + index │
       │             └────────┬─────────┘
       │                      │
       │   index.started ◄────┤
       │   index.progress ◄───┤  (repeated)
       │   index.phase ◄──────┤
       │   index.complete ◄───┘
       │
       ├── Bridge to SSE: repo_indexing_progress
       ▼
[Frontend: Indexing progress UI]
       │
       ▼
[Frontend: Repo Health Dashboard ready]
```

### 14.2 Job Start → Review (Happy Path)

```
Operator submits task
       │
       ▼
┌──────────────┐     ┌──────────────────┐
│ RuntimeService│────►│ CodeReconService  │
│ start_job()  │     │ recon(task=...)   │
└──────┬───────┘     └────────┬─────────┘
       │                      │
       │  context_packet ◄────┘  (ranked code locations)
       │
       │  Agent tools ◄── coderecon.agent_tools(repo, worktree)
       │
       ▼
┌──────────────┐
│ AgentAdapter  │──── stdio ────►[Agent Process]
│ create_session│                    │
│ (with CR tools)                   │  Agent can call:
└──────┬───────┘                    │  recon(), recon_impact(),
       │                            │  checkpoint(), refactor_rename()
       │  ◄─────────────────────────┘  + file_changed events
       │
       ▼
┌──────────────┐     ┌──────────────────┐
│ DiffService   │     │ CodeRecon Daemon  │
│ on file_change│     │ watcher detects  │
└──────┬───────┘     │ → auto-reconcile │
       │             └──────────────────┘
       │
       │  diff_update SSE event
       ▼
[Frontend: live diff view]

       ... agent completes ...

┌──────────────┐     ┌──────────────────────────────┐
│ RuntimeService│────►│ CodeReconService              │
│ → review state│    │ semantic_diff(base, HEAD)     │
└──────┬───────┘     │ communities()                 │
       │             │ cycles()                      │
       │             └──────────────┬───────────────┘
       │                            │
       │  structural_analysis ◄─────┘
       │
       ▼
┌──────────────┐
│ StoryService  │◄──── structural context from CodeRecon
│ generate()   │
└──────┬───────┘
       │
       │  structural_analysis_ready SSE
       ▼
[Frontend: Verification Dashboard]
```

### 14.3 On-Demand Drill-Down

```
Reviewer clicks "View Impact" on config.RATE_LIMITS
       │
       ▼
┌──────────────┐     ┌────────────────────────┐
│ Frontend      │────►│ API: GET /jobs/{id}/   │
│ ImpactView    │     │   impact/{symbol}      │
└──────┬───────┘     └────────┬───────────────┘
       │                      │
       │                      ▼
       │             ┌──────────────────┐
       │             │ CodeReconService  │
       │             │ impact(symbol)   │
       │             └────────┬─────────┘
       │                      │ NDJSON over stdio
       │                      ▼
       │             ┌──────────────────┐
       │             │ CodeRecon Daemon  │
       │             │ recon_impact()   │
       │             └────────┬─────────┘
       │                      │
       │  ImpactResult ◄──────┘
       ▼
  Impact graph visualization
```

---

## 15. API Surface

### 15.1 Repo-Level Endpoints

```
POST /api/repos
  → Create repo + trigger CodeRecon registration and indexing
  → Body: { path, branch, codereconEnabled? }
  → Response: RepoResponse (includes indexingStatus)

GET /api/repos/{repo_id}/index-status
  → Current indexing status, freshness, stats
  → Response: IndexStatusResponse

POST /api/repos/{repo_id}/reindex
  → Trigger manual re-index (incremental or full)
  → Body: { mode: "incremental" | "full" }
  → Response: 202 Accepted

GET /api/repos/{repo_id}/health
  → Structural health: cycles, communities, ref quality
  → Response: RepoHealthResponse

GET /api/repos/{repo_id}/communities
  → Module community clustering
  → Response: CommunityResponse[]

GET /api/repos/{repo_id}/cycles
  → Dependency cycles
  → Response: CycleResponse[]
```

### 15.2 Job-Level Endpoints

```
GET /api/jobs/{job_id}/structural-analysis
  → Cached SemanticDiffResult + communities + cycles
  → Computed on transition to review state
  → Response: StructuralAnalysisResponse

GET /api/jobs/{job_id}/structural-analysis/sessions
  → Per-session breakdown
  → Response: SessionAnalysisResponse[]

GET /api/jobs/{job_id}/impact/{symbol}
  → On-demand blast radius for a specific symbol
  → Response: ImpactResponse

GET /api/jobs/{job_id}/scaffold/{file_path:path}
  → Compact structural representation of a file
  → Response: ScaffoldResponse

GET /api/jobs/{job_id}/structural-analysis/cycles
  → New dependency cycles introduced by this job
  → Response: CycleResponse[]
```

### 15.3 Response Schemas

```python
# ── Index Status ──────────────────────────────────────

class IndexStatusResponse(CamelModel):
    status: str                        # "indexing" | "ready" | "error" | "not_configured"
    fresh: bool
    phase: str | None                  # Current indexing phase (if indexing)
    progress: float | None             # 0.0-1.0 (if indexing)
    stats: IndexStatsPayload | None    # Populated when ready
    last_indexed_at: str | None

class IndexStatsPayload(CamelModel):
    files: int
    symbols: int
    languages: list[str]
    duration_ms: int
    ref_quality: RefQualityPayload

class RefQualityPayload(CamelModel):
    proven: int
    strong: int
    anchored: int
    unknown: int
    verified_percent: float            # (proven + strong) / total

# ── Repo Health ───────────────────────────────────────

class RepoHealthResponse(CamelModel):
    index_status: IndexStatusResponse
    cycles: list[CyclePayload]
    communities: list[CommunityPayload]
    ref_quality: RefQualityPayload

# ── Structural Analysis (Job) ─────────────────────────

class StructuralChangePayload(CamelModel):
    path: str
    kind: str                          # function, class, variable, method
    name: str
    change: str                        # added, removed, signature_changed, body_changed, renamed
    structural_severity: str           # breaking, non_breaking, additive
    behavior_change_risk: str          # high, medium, low
    old_sig: str | None
    new_sig: str | None
    impact: ImpactPayload

class ImpactPayload(CamelModel):
    reference_count: int
    ref_tiers: RefTierBreakdown
    referencing_files: list[str]
    affected_test_files: list[str]
    confidence: str                    # high, medium, low

class RefTierBreakdown(CamelModel):
    proven: int
    strong: int
    anchored: int
    unknown: int

class StructuralAnalysisResponse(CamelModel):
    structural_changes: list[StructuralChangePayload]
    non_structural_changes: list[NonStructuralChangePayload]
    summary: str
    breaking_summary: str | None
    scope: AnalysisScopePayload
    triage: TriagePayload              # aggregated counts per category
    risk_score: float                  # 0-1 composite
    communities: list[CommunityPayload]
    new_cycles: list[CyclePayload]

class SessionAnalysisResponse(CamelModel):
    session_number: int
    session_prompt: str
    structural_analysis: StructuralAnalysisResponse
    direction_change: DirectionChangePayload | None
    cross_session_files: list[str]

class ScaffoldResponse(CamelModel):
    path: str
    language: str
    total_lines: int
    imports: list[str]
    symbols: list[str]                 # Hierarchical, indented

class CommunityPayload(CamelModel):
    community_id: int
    name: str
    members: list[str]
    size: int
    representative: str
    changes_in_job: int

class CyclePayload(CamelModel):
    nodes: list[str]
    size: int
    is_new: bool                       # True if not present before job
```

### 15.4 SSE Events (Summary)

| Event | Scope | Payload | When |
|-------|-------|---------|------|
| `repo_indexing_started` | Repo | `{repoId, fileCount}` | `register_repo()` triggers indexing |
| `repo_indexing_progress` | Repo | `{repoId, phase, pct, langs}` | During indexing |
| `repo_indexing_complete` | Repo | `{repoId, stats, health}` | Indexing finished |
| `repo_indexing_error` | Repo | `{repoId, error}` | Indexing failed |
| `repo_freshness_changed` | Repo | `{repoId, fresh, pending}` | Index freshness transition |
| `coderecon_unavailable` | Global | `{reason}` | Daemon crashed |
| `coderecon_available` | Global | `{}` | Daemon recovered |
| `structural_analysis_ready` | Job | `{jobId, summary, triage, risk}` | Job reaches review + analysis done |
| `structural_analysis_session` | Job | `{jobId, session, summary, directionChange}` | Per-session analysis done |

---

## 16. Frontend Architecture

### 16.1 New Components

```
src/components/
├── repo/
│   ├── IndexingProgress.tsx            # Onboarding progress bar + phases
│   ├── RepoHealthDashboard.tsx         # Cycles, communities, ref quality
│   ├── FreshnessIndicator.tsx          # Small badge: fresh/stale
│   └── CommunityGraph.tsx              # Visual community clustering
├── review/
│   ├── StructuralDashboard.tsx         # Main verification dashboard
│   │   ├── TriageBar.tsx               # Visual triage summary bar
│   │   ├── StructuralChangeCard.tsx    # Individual change card
│   │   ├── ImpactGraph.tsx             # Reference impact visualization
│   │   ├── ScaffoldView.tsx            # Compact file representation
│   │   └── CommunityCluster.tsx        # Module grouping
│   ├── SessionTimeline.tsx             # Multi-session timeline view
│   │   ├── SessionCard.tsx             # Per-session summary
│   │   ├── DirectionChangeWarning.tsx  # Cross-session concern alert
│   │   └── CrossSessionFiles.tsx       # Files touched in multiple sessions
│   └── MergeConfidence.tsx             # Confidence indicator at merge time
├── DiffViewer.tsx                      # Extended with structural overlays
│   ├── StructuralAnnotations.tsx       # Ref count + tier overlays
│   └── SessionOwnership.tsx            # "Changed in session N" markers
├── StoryBanner.tsx                     # Extended with session chapters
│   └── SessionChapters.tsx             # Per-session story segments
└── CodeReconStatus.tsx                 # Global: daemon up/down indicator
```

### 16.2 Zustand Store Extensions

```typescript
// ── Index & Health State ──────────────────────────

interface IndexState {
  // Per-repo index status
  indexStatus: Record<string, IndexStatusResponse>;
  repoHealth: Record<string, RepoHealthResponse>;

  // Actions
  setIndexingProgress: (repoId: string, progress: IndexProgress) => void;
  setIndexingComplete: (repoId: string, stats: IndexStats) => void;
  setFreshness: (repoId: string, fresh: boolean) => void;
  setRepoHealth: (repoId: string, health: RepoHealthResponse) => void;
}

// ── Structural Analysis State ─────────────────────

interface StructuralState {
  // Per-job structural analysis
  analyses: Record<string, StructuralAnalysisResponse>;
  sessionAnalyses: Record<string, SessionAnalysisResponse[]>;

  // On-demand drill-down cache
  impacts: Record<string, ImpactResponse>;
  scaffolds: Record<string, ScaffoldResponse>;

  // Global daemon status
  codereconAvailable: boolean;

  // Actions
  setAnalysis: (jobId: string, analysis: StructuralAnalysisResponse) => void;
  setSessionAnalyses: (jobId: string, sessions: SessionAnalysisResponse[]) => void;
  setImpact: (key: string, impact: ImpactResponse) => void;
  setScaffold: (key: string, scaffold: ScaffoldResponse) => void;
  setCodereconAvailable: (available: boolean) => void;
}
```

### 16.3 View Modes

The review tab gets multiple view modes accessible via tabs:

```
┌─────────────────────────────────────────────────────────┐
│  [Dashboard]  [Timeline]  [Story]  [Full Diff]          │
│                                                          │
│  Dashboard: Structural triage (§10.1)                    │
│  Timeline:  Session-by-session view (§11.3)              │
│  Story:     Enhanced narrative with structural context    │
│  Full Diff: Current DiffViewer (upgraded with overlays)  │
└─────────────────────────────────────────────────────────┘
```

**Dashboard** is the default entry point. From there, the reviewer navigates to specific diffs, stories, or timeline views as needed.

When CodeRecon is unavailable (daemon down), the Dashboard and Timeline tabs show a graceful fallback:

```
┌─────────────────────────────────────────────────────────┐
│  Structural analysis unavailable                         │
│  Showing standard diff view. CodeRecon daemon is down.   │
│  [Retry]                                                 │
└─────────────────────────────────────────────────────────┘
```

The Story and Full Diff tabs still work — they don't require CodeRecon.

### 16.4 DiffViewer Enhancements

The DiffViewer includes structural overlays:

```
In the Monaco editor, when viewing a changed function:

┌──────────────────────────────────────────────────────────┐
│  35 │ def handle(self, request: UploadRequest) -> Response:    │
│     │ ┌──────────────────────────────────────────────┐  │
│     │ │ 12 references │ all proven │ 2 test files ✓   │  │
│     │ │ body_changed │ risk: low                      │  │
│     │ └──────────────────────────────────────────────┘  │
│  36 │     limiter = self._get_limiter(request.user_id)  │
│  37 │ +   if not limiter.check(request.user_id):        │
│  38 │ +       raise HTTPException(429, "Rate limited")   │
│  39 │     validated = self.validator.validate(request)    │
└──────────────────────────────────────────────────────────┘
```

For files touched in multiple sessions:

```
┌──────────────────────────────────────────────────────────┐
│  28 │ RATE_LIMITS = RateLimitConfig()     [Session 1]    │
│     │ ...                                                │
│  45 │ VALIDATOR_TIMEOUT = 60              [Session 3]    │
└──────────────────────────────────────────────────────────┘
```

---

## 17. Repository Settings & Configuration

### 17.1 Per-Repo CodeRecon Settings

The repo settings page includes a CodeRecon section:

```
┌──────────────────────────────────────────────────────────────┐
│  CODERECON SETTINGS                                           │
│                                                              │
│  ☑ Enable structural analysis                                │
│                                                              │
│  Excluded Paths:                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  node_modules/                                        │   │
│  │  .git/                                                │   │
│  │  dist/                                                │   │
│  │  vendor/                                              │   │
│  │  [+ Add exclusion]                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Agent Tools:                                                │
│  ☑ recon (code search)                                       │
│  ☑ recon_impact (blast radius)                               │
│  ☑ checkpoint (lint + test + commit)                         │
│  ☐ refactor_rename (index-backed rename)                     │
│  ☐ refactor_move (index-backed file move)                    │
│  ☐ graph_cycles (cycle detection)                            │
│  ☐ semantic_diff (structural diff)                           │
│                                                              │
│  [Save]  [Re-index Now]                                      │
└──────────────────────────────────────────────────────────────┘
```

### 17.2 Global CodeRecon Settings

```
┌──────────────────────────────────────────────────────────────┐
│  CODERECON (Global)                                           │
│                                                              │
│  Daemon Status: ● Running (PID 12345)                        │
│  Version: 0.9.2                                              │
│  Registered Repos: 3                                         │
│  Total Indexed Files: 8,420                                  │
│                                                              │
│  Home Directory: ~/.coderecon                                │
│                                                              │
│  [Restart Daemon]  [View Logs]                               │
└──────────────────────────────────────────────────────────────┘
```

### 17.3 Database Schema Extension

Additional columns on the `repos` table:

```python
class RepoRow(Base):
    # ... existing columns ...

    # CodeRecon integration
    coderecon_enabled: bool = True
    coderecon_excluded_paths: str | None = None      # JSON list
    coderecon_agent_tools: str | None = None          # JSON list of enabled tool names
    coderecon_last_indexed_at: float | None = None
    coderecon_index_stats: str | None = None          # JSON: {files, symbols, langs, ...}
```

---

## 18. Migration Strategy

### Phase 1: Foundation — SDK Integration & Repo Onboarding

1. Add `coderecon` as a dependency (`uv add coderecon`)
2. Create `CodeReconService` in `backend/services/`
3. Wire daemon lifecycle into `lifespan.py` (start/stop)
4. Event bridge: daemon events → CodePlane event bus → SSE
5. DB migration: `coderecon_*` columns on `repos` table
6. API: `POST /repos` triggers registration + indexing
7. API: `GET /repos/{id}/index-status`, `GET /repos/{id}/health`
8. Frontend: `IndexingProgress`, `FreshnessIndicator`, `RepoHealthDashboard`
9. Frontend: `CodeReconStatus` global indicator (daemon up/down)
10. Graceful degradation: all CodeRecon features optional

### Phase 2: Review Dashboard (Core UX)

1. Compute structural analysis on job → review transition
2. Cache results (new DB table `structural_analysis_snapshots`)
3. API: `GET /jobs/{id}/structural-analysis`, `/impact/{symbol}`, `/scaffold/{path}`
4. `StructuralDashboard` component with triage bar
5. `StructuralChangeCard` with impact summary
6. `ScaffoldView` for low-risk files
7. `ImpactGraph` for drill-down
8. New view mode tabs in `JobDetailScreen`
9. SSE: `structural_analysis_ready`

### Phase 3: Multi-Session Intelligence

1. Per-session `semantic_diff` computation (session boundaries from git log)
2. `SessionTimeline` component with session cards
3. Direction change detection via community overlap
4. Cross-session file ownership annotations
5. Session chapter story generation
6. API: `GET /jobs/{id}/structural-analysis/sessions`

### Phase 4: Agent Tool Provisioning

1. `CodeReconService.agent_tools()` integration
2. Pass pre-bound tools via `SessionConfig`
3. Repo settings UI for tool selection
4. Tool usage tracking in telemetry spans
5. Pre-execution `recon()` context packet

### Phase 5: Execution-Time Integration

1. Live structural diff per step (per-checkpoint `semantic_diff`)
2. Cycle detection warnings during execution
3. DiffViewer structural overlays (ref counts, risk badges)
4. Merge confidence scoring

### Phase 6: Repository Health

1. `RepoHealthDashboard` with trends over time
2. Cycle debt tracking across jobs
3. Community drift metrics
4. Reference quality trends (UNKNOWN % over time)
5. Job-to-job structural complexity comparison

---

## 19. Open Questions

### Decided

| # | Question | Resolution |
|---|----------|------------|
| ~~1~~ | In-process vs child process? | **Child process over stdio** (SDK spec §3). Clean isolation, independent failure domains. |
| ~~2~~ | How to manage daemon lifecycle? | **SDK spawns daemon via `recon up --stdio`** (SDK spec §6.1). CodePlane owns the child process. Stdin close = graceful shutdown. |
| ~~3~~ | How does the agent get CodeRecon tools? | **`sdk.repo(name).as_openai_tools()`** (SDK spec §4.3). Pre-bound to repo + worktree. |
| ~~4~~ | Index storage location? | **`<repo>/.recon/`** — the daemon manages it. CodePlane doesn't control the path. Add `.recon/` to `.gitignore`. |

### Open

| # | Question | Recommendation |
|---|----------|----------------|
| 1 | **Reconcile frequency during execution**: On every `file_changed` event (via watcher), or also explicit calls? | Daemon's `BackgroundIndexer` + `FileWatcher` handles this automatically. CodePlane doesn't need to call `reindex` explicitly during execution. The watcher detects changes and the indexer reconciles on its interval. |
| 2 | **Community naming**: Louvain communities get auto-generated names from the PageRank representative. Good enough? | Start with representative file name. Add LLM-generated names as an enhancement if representatives are unclear (e.g., `__init__.py`). |
| 3 | **Breaking change false positives**: Adding an optional parameter is technically non-breaking in Python but changes the signature hash. | CodeRecon should refine severity classification per language. For now, surface as `body_changed` when the only signature change is adding a parameter with a default value. |
| 4 | **UNKNOWN ref verification**: If the agent edited UNKNOWN ref sites, the warning is noise. | Check if the agent's `file_write` spans include the file:line of UNKNOWN refs. If so, downgrade to "verified by agent edit" with a different visual indicator. |
| 5 | **Index cold start for large repos**: Block job start or allow degraded mode? | Allow degraded mode. Jobs can start immediately. Structural analysis becomes available when indexing completes. Progressive capability unlocking (§6.5). |
| 6 | **Co-existing with other CodeRecon consumers**: If the user also runs `recon up` for their editor MCP integration, do the daemon and SDK conflict? | Per SDK spec §14.1: coexist. Both read the same catalog DB. The stdio daemon and HTTP daemon are independent processes that share data on disk. |
| 7 | **Index size on disk**: How much space does `.recon/` consume? | Typically 1-5% of repo size (SQLite + Tantivy). For a 100MB repo, expect 1-5MB index. Show index size in repo health dashboard. |
| 8 | **Worktree cleanup**: When a job's worktree is deleted, what happens to its index partition? | Daemon evicts idle worktrees automatically (`worktree_idle_timeout_sec`). Rows with deleted worktree_id can be GC'd by the daemon on next reconcile. CodePlane should call unregister or let eviction handle it. |

---

*End of design document.*
