# Review Tab — Fix Plan

Verified against live system (job `fix-code-smells-and-bugs`, localhost:8080) on 2026-05-24.

---

## Bug 1: Motivation Path Mismatch

**Problem:** 2/5 file motivations silently lost. Telemetry spans store `tool_target` as absolute paths in two forms: worktree-rooted (`/.../onboard-wizard/.codeplane-worktrees/fix-code-smells-and-bugs/src/...`) and repo-rooted (`/.../onboard-wizard/package.json`). The normalization at `backend/api/job_artifacts.py:1548` only strips the worktree prefix. Repo-rooted paths leak through as absolute. Frontend does exact key match (`fileMots[filePath]`) against relative diff paths — mismatch.

**Fix:** After the `wt_prefix` strip, add a fallback `repo_prefix` strip. At `backend/api/job_artifacts.py` around line 1537:

```python
# Current (broken):
wt_prefix = ((job.worktree_path or job.repo or "") + "/").replace("//", "/")
# ...
rel_target = target[len(wt_prefix):] if target.startswith(wt_prefix) else target

# Fixed:
wt_prefix = ((job.worktree_path or job.repo or "") + "/").replace("//", "/")
repo_prefix = ((job.repo or "") + "/").replace("//", "/")
# ...
if target.startswith(wt_prefix):
    rel_target = target[len(wt_prefix):]
elif target.startswith(repo_prefix):
    rel_target = target[len(repo_prefix):]
else:
    rel_target = target
```

**Scope:** 5 lines changed in one file.

---

## Bug 2: Trail Enrichment Stuck (Story Never Caches)

**Problem:** 4 trail nodes stuck in `enrichment='pending'` forever. Story service checks `WHERE enrichment = 'pending'` — count > 0 → skips caching → `/story` returns `{"pending": true}` indefinitely.

**Root cause chain (verified):**

1. Trail enricher (`backend/services/trail/enricher.py:94`) calls `self._sidecar_sessions.complete(full_prompt)`.
2. OLD code: `SidecarSessionManager.complete()` checked `self._fast_completer.available`. The `LightweightCompleter` detected no `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` → returned `available=False`.
3. Fell through to pool path → spawned a `SidecarSession` → called `CopilotAdapter.complete()`.
4. `CopilotAdapter.complete()` (`backend/services/copilot_adapter/_adapter.py:638`) spawns a `CopilotClient` subprocess, creates a session, sends prompt, waits for response. On failure catches `(JsonRpcError, ProcessExitedError, ConnectionError, OSError)` → returns empty `CompletionResult()`.
5. The pool path in `SidecarSession.complete()` wraps with `asyncio.wait_for(timeout=30)`. If the subprocess hangs or the SDK emits an unexpected error type (e.g. `RuntimeError` from copilot internals), `TimeoutError` or the uncaught exception propagates.
6. `SidecarSessionManager.complete()` (OLD code) caught `(OSError, RuntimeError)` on the pool path — but NOT `TimeoutError`.
7. Uncaught `TimeoutError` propagated to `drain_enrichment()`.
8. `drain_enrichment()` catches `(SQLAlchemyError, KeyError, ValueError, OSError)` — does NOT catch `TimeoutError` or `RuntimeError`.
9. Exception hits the `drain_loop` safety-net (`except Exception` at line 583) which logs but does NOT mark nodes as failed.
10. Nodes remain `pending` forever.

**Fix (two parts):**

### Part A: Broaden enricher exception handling

At `backend/services/trail/enricher.py:190`:

```python
# Current:
except (SQLAlchemyError, KeyError, ValueError, OSError):

# Fixed:
except Exception:
```

This ensures ANY failure during enrichment marks nodes as `failed` rather than leaving them `pending`. The drain_loop safety-net already exists as a second layer, but it doesn't mark nodes — only this inner handler does.

### Part B: Already fixed by API key cleanup

