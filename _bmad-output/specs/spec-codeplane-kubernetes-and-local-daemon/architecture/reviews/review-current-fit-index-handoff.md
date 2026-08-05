---
review-type: current-fit-and-brownfield-grounding
subject: ARCHITECTURE-SPINE.md — AD-36 and AD-37 with technology-claim audit
reviewed-at: '2026-08-05'
scope:
  - AD-36 (repository-index ownership)
  - AD-37 (handoff ownership)
  - Named technology version claims
sources-inspected:
  - backend/services/coderecon/coderecon_service.py
  - backend/services/runtime/handoff.py
  - backend/models/events.py
  - pyproject.toml
  - frontend/package.json
verdict: CONDITIONAL PASS — AD-36 is well-grounded with two gap annotations needed; AD-37 is substantially aspirational relative to current code; one technology claim is ungrounded and should be corrected
---

# Current-Fit and Brownfield Grounding Review
## ARCHITECTURE-SPINE.md — AD-36, AD-37, and Technology Claims

---

## Executive Verdict

| Decision | Grounding score | Status |
|---|---|---|
| AD-36 — Repository-index ownership | ~80 % | MOSTLY GROUNDED — two unacknowledged gaps |
| AD-37 — Handoff ownership | ~35 % | ASPIRATIONAL — current code implements a small subset; forward-looking portions are valid but unmarked |
| Technology claims | See §4 | One ungrounded claim (FastAPI locked version); all others confirmed |

Neither AD misrepresents the target Kubernetes architecture. The concern is that both partially overstate the present local-adapter implementation without flagging forward-looking sections as such.

---

## 1. AD-36 — Repository-Index Ownership

### 1.1 Method-name grounding (PASS)

All six local-adapter operations named in AD-36 are present in `coderecon_service.py`:

| Spine name | Implementation status |
|---|---|
| `ensure_repo_indexed` | Implemented — lines 118–171 |
| `register_worktree` | Implemented — lines 219–246 |
| `reindex` | Implemented — lines 341–356 |
| `sync_from_git` | Implemented — lines 409–419 |
| `merge_index` | Implemented — lines 421–431 |
| `drop_worktree` | Implemented — lines 433–442 |

### 1.2 Event-kind grounding (PASS)

`repo_index_progress` and `repo_index_complete` are defined in `events.py` (`EventKind.repo_index_progress`, `EventKind.repo_index_complete`) and are emitted by `CodeReconService._emit_index_progress` and `_emit_index_complete` respectively. The SSE path is correctly described.

### 1.3 Local adapter architecture (PASS)

Spine correctly characterises the local adapter as in-process with a `ThreadPoolExecutor` (not a daemon or network service). The `_kits` dictionary (keyed by resolved repo path), per-path `asyncio.Lock`, and `Thread-offload` pattern match the code exactly. No PostgreSQL or S3 is introduced.

### 1.4 GAP — Generation identity includes feature config and schema version; local key does not

**AD-36 claims:** "A generation identity binds tenant, canonical repository identity, immutable source commit/tree, worktree or overlay identity, **CodeRecon/index schema version, feature configuration**, and model/tool digest."

**Actual code:** The `_kits` dictionary is keyed solely by `resolved` repo path. Two concurrent jobs with different feature configurations (e.g., `CODERECON__FEATURES__SPLADE=true` vs `false`) would share the same `ReviewKit` instance because `resolved` is the same path. There is no schema-version or feature-flag component in the local index key.

**Impact:** The "exact identity reuse" claim in AC-19 ("commit/tree, overlay, schema, feature, or model/tool digest changes invalidate reuse") is not enforced in the local adapter. For local mode this may be an acceptable simplification (single-user, single config), but the spine should note it as an intentional difference under AD-25 or an open gap, not a shared invariant.

**Recommended annotation:** Add a note under AD-36 or in the Local-Only/Kubernetes-Analogue table: "Local-daemon uses a single per-repository `ReviewKit` keyed by resolved path; feature-configuration and schema-version isolation is a Kubernetes-only generation property."

### 1.5 GAP — Shared in-process index is not isolated between concurrent jobs

