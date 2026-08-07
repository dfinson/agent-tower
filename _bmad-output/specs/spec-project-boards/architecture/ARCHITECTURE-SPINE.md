---
name: 'project-boards'
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: 'layered (route-scoped feature slice inside an existing thin-route/service/repository backend and Zustand-store frontend)'
scope: 'Repo/Project-scoped Kanban board (CAP-1) and cross-project overview with attention rollup, filter, Project registry, external-tracker sync, Task Recipe chaining/ingestion, and a persistent Chat that can launch Jobs and/or gate a recipe chain (CAP-2/CAP-3/CAP-4/CAP-5/CAP-6/CAP-7/CAP-8/CAP-9/CAP-10/CAP-11/CAP-12) for CodePlane'
status: final
created: '2026-08-06'
updated: '2026-08-07'
binds: ["CAP-1", "CAP-2", "CAP-3", "CAP-4", "CAP-5", "CAP-6", "CAP-7", "CAP-8", "CAP-9", "CAP-10", "CAP-11", "CAP-12"]
sources: ["_bmad-output/specs/spec-project-boards/SPEC.md"]
companions: []
---

# Architecture Spine — project-boards

## Design Paradigm

Route-scoped feature slice inside CodePlane's existing layering: FastAPI routes stay thin and delegate to services/repositories (backend), React components read the Zustand store via named selectors (frontend). This feature adds no new paradigm — it extends the existing `/repos/:repoPath/*` per-repo shell (`RepoLayout` + child routes) and the existing settings-repo service path, rather than introducing a parallel navigation or state model.

## Invariants & Rules

### AD-1 — One shared job-status classifier, two call sites

- **Binds:** CAP-1, CAP-2, CAP-3
- **Prevents:** The frontend board and the backend-computed overview counts disagreeing on what counts as "awaiting input" vs "failed" vs "in progress".
- **Rule:** Status bucketing (in-progress / awaiting-input / failed) is defined once per layer and reused, never re-implemented at the call site: frontend reuses `selectActiveJobs` / `selectSignoffJobs` / `selectAttentionJobs` (`store/selectors.ts`) for both `KanbanBoard` and any board filtered by repo; backend reuses the same job-count query path `get_repo_summary` (`backend/api/settings.py`) already uses, extended in place rather than duplicated into a new query.

### AD-2 — Repo scoping travels via the URL route param, never a parallel selection scheme

- **Binds:** CAP-1
- **Prevents:** Two competing patterns for "which repo am I looking at" (a URL param here, a query string or client-only state there) inside the same app.
- **Rule:** The repo-scoped board is a child route of the existing `/repos/:repoPath` shell (e.g. `/repos/:repoPath/board`), reading `repoPath` via `useParams`, exactly like `RepoJobs`/`RepoHealth`/`RepoCost` already do. No new top-level route owns repo selection.

### AD-3 — Overview data is one batch call, never N per-repo calls

- **Binds:** CAP-2, CAP-3
- **Prevents:** An overview screen that fires one HTTP request per Project on load (N+1, scales badly past a handful of Projects).
- **Rule:** Add `GET /settings/projects/summary` (plural, batch) returning an array of the same per-Project shape `GET /settings/projects/{id}/summary` returns, extended with status-bucket counts (AD-4). The prior repo-scoped `GET /settings/repos/{repo}/summary` is retired along with standalone repo registration (AD-5); Project is the only summary unit now.

### AD-4 — One generated type for repo summary counts, no hand-duplicated shape

- **Binds:** CAP-2, CAP-3
- **Prevents:** Overview-card counts drifting out of sync with board-column counts because someone hand-wrote a second interface for "the same data."
- **Rule:** Extend the existing `RepoSummaryResponse` (backend `api_schemas.py`, frontend generated `schema.d.ts` → `api/types.ts` alias) with `awaitingInputCount` and `failedCount` alongside the existing `activeJobCount`. The batch endpoint (AD-3) and the singular endpoint return the same extended shape. No new hand-written TypeScript interface is introduced for either.