The `SidecarSessionManager.complete()` was rewritten in this session (already committed). It now routes through pooled `SidecarSession` → `adapter.complete()`. The adapter catches all subprocess errors internally and returns `CompletionResult()`. Timeouts are caught by `SidecarSessionManager.complete()` which returns `""`. Empty string → `parse_enrichment_response("")` → `None` → nodes marked `failed`.

### Part C: Server restart required

The running server (PID 866930, started 17:07) has the old code. A restart will:
- Pick up the new completer code
- `drain_enrichment()` will fetch the 4 `pending` + 10 `failed` nodes (the repo fetches both)
- Retry enrichment through the now-working adapter path
- Either succeed (enrich properly) or fail gracefully (mark `failed`)
- Once `pending` count = 0, story caches on next generation sweep

---

## Bug 3: Coverage Pipeline (No Ingestion Exists)

**Problem:** `coderecon_service.ingest_coverage()` exists but has zero production callers. The "Coverage" toggle does nothing. Green/red gutter dots never appear. Blast radius is always empty.

**Design:**

Two trigger points:

### Trigger A: Turn-completion hook

When a turn completes and contains test execution (detected by the shell classifier marking spans as `verification`), scan the worktree for coverage reports and ingest them.

- Subscribe to the existing turn-completion event in the trail/enricher pipeline
- After a turn with `is_verification_segment=True` spans, look for coverage artifacts:
  - `coverage.json` (coverage.py JSON format)
  - `lcov.info` / `coverage/lcov.info`
  - `coverage.xml` (Cobertura)
- Call `coderecon_service.ingest_coverage(repo, report_path, worktree=branch)`
- This gives incremental coverage updates as the agent works

### Trigger B: Checkpoint tool injection

Inject a `checkpoint` tool into sidecar sessions. When the agent calls `checkpoint`:
1. Run the project's test suite with coverage enabled
2. Collect the coverage report
3. Call `ingest_coverage()` automatically
4. Return a summary to the agent ("Coverage: 73%, 12 uncovered lines in route.ts")