**AD-36 claims:** "Agent Pods query through an authenticated tenant CodeRecon/index service … and **never mutate shared bytes**."

**Actual code:** `CodeReconService._kits` is a shared in-process dict. Both `reindex` and `sync_from_git` call `kit.reindex(...)` / `kit.sync_from_git(...)` with no per-job locking beyond `_index_locks` (which are held only during the initial `ensure_repo_indexed`). Two concurrent local jobs on the same repository can both call `reindex` concurrently, mutating the shared `ReviewKit` state.

**Impact:** The "never mutate shared bytes" guarantee is Kubernetes-specific (agent Pods access a read-only index service). The local adapter has no equivalent fence. This is not the same failure mode as Kubernetes (there are no separate Pods), but the spine's phrasing reads as a universal invariant. It should be scoped explicitly to Kubernetes mode.

**Recommended annotation:** Scope "never mutate shared bytes" to the Kubernetes adapter description. Add an explicit intentional-difference entry noting that local mode shares an in-process mutable index and that concurrent mutation isolation is the operator's responsibility (single-user workstation assumption).

### 1.6 Module-docstring contradiction (NOT an architecture gap — code quality note)

`coderecon_service.py` module docstring (line 11): "If the import fails, `start()` raises immediately — silent degradation is a bug." But `start()` (lines 89–100) catches `ImportError`/`ModuleNotFoundError`, logs a warning, sets `_available = False`, and returns — it does not raise. The docstring is wrong. This is a code defect, not an architecture defect, but the spine's claim that the service is "always enabled" is not strictly accurate given this path.

---

## 2. AD-37 — Handoff Ownership

### 2.1 `context.handoff` event kind (PASS)

`EventKind.context_handoff = "context.handoff"` is defined in `events.py` (line 138). The spine's Consistency Conventions table correctly references this kind. ✓

### 2.2 Local job-level handoff (PARTIAL — implementation is much simpler than described)

**AD-37 describes:** Immutable versioned artifact packages containing summary, changed-file set, plan and curated-context references, source job/session/attempt, repository/ref/tree identity, **content hash, provenance, intended consumer, and compatibility version**. Selection logic: "selects an explicitly requested package or, absent that, the newest compatible committed package for the same lineage and intended consumer using stable creation sequence then package ID, validates hash, provenance, repository/tree and compatibility."

**Actual `handoff.py`:** The module implements `load_handoff_context_for_job` and two prompt-building helpers. It:
- Reads the latest session summary artifact via `ArtifactService.get_latest_session_summary(job.id)` — no selection by lineage, intended consumer, or compatibility version.
- Falls back to summarising the session log artifact or calling `summarization_service.summarize_and_store`.
- Returns `(summary_text, changed_files)` — two fields, not an immutable package structure.
- Does **not** validate content hash, provenance, repository/tree identity, or compatibility version.
- Does **not** emit a `context.handoff` event at any point despite the event kind existing.
- Has no concept of "committed" vs "staged" packages, no conflict detection, no `Conflict` condition.

**Assessment:** `handoff.py` is the current-state local implementation of job resume context assembly. It covers roughly the "summary text + changed files" subset of what AD-37 describes. The full immutable-package model, hash validation, lineage selection, compatibility versioning, and conflict-preservation rules are forward-looking Kubernetes design that has not yet been ported back to the local adapter either.

**Gap severity:** HIGH — the gap is large enough to mislead implementers who read AD-37 as describing existing behavior. The spine should tag at least the selection/validation/conflict portions of AD-37 with `[FORWARD-LOOKING]` or reference the AD-26 delivery phase in which they become required.

### 2.3 `context.handoff` event not connected to handoff workflow (GAP)

`EventKind.context_handoff` exists in `events.py` but `handoff.py` never emits it. The Consistency Conventions table says "`context.handoff` references an immutable AD-37 package" — this is a forward design contract, not current behavior. Neither the event emission nor the package reference are implemented. This should be called out as a Phase 1/2 gap (AD-26).

### 2.4 Git common-directory `session-handoff/` protocol (NOT IN `handoff.py` — correctly separated in spine)