```mermaid
flowchart TD
    subgraph Frontend
        DB[DashboardScreen / KanbanBoard] -->|reuses| SEL[store/selectors.ts status buckets]
        PO[ProjectsOverview - new] -->|batch fetch| API1[GET /settings/projects/summary]
        RB[RepoBoard - new, child of RepoLayout] -->|scoped fetch/filter| SEL
        RB -->|route param -> Project| RepoLayout
        PO -->|click card, navigate| RB
        RB -->|fetch| API3[GET /settings/projects/:id/task-links]
    end
    subgraph Backend
        API1 --> SVC[settings.py service path]
        API2[GET /settings/repos/{repo}/summary] --> SVC
        SVC --> DB2[(jobs table)]
        SVC --> DB3[(ProjectRow)]
        SVC --> DB5[(CredentialRow / TrackerLinkRow)]
        POLL[Tracker sync poller] --> ADAPT[TrackerAdapterInterface]
        ADAPT --> EXT[GitHub Projects / Jira / Azure DevOps APIs]
        POLL --> DB4[(TrackerSummaryRow)]
        POLL -->|proposes write| APR[Approval service]
        API3 --> REC[recipe_service.py]
        REC --> DB6[(TaskLinkRow)]
        REC -->|ingest, read-only| SRC[BMAD stories / spec-kit tasks.md, per member repo]
        REC -->|spawn_task, deps satisfied| JOBSVC[existing job-creation service]
        REC -->|tracker_write| APR
    end
```

### AD-5 — Project is the sole persistence entity for repo membership; there is no bare/unassigned repo entry

- **Binds:** CAP-6
- **Prevents:** A second source of truth for "which repos exist" (a repo-only registry row competing with `ProjectRow` membership); an implicit-wrap read-time reconciliation step that would need to handle repos with no Project.
- **Rule:** A new `ProjectRow` (id, name, `repo_paths`) is introduced, owned by a repository class per existing convention, and becomes the *only* place a repo path is durably recorded — the standalone `register_repo`/`create_repo` endpoints (`backend/api/settings.py`, previously repo-scoped) are retired as user-facing add actions; their underlying clone/register logic is called from `project_service.py`'s create/update-membership functions instead, always inside a Project create-or-update transaction. A single-repo Project is not a special case at the data layer — it is a `ProjectRow` with one entry in `repo_paths`, created through the same path as any other Project.

### AD-6 — Integration auth is a global Credential entity, referenced by a separate per-Project TrackerLink; never returned by any API

- **Binds:** CAP-7
- **Prevents:** A tracker PAT leaking via an API response, a log line, or a job's prompt/context; also prevents the earlier per-Project-embedded-credential design, which would force re-entering the same PAT for every Project sharing one tracker account and couldn't represent a Project linked to two trackers at once.
- **Rule:** A new `CredentialRow` (id, provider, label, base_url, encrypted secret) is managed globally from a Settings > Integrations screen, independent of any `ProjectRow`, stored encrypted at rest with an app-level symmetric key (never plaintext config). A new `TrackerLinkRow` (id, project_id, credential_id, external_ref) is the many-to-many join: any number of `TrackerLinkRow`s across different Projects may reference the same `CredentialRow`, and a single Project may hold multiple `TrackerLinkRow`s (e.g. one Jira link and one GitHub Projects link). Deleting a `CredentialRow` is blocked at the repository layer while any `TrackerLinkRow` still references it. No endpoint ever returns the credential value — only a `connected: bool` + `lastSyncedAt` status per link. Job prompt/context construction has no code path that can read `CredentialRow`.

### AD-7 — Tracker sync is a poller writing a separate read model; write-backs are proposed, never applied directly