This requires:
- New tool definition in the sidecar tool registry
- Tool handler that: runs tests (using project's test command from config), collects coverage, ingests it
- Agent prompt guidance: "Call `checkpoint` after completing a batch of related changes to validate and record coverage"

### Prerequisites

The agent must produce coverage reports. Options:
- Configure `test_command` in codeplane config to include coverage flags (e.g. `jest --coverage`, `pytest --cov`)
- OR: the checkpoint tool handler adds coverage flags itself when invoking the test command
- The checkpoint tool approach is cleaner — it controls the execution and knows where the report lands

### Files involved

- `backend/services/sidecar/tools/` — new checkpoint tool definition
- `backend/services/trail/enricher.py` — add turn-completion coverage scan
- `backend/services/coderecon/coderecon_service.py` — already has `ingest_coverage()`, no changes
- Agent system prompt — add checkpoint guidance

---

## Bug 4: Diff Payload Bloat (Option C — Lazy Load Large Files)

**Problem:** 292KB diff payload. `package-lock.json` (94KB) + `tsconfig.tsbuildinfo` (80KB) = 60% waste. All hunks shipped upfront.

**Design:** Lazy loading for files exceeding a size threshold.

### Backend changes

1. New field on `DiffFileItem` schema: `truncated: bool` (default False)
2. When computing diff, if a file's hunk content exceeds a threshold (e.g. raw diff bytes > 20KB), set `truncated=True` and omit `hunks` from the response
3. New endpoint: `GET /jobs/{job_id}/diff/{file_path:path}` — returns the full hunks for a single file on demand
4. Threshold derived from: the median file diff size in practice. 20KB is ~2x the 95th percentile of non-lockfile diffs based on observed data. Could also use a heuristic: files matching `*.lock`, `*-lock.json`, `*.tsbuildinfo` are always truncated regardless of size.

### Frontend changes

1. `DiffViewer.tsx` — when rendering a file with `truncated=true`, show a "Load diff" button instead of hunks
2. On click, fetch `/diff/{file_path}` and merge into the store
3. File list sidebar shows these files normally (with an indicator they're collapsed)

### Files involved

- `backend/models/api_schemas.py` — add `truncated` field to `DiffFileItem`
- `backend/services/artifacts/diff_service.py` — add size check + truncation logic
- `backend/api/job_artifacts.py` — new single-file diff endpoint
- `frontend/src/components/DiffViewer.tsx` — lazy load UI
- `frontend/src/api/client.ts` — new `fetchDiffFile()` function

---

## Feature: Impact Graph Batch Endpoint

**Problem:** Frontend calls `/impact-graph/{symbol}` per symbol. 5 symbols = 5 sequential HTTP requests.

**Design:**

### Backend

New endpoint: `POST /jobs/{job_id}/impact-graph-batch`

```
Request body: { "symbols": ["GET", "POST", "createEmployee", ...] }
Response:     { "results": { "GET": { callers: [...], ... }, "POST": { ... } } }
```

Implementation: loop over symbols, call the same CodeRecon method for each, aggregate results. Single HTTP round-trip.

### Frontend

Refactor `useImpactLayers.ts`:
- Collect all symbols visible in the current file's diff
- Single batch fetch instead of N individual fetches
- Cache results in a ref to avoid refetching on scroll

### Files involved

- `backend/api/job_artifacts.py` — new route handler
- `backend/models/api_schemas.py` — request/response schemas
- `frontend/src/hooks/useImpactLayers.ts` — batch fetch logic
- `frontend/src/api/client.ts` — new `fetchImpactGraphBatch()` function

---

## Feature: Nuke Communities Sub-View

**Problem:** Empty, unused tab. User decision to remove.

**Files to modify:**

1. DELETE `frontend/src/components/review/CommunitiesSubView.tsx`
2. `frontend/src/components/review/ReviewSubTabs.tsx` — remove "communities" from `ReviewSubView` type and `TABS` array, remove `showCommunities` prop
3. `frontend/src/components/ReviewDashboard.tsx` — remove import, remove `showCommunities` logic, remove render case
4. `frontend/src/store/index.ts` — remove `setCommunities`, `fetchCommunities`, `communities` state
5. `frontend/src/store/selectors.ts` — remove `selectCommunities`
6. `frontend/src/store/types.ts` — remove `communities` from `AppState`
7. `frontend/src/api/client.ts` — remove `fetchCommunities`, `CommunitiesResponse`, `CommunityGroup`

Backend endpoint stays (no harm, other tools use it).

---

## Execution Order

1. Bug 1 (motivation paths) — immediate, 5 lines
2. Bug 2 (enricher exception) — immediate, 1 line + server restart
3. Nuke communities — quick cleanup, no dependencies
4. Impact graph batch — small, self-contained
5. Diff lazy loading — medium, needs schema change
6. Coverage pipeline — largest, needs design review on checkpoint tool

---

## Prompts for AI Agents

Each prompt below is self-contained. An agent with access to the codebase can execute it without prior context.

---

### Prompt 1: Fix Motivation Path Normalization

```
TASK: Fix a bug where 2/5 file motivations are silently lost in the Review tab.

CONTEXT:
- File: backend/api/job_artifacts.py
- Function: the route handler for GET /jobs/{job_id}/motivations (search for JobMotivationsResponse)
- The handler computes `wt_prefix` from job.worktree_path and strips it from tool_target paths
- Problem: telemetry spans created BEFORE the worktree existed store tool_target as repo-absolute paths (e.g. /home/user/repos/myapp/package.json) which don't start with wt_prefix
- The frontend does exact key match between motivation keys and diff file paths (which are relative like "package.json")

FIX:
1. After computing wt_prefix, also compute repo_prefix: `repo_prefix = ((job.repo or "") + "/").replace("//", "/")`
2. Change the normalization from a single ternary to a cascade:
   - If target starts with wt_prefix → strip wt_prefix
   - Elif target starts with repo_prefix → strip repo_prefix  
   - Else → use target as-is

VERIFICATION:
- Run: uv run pytest backend/tests/unit/ -k "motivation" -x
- If no specific test exists, verify with: curl http://localhost:8080/api/jobs/fix-code-smells-and-bugs/motivations | python3 -c "import json,sys; d=json.load(sys.stdin); [print(k) for k in d['fileMotivations']]"
- All keys should be relative paths (no /home/... prefixes)

DO NOT modify any other files. DO NOT add tests unless the existing test already covers this path.
```

---

### Prompt 2: Fix Trail Enrichment Exception Handling

```
TASK: Fix stuck trail enrichment nodes that block story generation forever.

CONTEXT:
- File: backend/services/trail/enricher.py
- Method: drain_enrichment() (around line 68)
- The method processes pending trail nodes by calling self._sidecar_sessions.complete() for LLM enrichment
- There is a try/except block (around line 190) that catches (SQLAlchemyError, KeyError, ValueError, OSError) and marks nodes as "failed"
- Problem: if the sidecar completion raises TimeoutError, RuntimeError, or any other exception NOT in that tuple, the exception propagates to the outer drain_loop safety-net which logs but does NOT mark nodes as failed
- Result: nodes stay "pending" forever, story service sees pending_enrichment > 0, never caches

FIX:
1. Change the except clause at ~line 190 from:
   `except (SQLAlchemyError, KeyError, ValueError, OSError):`
   to:
   `except Exception:`
2. The existing behavior inside the handler (log + mark nodes failed) is correct — just needs to catch all exceptions

VERIFICATION:
- Run: uv run pytest backend/tests/unit/ -k "enricher" -x
- Verify the drain_loop (around line 560) still has its own `except Exception` safety-net — that's the last-resort crash prevention for the background loop itself
- The two layers serve different purposes: inner (this fix) marks nodes failed; outer prevents the loop from dying

ALSO: After this fix is deployed, the server must be restarted. The 4 stuck "pending" nodes will be picked up by drain_enrichment on the next sweep (it fetches both "pending" and "failed" nodes for retry).

DO NOT modify SidecarSessionManager or any completer code — those were already fixed in a prior session.
```

---

### Prompt 3: Coverage Ingestion Pipeline

```
TASK: Implement a coverage ingestion pipeline so the Review tab's Coverage toggle actually shows data.

CONTEXT:
- coderecon_service.ingest_coverage() exists at backend/services/coderecon/coderecon_service.py:522
- It accepts (repo, report_path, worktree, test_id, failed_tests, rebuild_reachability)
- It delegates to ReviewKit.ingest_coverage() which parses coverage.py JSON and lcov formats
- Currently ZERO production code calls it — only a test file
- The frontend already has useCoverageLayers.ts that renders green/red gutter dots IF the API returns data
- The API endpoint for line-coverage already exists and works — it just returns empty arrays because nothing was ingested

DESIGN — Two trigger mechanisms:

TRIGGER A — Turn-completion scan:
1. In backend/services/trail/enricher.py, after drain_enrichment processes a batch, check if any of the processed nodes were shell/verification nodes
2. If yes, scan the job's worktree for coverage report files:
   - {worktree}/coverage.json
   - {worktree}/coverage/lcov.info  
   - {worktree}/lcov.info
   - {worktree}/coverage.xml
3. If found, call coderecon_service.ingest_coverage(repo=job.repo, report_path=found_path, worktree=branch_name)
4. This runs asynchronously in the drain loop — no latency impact on the agent

TRIGGER B — Checkpoint tool:
1. Create a new tool in backend/services/sidecar/tools/ called "checkpoint"
2. When invoked by the agent:
   a. Determine the project's test command (from job config or detect from package.json/pyproject.toml)
   b. Append coverage flags (--coverage for jest, --cov --cov-report=json for pytest)
   c. Run the test command in the worktree
   d. Find the coverage report in the output
   e. Call coderecon_service.ingest_coverage()
   f. Return a summary to the agent: pass/fail count, coverage percentage, uncovered lines in changed files
3. Register this tool in the sidecar tool registry so it's available in sessions
4. Add to the agent system prompt: "Call checkpoint after completing a logical batch of changes to validate correctness and record test coverage."

IMPLEMENTATION ORDER:
- Start with Trigger A (simpler, immediate value)
- Then implement Trigger B (requires tool registration, test runner detection, more complex)

FILES TO CREATE/MODIFY:
- backend/services/trail/enricher.py — add coverage scan after verification turns
- backend/services/sidecar/tools/checkpoint.py — new file for checkpoint tool
- backend/services/sidecar/tools/__init__.py — register checkpoint
- backend/config.py — add test_command config field if not present
- Integration test to verify ingestion triggers correctly

CONSTRAINTS:
- Use uv for all Python operations
- Do NOT hardcode coverage report paths — scan for common locations
- The test command detection should check: package.json scripts.test, pyproject.toml [tool.pytest], Makefile test target
- Coverage threshold for "large enough to ingest" = at least 1 file covered (don't ingest empty reports)
```

---

### Prompt 4: Diff Lazy Loading for Large Files

```
TASK: Implement lazy loading for large diff files to reduce the initial payload from 292KB to ~120KB.

CONTEXT:
- Endpoint: GET /jobs/{job_id}/diff returns ALL file diffs including hunks
- package-lock.json (94KB of hunks) and tsconfig.tsbuildinfo (80KB) dominate the payload
- The diff service is at backend/services/artifacts/diff_service.py
- The API schema for diff items is in backend/models/api_schemas.py (search for DiffFileItem or similar)
- Frontend renders diffs in frontend/src/components/DiffViewer.tsx

DESIGN:
1. Add a `truncated: bool = False` field to the diff file response schema
2. In the diff computation, after generating hunks for each file:
   - Calculate total hunk content size (sum of line text lengths)
   - If size > 20KB OR file matches a binary/generated pattern (*.lock, *-lock.json, *.tsbuildinfo, *.min.js, *.min.css):
     - Set truncated=True
     - Replace hunks with an empty array
     - Include a `rawSize: int` field so the UI can show "Load 94KB diff"
3. New endpoint: GET /jobs/{job_id}/diff-file?path={relative_path}
   - Returns the full DiffFileItem (with hunks) for a single file
   - Uses the same diff computation logic but for one file only
4. Frontend changes:
   - In DiffViewer.tsx, when rendering a file with truncated=true, show a button: "Load diff ({rawSize} KB)"
   - On click, call the new endpoint and merge the result into the file list
   - File sidebar shows truncated files with a collapse icon

THRESHOLD JUSTIFICATION:
- 20KB chosen because: observed non-lockfile diffs are all under 10KB for this project
- The pattern list catches the common offenders regardless of size

FILES TO MODIFY:
- backend/models/api_schemas.py — add truncated + rawSize fields
- backend/services/artifacts/diff_service.py — add size check and truncation
- backend/api/job_artifacts.py — new single-file endpoint
- frontend/src/api/client.ts — new fetchDiffFile() function  
- frontend/src/components/DiffViewer.tsx — lazy load UI for truncated files

CONSTRAINTS:
- Do NOT remove large files from the diff entirely — they must still appear in the file list
- The truncation threshold must be a named constant, not a magic number
- Backend schema uses CamelModel (camelCase serialization)
```

---

### Prompt 5: Impact Graph Batch Endpoint

```
TASK: Add a batch endpoint for impact graph queries to eliminate N+1 HTTP requests.

CONTEXT:
- Current: frontend/src/hooks/useImpactLayers.ts calls GET /jobs/{job_id}/impact-graph/{symbol} once per symbol
- For a file with 5 exported symbols, this means 5 sequential HTTP requests (13-28ms each)
- The backend handler is in backend/api/job_artifacts.py (search for "impact-graph" or "impact_graph")
- It delegates to coderecon_service which calls ReviewKit

IMPLEMENTATION:

Backend:
1. New endpoint: POST /jobs/{job_id}/impact-graph-batch
2. Request schema: ImpactGraphBatchRequest with field `symbols: list[str]`
3. Response schema: ImpactGraphBatchResponse with field `results: dict[str, ImpactGraphResponse]`
   - Where ImpactGraphResponse is the existing response type for the single-symbol endpoint
4. Implementation: loop over symbols, call the same coderecon method for each, collect into dict
5. Add to the router in the same file as the existing impact-graph endpoint

Frontend:
1. In frontend/src/api/client.ts — add fetchImpactGraphBatch(jobId, symbols[]) function
2. In frontend/src/hooks/useImpactLayers.ts:
   - Collect all symbols that need impact data for the current file
   - Make a single batch call instead of N individual calls
   - Cache results in a useRef to avoid refetching on re-render
   - Invalidate cache when the file changes

FILES TO MODIFY:
- backend/api/job_artifacts.py — new route handler
- backend/models/api_schemas.py — ImpactGraphBatchRequest, ImpactGraphBatchResponse schemas
- frontend/src/api/client.ts — fetchImpactGraphBatch
- frontend/src/hooks/useImpactLayers.ts — refactor to batch

CONSTRAINTS:
- Keep the existing single-symbol endpoint working (don't break it)
- Request body uses CamelModel conventions
- Frontend should gracefully handle partial failures (if one symbol fails, still render the rest)
- Maximum batch size: no limit needed (typically 3-10 symbols per file)
```

---

### Prompt 6: Nuke Communities Sub-View

```
TASK: Remove the Communities sub-tab from the Review dashboard. It shows no useful data and is being removed.

CONTEXT:
- The "Communities" tab appears in the Review view's sub-tab bar
- It renders CommunitiesSubView.tsx which calls a CodeRecon communities endpoint
- The endpoint works but the data is not useful for code review
- Backend endpoint should NOT be removed (other tools may use it)

FILES TO MODIFY (in order):

1. DELETE: frontend/src/components/review/CommunitiesSubView.tsx

2. frontend/src/components/review/ReviewSubTabs.tsx:
   - Remove "communities" from the ReviewSubView type union
   - Remove the communities entry from the TABS array
   - Remove the showCommunities prop and its filter logic

3. frontend/src/components/ReviewDashboard.tsx:
   - Remove the CommunitiesSubView import
   - Remove any showCommunities state/logic
   - Remove the communities case from the sub-view render switch

4. frontend/src/store/index.ts:
   - Remove communities state field
   - Remove setCommunities action
   - Remove fetchCommunities thunk/call

5. frontend/src/store/selectors.ts:
   - Remove selectCommunities selector (if it exists)

6. frontend/src/store/types.ts:
   - Remove communities field from AppState interface (if defined here)

7. frontend/src/api/client.ts:
   - Remove fetchCommunities function
   - Remove CommunitiesResponse type
   - Remove CommunityGroup type (if only used by communities)

VERIFICATION:
- Run: cd frontend && npx tsc --noEmit (should compile cleanly)
- Run: cd frontend && npx eslint src/ --quiet (no errors about missing imports)
- Visual: load http://localhost:5173, navigate to a job in review state, confirm the tab bar no longer shows "Communities"

CONSTRAINTS:
- Do NOT remove the backend endpoint (/communities)
- Do NOT modify any backend code
- If any type is shared with other features, only remove the communities-specific usage
- Use the Network icon import from lucide-react may become unused — remove it if so
```