**What the spine says:** AD-37 correctly separates "Job/session handoff packages" (`ArtifactStoragePort`) from "Repository-scoped `session-handoff/` protocol files" (`RepositoryContextPort`), with the local adapter using "the actual Git common-directory `session-handoff/` tree."

**What `handoff.py` does:** It reads `ArtifactService` / `ArtifactRepository` (the `~/.codeplane` filesystem artifacts path). It does **not** read or write the Git common-directory `session-handoff/` tree at all. That tree is handled by a separate code path (not in this file).

**Assessment:** The spine's architectural separation is correct and sound. `handoff.py` implements only the artifact/summarization side. The Git-common-directory protocol side is a separate module. No spine correction needed here, but implementers should be aware that the local `RepositoryContextPort` is not yet visible in `handoff.py`.

### 2.5 No PostgreSQL or S3 introduced (PASS)

`handoff.py` reads from SQLAlchemy sessions and local `disk_path` filesystem. No external storage service is introduced. ✓

### 2.6 Kubernetes `CodePlaneSessionHandoff` CRD (PASS — forward-looking, correctly framed)

The CRD table entry for `CodePlaneSessionHandoff` is clearly part of the Kubernetes adapter design. Conditions (`Staged`, `Ready`, `Selected`, `Incompatible`, `Missing`, `Conflict`) are consistent with AD-37's rules and do not conflict with the current local implementation. The spine never claims the CRD exists today. ✓

---

## 3. Cross-Cutting Architecture Observations

### 3.1 AD-26 phase tagging (recommendation)

AD-36's Kubernetes sections (dedicated indexer workload, `CodePlaneRepositoryIndex` CRD, authenticated tenant CodeRecon service, `RepositoryIndexStoragePort` port) are Phase 3–4 deliverables under AD-26. AD-37's full immutable-package model is also Phase 2–4. Neither AD carries `[PHASE N]` or `[FORWARD-LOOKING]` tags on the Kubernetes-specific portions.

**Recommendation:** Tag the Kubernetes-specific sub-clauses of AD-36 and AD-37 with their AD-26 delivery phase to prevent readers from testing Phase-4 behavior against a Phase-1 codebase.

### 3.2 Local `CodeReconService` degraded-availability path

The spine (AD-36) says "Missing, stale, incompatible, or corrupt generations are never silently used." In the local adapter, when `ensure_repo_indexed` throws (non-import failure path, lines 153–157), the exception propagates to the caller, which is correct. However, the `_available = False` path in `start()` (import failure) results in all operations raising `CodeReconUnavailableError`, which callers must handle. This is consistent with the spine's "Missing … are never silently used" rule only if callers correctly surface the error rather than swallowing it. The spine should note that error surface policy in local callers is an AC-19 conformance obligation.

---

## 4. Named Technology Claim Audit

| Claim in spine | Verified against | Finding |
|---|---|---|
| Python 3.12.x | `pyproject.toml: requires-python = ">=3.12"` | GROUNDED — range ≥3.12 is consistent; "3.12.x" implies patch-lock not present in pyproject but not a false claim |
| FastAPI `0.136.3 locked baseline; supported range >=0.115,<1` | `pyproject.toml: "fastapi>=0.115,<1"` | **UNGROUNDED** — `0.136.3` locked baseline is stated as fact but there is no such lock in pyproject.toml; uv.lock was not inspectable at review time. The range `>=0.115,<1` is correct. The specific `0.136.3` version should be qualified as "current resolved version at authoring" rather than a standing locked baseline, or confirmed from `uv.lock`. |
| SQLAlchemy 2.x | `pyproject.toml: "sqlalchemy>=2.0,<3"` | GROUNDED ✓ |
| Pydantic 2.x | `pyproject.toml: "pydantic>=2.0,<3"` | GROUNDED ✓ |
| TraceForge toolkit 0.1.x | `pyproject.toml: "traceforge-toolkit>=0.1.5,<0.2"` | GROUNDED ✓ |
| React 18.3.x | `frontend/package.json: "react": "^18.3.1"` | GROUNDED ✓ |
| Zustand 5.x | `frontend/package.json: "zustand": "^5.0.3"` | GROUNDED ✓ |
| Kubernetes 1.34–1.36 | No cluster to inspect; stated as "three maintained minors at authoring" | PLAUSIBLE — consistent with public Kubernetes release cadence at the stated authoring date; marked as an assumption which is correct posture |
| Helm CLI 3.21.x and 4.2.x | Not verifiable locally; no lock file | NOT VERIFIABLE — no install or lock file available; should be confirmed at qualification |
| CSI PVC / VolumeSnapshot v1 | No cluster to inspect | NOT VERIFIABLE — correctly deferred to operator environment; posture is sound |
| `@tanstack/react-virtual` | `frontend/package.json: "^3.13.23"` | GROUNDED (matches AD-27 convention) ✓ |