- **Binds:** CAP-7
- **Prevents:** The sync engine bypassing the existing approval gate, and tracker data corrupting the job-status pipeline (AD-1) it must stay independent of.
- **Rule:** A new backend poller service (shaped like existing background job supervision) calls each connected provider through a shared `TrackerAdapterInterface` (mirrors `AgentAdapterInterface`'s existing isolation of one volatile external SDK — same rationale extends to three volatile external REST APIs) on a configurable interval, once per `TrackerLinkRow`, writing results into a new `TrackerSummaryRow` read model (keyed by `tracker_link_id`) kept separate from `JobRow`. Any outbound action (ticket transition, comment) is created as a new `ApprovalRow` via the existing approval service — the poller itself never calls a provider's write endpoint directly.

### AD-8 — Recipe schema widening lives inside the existing sidecar validation function; no new table for the schema itself

- **Binds:** CAP-8
- **Prevents:** A second, parallel recipe-definition schema/validator diverging from `SidecarTemplateRow`'s existing one, and existing sidecar templates breaking when the vocabulary grows.
- **Rule:** `lifetime: chained`, `outputRoutes: [spawn_task, tracker_write]`, and `contextSources: [story_node, tracker_ticket]` are added as accepted values inside the same validation function that already checks `_ALLOWED_PHASES`/`_ALLOWED_LIFETIMES`/`_ALLOWED_SCOPES`/`_ALLOWED_CONTEXT_SOURCES`/`_ALLOWED_OUTPUT_ROUTES` in `template_service.py`. `SidecarTemplateRow` and its `definition_json` column are reused unchanged — no new schema table, no version flag, no migration.

### AD-9 — `TaskLinkRow` is a new, thin, Project-scoped table owned by a new `recipe_service.py`; ingestion is a stateless on-demand parser, never a background watcher

- **Binds:** CAP-9
- **Prevents:** A heavyweight parallel "Task" execution entity; a filesystem watcher silently re-ingesting on every save (surprising, hard to reason about, and unnecessary since re-ingestion is explicitly user-triggered per CAP-9's success criterion).
- **Rule:** A new `TaskLinkRow` (`id`, `project_id`, `repo_path`, `story_node_id`, `depends_on: list[str]`, `job_id: nullable`) is owned by a new `recipe_service.py`, following the existing repository-owns-DB-access convention. Ingestion is a stateless function invoked on demand (a settings action, not a poller or watcher): given a `project_id`, it iterates every repo in `project.repo_paths` (AD-5's `ProjectRow.repo_paths`), parses each repo's BMAD stories or spec-kit `tasks.md` independently, and upserts `TaskLinkRow`s keyed by `(project_id, repo_path, story_node_id)` — so `depends_on` can validly reference a `story_node_id` in a sibling member repo of the same Project without any cross-Project reference ever being possible.

### AD-10 — `spawn_task` reuses the existing job-creation service function directly; no second execution pipeline

- **Binds:** CAP-10
- **Prevents:** A second, recipe-specific job-execution path drifting from the real one (worktree provisioning, branch naming, agent adapter dispatch) that every user-initiated job already goes through.
- **Rule:** When a `chained` recipe's `spawn_task` output route fires (a `TaskLinkRow`'s dependencies are all satisfied), it calls the same internal job-creation service function used by `codeplane_job create` — same worktree/branch provisioning, same `AgentAdapterInterface` dispatch — passing the recipe's configured prompt/context. The resulting `job_id` is written onto the `TaskLinkRow` it was spawned for. `TaskLinkRow` never becomes a competing run entity; it only ever points at zero-or-one real `JobRow`.

### AD-11 — `TaskLink` read model is a separate endpoint, polled by the board alongside job data, not folded into the Project summary endpoint

- **Binds:** CAP-9, CAP-10
- **Prevents:** Overloading `GET /settings/projects/summary` (AD-3's single-batch-call contract for CAP-2/CAP-3) with a materially different, per-card data shape, which would slow down or complicate the overview's own fast path.
- **Rule:** A new `GET /settings/projects/{id}/task-links` endpoint returns every `TaskLinkRow` for a Project (with resolved dependency-satisfied state), fetched by `RepoBoard.tsx` (CAP-1) alongside its existing job fetch, so `TaskLink` cards (CAP-10, rendered greyed-out until dependencies are satisfied, with a chained-lifetime badge) render in the same column grid as regular job cards through one client-side rendering pass — not a separate screen or a second board.

### AD-12 — Chat is one persistent, git-free entity that can launch Jobs and/or gate a TaskLink chain; no separate Orchestrator entity

- **Binds:** CAP-12
- **Prevents:** A second execution engine growing up beside `Job`/`GitService`; a Chat accidentally gaining git capability through shared code paths with Job; a redundant second scheduler/entity (an "Orchestrator") duplicating what a Chat already models; `project_id` being forced non-null and creating friction for a Chat with no natural Project yet.
- **Rule:** A new `ChatRow` (`id`, `project_id` **nullable**, `title`, `created_at`, `last_message_at`, `status`) is owned by a new `chat_service.py`, which has no dependency on `GitService` at all — not "unused," structurally absent, so a Chat cannot provision a worktree or branch by construction. Read-only repo context (if used) goes through the existing workspace read tools, never a git write path. `project_id` defaults at creation from UI context (`RepoBoard` → that Project's id; global nav → `null`), user-overridable in the creation dialog. Two independent, repeatable actions are available from within an open Chat, neither of which consumes or replaces it:
  - **Launch a Job** (`POST /settings/chats/{id}/launch-job`) calls the same job-creation service function AD-10 established for `spawn_task`, passing the chat transcript as the new Job's seed prompt/context, and provisions a worktree/branch for the first time at that call. If `project_id` is still null, the user is prompted to pick a Project/repo at this call, and the result is written back onto the `ChatRow`. The Chat itself is untouched by this beyond that write-back — it remains open and can launch further Jobs later.
  - **Attach to a chain** (`POST /settings/chats/{id}/attach-chain`) links the `ChatRow` to a specific `task_link_id` (owned by `recipe_service.py` alongside `TaskLinkRow`, AD-9) in gating mode. If `project_id` is still null, it is settled from the chain's Project at this call. CAP-10's `spawn_task` dispatch checks for an active, gated Chat attached to the completing `TaskLink`'s chain before firing: if none exists, behavior is exactly AD-10's existing ungated auto-spawn; if one exists, `spawn_task` creates a `codeplane_approval` entry (the same mechanism AD-7/CAP-11 already use) instead of calling the job-creation service directly, and only calls it once that approval is granted. Narration in this mode is read-only status text derived from polling the chain's `TaskLinkRow`/Job states — it never calls `GitService` or the job-creation function on its own.

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming (entities, files, interfaces, events) | New frontend components/routes follow existing `Repo*` naming (`RepoBoard`, `ProjectsOverview`); new backend fields are `camelCase` on the wire via the existing `CamelModel` base, `snake_case` in Python, matching every other schema in `api_schemas.py`. |
| Data & formats (ids, dates, error shapes, envelopes) | Reuses `RepoSummaryResponse`'s existing field/date conventions; no new envelope or error shape introduced. |
| State & cross-cutting (mutation, errors, logging, config, auth) | Route handlers stay thin (validate + delegate), per project convention; job-status classification logic is the single cross-cutting rule this feature adds (AD-1). |

## Stack

| Name | Version |
| --- | --- |
| React | 18 (existing, unchanged) |
| react-router-dom | existing pinned version in `frontend/package.json` (unchanged; nested routes only) |
| Zustand | existing (unchanged) |
| FastAPI / Pydantic (`CamelModel`) | existing (unchanged) |
| SQLAlchemy | existing (unchanged) |

## Structural Seed

```text
frontend/src/
  components/
    RepoLayout.tsx        # EXISTING — per-project sidebar shell, owns /repos/:repoPath/*, gains filter input (CAP-5)
    RepoBoard.tsx          # NEW — CAP-1, child route "/repos/:repoPath/board", reuses KanbanColumn, scoped to project.repo_paths; also fetches TaskLinks (CAP-10/AD-11), rendered in the same grid as job cards
    ProjectsOverview.tsx   # NEW — CAP-2/CAP-3/CAP-5, renders at bare "/repos" index (replaces auto-redirect), filter box, tracker chip
    ProjectSettings.tsx    # NEW — CAP-6, create/edit Project, assign repos, attach existing TrackerLinks; trigger CAP-9 ingestion action
    IntegrationsSettings.tsx # NEW — CAP-7, global Credential CRUD (Settings > Integrations), independent of any Project
    ChatPanel.tsx           # NEW — CAP-12, persistent Chat: conversation view, "Launch Job" and "Attach to chain" actions, nullable Project context
    KanbanColumn.tsx       # EXISTING — reused unchanged by RepoBoard (CAP-1)
    ~~KanbanBoard.tsx / DashboardScreen~~ # RETIRED (CAP-1-4) — flat cross-repo view removed, /repos is now the only entry point
  store/
    selectors.ts           # EXISTING — status-bucket selectors reused by RepoBoard (AD-1)

backend/
  api/
    settings.py             # EXISTING — get_repo_summary retired in favor of get_projects_summary (AD-3/AD-5); register_repo/create_repo/unregister_repo endpoints retired as standalone actions, logic called from project_service.py instead
    projects.py              # NEW — Project CRUD (CAP-6), tracker connect/disconnect (CAP-7), task-links endpoint (AD-11)
    chats.py                 # NEW — Chat CRUD, launch-job endpoint, attach-chain endpoint (CAP-12/AD-12)
  models/
    api_schemas.py           # EXISTING — RepoSummaryResponse extended with 2 fields (AD-4) + optional trackerSummary
    db.py                    # EXISTING — adds ProjectRow (AD-5), CredentialRow + TrackerLinkRow (AD-6), TrackerSummaryRow (AD-7), TaskLinkRow (AD-9), ChatRow (AD-12, project_id nullable)
  services/
    project_service.py       # NEW — Project repository/service; create/update-membership call the existing clone/register logic (AD-5)
    credential_service.py    # NEW — global Credential CRUD, delete-blocked-while-linked guard (AD-6)
    tracker_adapter.py        # NEW — TrackerAdapterInterface + per-provider adapters (AD-7)
    tracker_sync_service.py   # NEW — poller, iterates TrackerLinkRow, writes TrackerSummaryRow, proposes ApprovalRow on write-back (AD-7)
    sidecar/template_service.py # EXISTING — validation function gains chained/spawn_task/tracker_write/story_node/tracker_ticket branches (AD-8)
    recipe_service.py         # NEW — owns TaskLinkRow, on-demand Project-scoped ingestion (AD-9), spawn_task dispatch via existing job-creation function with Chat-attach gate check (AD-10, AD-12)
    chat_service.py           # NEW — owns ChatRow, no GitService dependency by construction; launch_job() and attach_chain() call the shared job-creation function / recipe_service respectively (AD-12)
  mcp/
    server.py                 # EXISTING — new codeplane_project tool added alongside unchanged codeplane_repo/codeplane_job tools
```

## Capability → Architecture Map

| Capability / Area | Lives in | Governed by |
| --- | --- | --- |
| CAP-1 Project-scoped board | `RepoBoard.tsx`, route `/repos/:repoPath/board` | AD-1, AD-2, AD-5 |
| CAP-2 Projects overview | `ProjectsOverview.tsx`, route `/repos` (index) | AD-3, AD-4, AD-5 |
| CAP-3 Cross-project attention rollup | `ProjectsOverview.tsx` (badge, sums batch response) | AD-3, AD-4 |
| CAP-4 Registry-driven empty states | `ProjectsOverview.tsx` + `RepoLayout.tsx` (both already read `fetchRepos`) | AD-3 (batch endpoint iterates the full registry, not just repos with jobs), AD-5 |
| CAP-5 Filter/search | `RepoLayout.tsx` sidebar, `ProjectsOverview.tsx` card grid | none new — client-side filter over existing fetched data |
| CAP-6 Project registry CRUD | `ProjectSettings.tsx`, `backend/api/projects.py`, `project_service.py` | AD-5 |
| CAP-7 External tracker sync | `IntegrationsSettings.tsx` (global Credential CRUD), `ProjectSettings.tsx` (attach TrackerLink), `credential_service.py`, `tracker_adapter.py`, `tracker_sync_service.py` | AD-6, AD-7 |
| CAP-8 Widen recipe vocabulary | `sidecar/template_service.py` (existing validation function) | AD-8 |
| CAP-9 Project-scoped BMAD/spec-kit ingestion | `ProjectSettings.tsx` (trigger), `recipe_service.py` | AD-9 |
| CAP-10 Chained TaskLink cards on the board | `RepoBoard.tsx` (renders alongside job cards), `backend/api/projects.py` (task-links endpoint), `recipe_service.py` (spawn_task) | AD-10, AD-11 |
| CAP-11 tracker_write reuses CAP-7's approval gate | `recipe_service.py` → existing approval service | AD-7, AD-10 |
| CAP-12 Persistent Chat: launch Jobs and/or gate a recipe chain | `ChatPanel.tsx`, `backend/api/chats.py`, `chat_service.py`, `recipe_service.py` (gate check), existing approval service | AD-12 |

## Deferred

- Whether `RepoLayout`'s sidebar itself should show live status badges per repo (beyond the overview page) — deferred; not required by any CAP in SPEC.md, would be a follow-up enhancement once CAP-1/CAP-2 ship and real usage patterns are visible.
- Auth/permissions scoping of which repos a user can see in the overview — deferred; out of scope for this feature, inherits whatever access model `fetchRepos`/`fetchRepoSummary` already have today (no change).
- Additional tracker providers beyond GitHub Projects/Jira/Azure DevOps — deferred; `TrackerAdapterInterface` (AD-7) is designed to admit more providers later without touching CAP-1-6.
