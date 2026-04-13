---
name: infrastructure-red-team
description: >
  Deep red-team audit of CodePlane's 8 infrastructure subsystems: git/merge,
  permission evaluation, MCP server, share/preview, retry tracker,
  progress/step tracking, config system, and database layer. Finds race
  conditions, resource leaks, data corruption, missing validation, and security
  issues. Produces fixes with tests.
---

# Infrastructure Red-Team Skill

Systematically red-team 8 infrastructure subsystems. For each: read code → find
bugs → fix → verify. Track all findings in session memory.

## Subsystems & Key Files

### 1. Git / Merge Service
| File | Lines | Role |
|------|-------|------|
| `backend/services/git_service.py` | ~595 | `GitService` — worktree lifecycle, git ops |
| `backend/services/merge_service.py` | ~617 | `MergeService` — 3-strategy merge escalation |

**Attack surface:**
- Worktree cleanup: `remove_worktree()` partial failure leaves stale dirs
- `_run_git()` timeout: long-running git ops (large repos) may hang
- Concurrent worktree operations on same repo: race in prune→force-remove→create
- `_try_ff_via_ref()` ref update race: two merges to same branch
- `_merge_in_worktree()` leftover worktree on exception
- Branch deletion after merge: what if branch is checked out elsewhere?
- `cleanup_worktrees()` on startup: can it delete an active worktree?
- `_repo_locks` dict grows unbounded with unique repo paths

### 2. Permission Evaluation
| File | Lines | Role |
|------|-------|------|
| `backend/services/base_adapter.py` | ~800 | `_evaluate_permission()` — central permission gate |
| `backend/services/permission_policy.py` | — | Policy rules per mode |
| `backend/services/approval_service.py` | ~200 | Approval lifecycle |

**Attack surface:**
- `_evaluate_permission()` bypass via `trust_job()` — does trust persist across pause/resume?
- `git reset --hard` detection: pattern matching on tool args — evasion possible?
- `observe_only` mode: can agent bypass by using shell commands instead of tools?
- Race: trust granted while approval pending — double-action?
- `_explicit_approval_ids` set growth: never cleaned for long-running jobs
- Policy evaluation exception: does it fail-open or fail-closed?

### 3. MCP Server
| File | Lines | Role |
|------|-------|------|
| `backend/mcp/server.py` | ~800 | 7 tool handlers, input validation, error handling |

**Attack surface:**
- Module-level service captures: stale references if services recreated
- `codeplane_workspace` path traversal: symlink bypass of `is_relative_to()`
- File read (5 MB limit): memory spike with many concurrent requests
- No rate limiting on MCP tool calls
- `codeplane_job` create action: missing input sanitization on prompt field
- Error responses leak internal exception messages
- No auth — relies on "local trusted machine" assumption

### 4. Share / Preview System
| File | Lines | Role |
|------|-------|------|
| `backend/api/share.py` | ~580 | Share endpoints + SSE for shared jobs |
| `backend/api/preview.py` | ~65 | Reverse proxy to local dev servers |
| `backend/services/share_service.py` | ~65 | Token generation/validation |

**Attack surface:**
- `_tokens` dict grows unbounded: no cleanup of expired tokens
- Token brute-force: no rate limiting on `/share/{token}/job`
- Preview proxy: SSRF via port parameter (localhost-only but still risky)
- Preview proxy: response header injection from upstream
- Share SSE: no connection limit per token
- `asyncio.gather()` in snapshot: one slow query stalls entire response
- Expired token race: validate→use with deletion in between

### 5. Retry Tracker
| File | Lines | Role |
|------|-------|------|
| `backend/services/retry_tracker.py` | ~70 | Track tool retries per job |

**Attack surface:**
- `_history` dict grows unbounded per job (thousands of tool calls)
- No cap on `(tool_name, tool_target)` keys
- `reversed()` linear scan on every record: O(n²) over job lifetime
- Cleanup: relies on external caller — what if pop() never called?

### 6. Progress / Step Tracking
| File | Lines | Role |
|------|-------|------|
| `backend/services/progress_tracking_service.py` | ~1100 | Plan inference, step-to-plan assignment |
| `backend/services/step_tracker.py` | ~280 | Step boundary detection, file tracking |
| `backend/services/step_persistence.py` | ~50 | DB persistence subscriber |

**Attack surface:**
- `_try_early_plan()` + `_infer_plan()`: concurrent calls for same job
- Step boundary on turn_id change: missing events cause phantom steps
- `auto_commit()` on step close: git error leaves step without end_sha
- `_plan_inference_lock` per-job: dict grows unbounded
- Sister session LLM call failure: plan never inferred, stuck in "pending"
- `files_written` list unbounded: agent touching thousands of files

### 7. Config System
| File | Lines | Role |
|------|-------|------|
| `backend/config.py` | ~500 | YAML config, env vars, per-repo overrides |

**Attack surface:**
- `register_repo()` TOCTOU: read-modify-write not atomic
- `.codeplane.yml` symlink: can point to arbitrary file on disk
- `discover_mcp_servers()`: env vars in MCP config → command injection
- Config reload: no validation of changed values → invalid state
- `_update_repos_in_file()` partial write on disk full

### 8. Database Layer
| File | Lines | Role |
|------|-------|------|
| `backend/persistence/database.py` | ~60 | Engine, pragmas, session factory |
| `backend/persistence/repository.py` | ~20 | Base repository class |
| 12 repo files | ~600 | Domain-specific queries |

**Attack surface:**
- `pool_size=10 + max_overflow=20`: 30 connections to SQLite — WAL writer contention
- Migration recovery: stamps to head silently — may skip data migrations
- `get_session()` commit-on-success: long-lived sessions hold WAL locks
- No connection health checks: stale connections after disk errors
- `busy_timeout=5000`: 5s may be insufficient under heavy write load
- No query timeout: runaway queries block the event loop

## Workflow

1. **Gather context** — Read all files listed above, trace hot paths
2. **For each subsystem** — identify bugs, rank by severity
3. **Fix** — implement minimal targeted fixes
4. **Verify** — run `uv run pytest backend/tests/ -x -q` (deselect flaky test)
5. **Commit** — `git add -A && git commit -m "fix: infrastructure red-team — <subsystem>"`
6. **Deploy** — `NODE_OPTIONS="--max-old-space-size=3072" python tools/dev_restart.py`

## Severity Scale

| Level | Meaning | Action |
|-------|---------|--------|
| P0 | Data corruption / security hole | Fix immediately |
| P1 | Resource leak / crash under load | Fix in this pass |
| P2 | Degraded behavior, workaround exists | Fix if time allows |
| P3 | Code smell / minor inefficiency | Document only |