---

## 5. Conformance with Bounded-CRD / PVC / No-PostgreSQL-S3 Requirements

| Requirement | Finding |
|---|---|
| CRDs bounded (≤256 KiB, metadata/hash/reference only, no large payloads in etcd) | Confirmed — AD-10 and CRD table both constrain index CRDs to "bounded metadata/status"; bytes go to PVC through tenant gateway. ✓ |
| PVC-backed index storage (not PostgreSQL/S3) | Confirmed — `RepositoryIndexStoragePort` uses "tenant gateway/PVC index generations" with qualified RWOP-capable StorageClass/CSI driver; no named object store. AD-21 "no external state service" is explicit. ✓ |
| No PostgreSQL or S3 introduced in local path | `coderecon_service.py` uses in-process ThreadPoolExecutor only; `handoff.py` uses SQLAlchemy/SQLite and local filesystem. ✓ |
| Session-handoff Git common-directory protocol | Spine correctly maps local mode to actual Git common-directory `session-handoff/` tree and Kubernetes mode to `RepositoryContextPort` PVC generations. Neither path introduces external databases. ✓ |

---

## 6. Required Changes to Spine

The review is advisory (spine is not to be edited during this review). Findings to address in a future spine revision:

| # | Finding | Severity | Suggested action |
|---|---|---|---|
| R-1 | AD-36: Generation identity (schema version, feature config) is a Kubernetes-only property; local adapter uses path-only key | MEDIUM | Add intentional-difference note scoping generation identity to Kubernetes; note local simplification explicitly |
| R-2 | AD-36: "never mutate shared bytes" is a Kubernetes-only guarantee; local in-process shared `_kits` has no per-job mutation fence | MEDIUM | Scope claim to Kubernetes mode; add local boundary note under AD-25 |
| R-3 | AD-37: Full immutable-package model, hash validation, lineage selection, compatibility versioning, and conflict-preservation are forward-looking; current `handoff.py` implements summary+changed-files subset only | HIGH | Tag Kubernetes-facing and package-formalism sub-clauses with AD-26 delivery phase; add `[FORWARD-LOOKING: Phase 2–4]` markers |
| R-4 | AD-37: `context.handoff` event is defined but not emitted by current handoff workflow | MEDIUM | Note as Phase 2 gap; add "[not yet emitted in local adapter]" annotation |
| R-5 | Stack table: FastAPI `0.136.3 locked baseline` is ungrounded; only a range is present in pyproject.toml | LOW | Replace with "range `>=0.115,<1`; resolved version at authoring: `<confirm from uv.lock>`" |

---

## 7. What is Correct and Should Not Change

- The ports-and-adapters paradigm and the clean separation between local and Kubernetes compositions are well-grounded in the codebase.
- The six method names in AD-36 are all implemented and correctly described.
- `EventKind.repo_index_progress`, `repo_index_complete`, and `context.handoff` are all present in `events.py`.
- AD-37's architectural separation of job-level artifact packages from `RepositoryContextPort` Git-common-directory protocol is sound and correctly maps to the codebase structure.
- No PostgreSQL, S3, or external object-store dependency has been introduced anywhere in the reviewed code.
- The CRD table, PVC storage model, and bounded-metadata-only-in-etcd invariants are internally consistent and do not conflict with the Kubernetes-native CSI/PVC-backed storage approach.
- TraceForge, SQLAlchemy, Pydantic, React, and Zustand version claims are all confirmed against project manifests.
