---
name: 'project-boards'
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: 'layered (route-scoped feature slice inside an existing thin-route/service/repository backend and Zustand-store frontend)'
scope: 'Repo/Project-scoped Kanban board (CAP-1) and cross-project overview with attention rollup, filter, Project registry, external-tracker sync, Task Recipe chaining/ingestion, and a persistent Chat that can launch Jobs and/or gate a recipe chain (CAP-2/CAP-3/CAP-4/CAP-5/CAP-6/CAP-7/CAP-8/CAP-9/CAP-10/CAP-11/CAP-12) for CodePlane'
status: final
created: '2026-08-06'
updated: '2026-08-17'
binds: ["CAP-1", "CAP-2", "CAP-3", "CAP-4", "CAP-5", "CAP-6", "CAP-7", "CAP-8", "CAP-9", "CAP-10", "CAP-11", "CAP-12", "CAP-13", "CAP-14"]
sources: ["_bmad-output/specs/spec-project-boards/SPEC.md"]
companions: []
---

# Architecture Spine — project-boards

## Design Paradigm

Route-scoped feature slice inside CodePlane's existing layering: FastAPI routes stay thin and delegate to services/repositories (backend), React components read the Zustand store via named selectors (frontend). Project ID is the canonical navigation identity; repository paths remain member data and explicit repository-analytics scope.

## Invariants & Rules

### AD-1 — One shared job-status classifier, two call sites

- **Binds:** CAP-1, CAP-2, CAP-3
- **Prevents:** The frontend board and the backend-computed overview counts disagreeing on what counts as "awaiting input" vs "failed" vs "in progress".
- **Rule:** Status bucketing (in-progress / awaiting-input / failed) is defined once per layer and reused, never re-implemented at the call site: frontend reuses `selectActiveJobs` / `selectSignoffJobs` / `selectAttentionJobs` (`store/selectors.ts`) for both `KanbanBoard` and any board filtered by repo; backend reuses the same job-count query path `get_repo_summary` (`backend/api/settings.py`) already uses, extended in place rather than duplicated into a new query.

### AD-2 — Project identity travels via a stable URL parameter

- **Binds:** CAP-1, CAP-2, CAP-6
- **Prevents:** URLs becoming invalid or ambiguous when a Project contains multiple repositories or membership changes.
- **Rule:** Project routes use `/projects/id/:projectId/*` and read `projectId` from `useParams`. Legacy repository-path links may resolve once through a membership lookup and redirect to the canonical Project-ID route, but no new UI emits repository-path routes. Repository analytics use a required member-repository selector nested under the Project route; no view silently defaults to the first repository.

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
        API2[GET /settings/projects/{id}/summary] --> SVC
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
- **Rule:** A new backend poller service (shaped like existing background job supervision) calls each connected provider through a shared `TrackerAdapterInterface` (mirrors `AgentAdapterInterface`'s existing isolation of one volatile external SDK — same rationale extends to three volatile external REST APIs) every 60 seconds, once per `TrackerLinkRow`, writing results into a new `TrackerSummaryRow` read model (keyed by `tracker_link_id`) kept separate from `JobRow`. A manual refresh runs the same path immediately. Any outbound action (ticket transition, comment) is created as a new `ApprovalRow` via the existing approval service; approval execution invokes the selected adapter exactly once.

### AD-8 — Recipe schema widening lives inside the existing sidecar validation function; no new table for the schema itself

- **Binds:** CAP-8
- **Prevents:** A second, parallel recipe-definition schema/validator diverging from `SidecarTemplateRow`'s existing one, and existing sidecar templates breaking when the vocabulary grows.
- **Rule:** `lifetime: chained`, `outputRoutes: [spawn_task, tracker_write]`, and `contextSources: [story_node, tracker_ticket]` are added as accepted values inside the same validation function that already checks `_ALLOWED_PHASES`/`_ALLOWED_LIFETIMES`/`_ALLOWED_SCOPES`/`_ALLOWED_CONTEXT_SOURCES`/`_ALLOWED_OUTPUT_ROUTES` in `template_service.py`. `SidecarTemplateRow` and its `definition_json` column are reused unchanged — no new schema table, no version flag, no migration.

### AD-9 — `TaskLinkRow` is a new, thin, Project-scoped table owned by a new `recipe_service.py`; ingestion is a stateless on-demand parser, never a background watcher

- **Binds:** CAP-9
- **Prevents:** A heavyweight parallel "Task" execution entity; a filesystem watcher silently re-ingesting on every save (surprising, hard to reason about, and unnecessary since re-ingestion is explicitly user-triggered per CAP-9's success criterion).
- **Rule:** A new `TaskLinkRow` (`id`, `project_id`, `repo_path`, `story_node_id: nullable`, `depends_on: list[str]`, `job_id: nullable`, `tracker_link_id: nullable`, `tracker_ticket_ref: nullable`, `prompt_override: nullable`, `epic_id: nullable`) is owned by a new `recipe_service.py`, following the existing repository-owns-DB-access convention. It is populated by two independent creation paths, neither required nor coerced to resemble the other: (1) ingestion parses each member repo on demand and upserts by `(project_id, repo_path, story_node_id)`; (2) manual assignment targets an existing ticket from an explicitly selected Project TrackerLink, setting `tracker_link_id` + `tracker_ticket_ref` + `prompt_override`. Many TaskLinks may share one ticket, but every tracker-backed row retains its owning link. `story_node_id` and `tracker_ticket_ref` are independently nullable, and exactly one is guaranteed non-null at creation. `epic_id` is cosmetic only.

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
**Rule:** A new `ChatRow` (`id`, `project_id` **nullable**, `title`, `created_at`, `last_message_at`, `status`) is owned by a new `chat_service.py`, which has no dependency on `GitService` at all — not "unused," structurally absent, so a Chat cannot provision a worktree or branch by construction. Read-only repo context (if used) goes through the existing workspace read tools, never a git write path. `project_id` defaults at creation from UI context (`RepoBoard` → that Project's id; global nav → `null`), user-overridable in the creation dialog. Messages use `{role, content}` and expose assistant-response and failure states. Two independent, repeatable actions are available from within an open Chat, neither of which consumes or replaces it:
  - **Launch a Job** (`POST /settings/chats/{id}/launch-job`) calls the same job-creation service function AD-10 established for `spawn_task`, passing the chat transcript as the new Job's seed prompt/context, and provisions a worktree/branch for the first time at that call. If `project_id` is still null, the user is prompted to pick a Project/repo at this call, and the result is written back onto the `ChatRow`. The Chat itself is untouched by this beyond that write-back — it remains open and can launch further Jobs later.
  - **Attach to a chain** (`POST /settings/chats/{id}/attach-chain`) links the `ChatRow` to a specific `task_link_id` (owned by `recipe_service.py` alongside `TaskLinkRow`, AD-9) in gating mode. If `project_id` is still null, it is settled from the chain's Project at this call. CAP-10's `spawn_task` dispatch checks for an active, gated Chat attached to that exact chain before firing: if none exists, behavior is exactly AD-10's ungated auto-spawn; if one exists, `spawn_task` creates a `codeplane_approval` entry instead of calling the job-creation service directly, and only calls it once that approval is granted. Narration is read-only status text derived from that chain's TaskLink/Job states. The frontend labels the Chat with a shared Epic only when every resolved TaskLink shares one non-null `epic_id`; otherwise it renders a generic "chain."

### AD-13 — `codeplane_tracker` is a second caller of the existing approval gate, not a second write mechanism

- **Binds:** CAP-13, CAP-11
- **Prevents:** An agent-initiated tracker write bypassing approval by inventing its own path to `tracker_adapter.py`; a second, differently-shaped approval entry type for agent-initiated vs. recipe-initiated writes; the agent needing its own copy of a Credential's PAT.
- **Rule:** A new `codeplane_tracker` MCP tool (comment, transition) resolves the calling Job's Project and its TrackerLink(s) server-side, then calls the exact same `codeplane_approval`-creation function AD-7/CAP-11's `tracker_write` output route already calls — same approval shape, same resolution/execution path once granted, only the caller (agent-initiated vs. recipe-initiated) differs. The agent never receives or handles the Credential's decrypted secret; CodePlane resolves and uses it server-side on the agent's behalf. This tool operates at Project-TrackerLink granularity (an agent comments on "the" tracker link its Job's Project has), distinct from AD-9's per-`TaskLink` `tracker_ticket_ref` targeting used by CAP-11's recipe-driven writes — the two granularities are intentionally different, not inconsistent: a chained recipe knows exactly which ticket its TaskLink node is paired with, while an agent mid-job addresses whichever TrackerLink(s) its Project has.

### AD-14 — `codeplane_pr` and completion-time auto-PR share one `_create_pr` implementation

- **Binds:** CAP-14
- **Prevents:** A second, divergent PR-creation code path growing up beside `merge_service._create_pr`; duplicate PRs from calling both the agent tool and the automatic completion path for the same Job.
- **Rule:** A new `codeplane_pr` MCP tool, callable mid-job, invokes `merge_service._create_pr` directly (the same function the existing completion/merge-strategy path calls) rather than a parallel implementation. `_create_pr` becomes idempotent per Job (checks for an existing PR on the Job before creating one) so a Job that calls `codeplane_pr` and then completes normally does not get a second PR from the automatic path, and vice versa.

### AD-15 — Project and repository membership changes are transactional and explicit

- **Binds:** CAP-6
- **Prevents:** Cancelled or failed Project creation leaving cloned/registered repositories behind, and membership edits silently orphaning active work or integration state.
- **Rule:** Project creation stages repository side effects and commits them with Project persistence; cancellation/failure rolls back newly-created side effects or presents an explicit recovery action. Membership removal requires confirmation, rejects unsafe removal while active Jobs or dependent TaskLinks exist unless the user chooses a documented disposition, and never deletes historical Job records implicitly. A Project always retains at least one repository.

### AD-16 — Tracker actions target an explicit link and report provider truth

- **Binds:** CAP-7, CAP-11, CAP-13
- **Prevents:** Selecting the first TrackerLink by insertion order, claiming a write was dispatched when no provider call occurred, and accepting invalid provider references that only fail during polling.
- **Rule:** Attach uses provider-specific reference fields plus a provider validation/test operation. Every outbound action stores `tracker_link_id` and, when applicable, `tracker_ticket_ref`; approval execution invokes that adapter exactly once and persists pending/applied/rejected/failed state. TrackerLinks support detach, and Credential deletion remains blocked only while links exist. Polling uses a fixed 60-second cadence plus manual refresh.

### AD-17 — TaskLink lifecycle is visible and atomically claimed

- **Binds:** CAP-9, CAP-10, CAP-11
- **Prevents:** Inert task cards, misleading dependency readiness, orphan Jobs from concurrent spawns, and tracker writes routed to an ambiguous Project default.
- **Rule:** TaskLinks expose waiting/ready/running/completed/failed state, source and linked-Job context, and a start action for ready roots. Dependency satisfaction accepts only the terminal success states defined by the Job state machine. A repository transaction claims a ready TaskLink before creating its Job; duplicate claims return the existing Job. Recipe writes use the TaskLink's explicit TrackerLink/ticket pair.

### AD-18 — Chat is a real conversation with explicit execution boundaries

- **Binds:** CAP-12
- **Prevents:** A Chat UI that can create messages but cannot produce or surface a response, request-shape mismatches, and loss of Project context after launching a Job.
- **Rule:** Chat messages use the `{role, content}` contract and expose sending, assistant-response, and failure states. Chat remains git-free; Launch Job is an explicit transition to the shared Job-creation service. Chat, Job, TaskLink, and Project views preserve breadcrumbs and stable deep links.

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
    RepoLayout.tsx        # EXISTING — Project sidebar shell, owns /projects/id/:projectId/*, gains filter input and repo selector
    RepoBoard.tsx          # NEW — CAP-1, child route "/projects/id/:projectId/board", reuses KanbanColumn, scoped to project.repo_paths; also fetches TaskLinks
    ProjectsOverview.tsx   # NEW — CAP-2/CAP-3/CAP-5, renders at "/projects" index, filter box, integration summary
    ProjectSettings.tsx    # NEW — CAP-6, create/edit Project, assign repos, attach existing TrackerLinks; trigger CAP-9 ingestion action
    IntegrationsSettings.tsx # NEW — CAP-7, global Credential CRUD (Settings > Integrations), independent of any Project
    ChatPanel.tsx           # NEW — CAP-12, persistent Chat: conversation view, "Launch Job" and "Attach to chain" actions, nullable Project context
    KanbanColumn.tsx       # EXISTING — reused unchanged by RepoBoard (CAP-1)
    ~~KanbanBoard.tsx / DashboardScreen~~ # RETIRED (CAP-1-4) — flat cross-repo view removed, /projects is now the only entry point
  store/
    selectors.ts           # EXISTING — status-bucket selectors reused by RepoBoard (AD-1)

backend/
  api/
    settings.py             # EXISTING — project summary is the overview source; repository analytics remain explicitly member-repository scoped
    projects.py              # NEW — Project CRUD (CAP-6), tracker connect/disconnect (CAP-7), task-links/list/start endpoints (AD-11/AD-17)
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
    server.py                 # EXISTING — new codeplane_project tool added alongside unchanged codeplane_repo/codeplane_job tools; new agent-facing codeplane_tracker (CAP-13) and codeplane_pr (CAP-14) tools added
```

## Capability → Architecture Map

| Capability / Area | Lives in | Governed by |
| --- | --- | --- |
| CAP-1 Project-scoped Agent Runs | `RepoBoard.tsx`, route `/projects/id/:projectId/board` | AD-1, AD-2, AD-5, AD-17 |
| CAP-2 Projects overview | `ProjectsOverview.tsx`, route `/projects` (index) | AD-3, AD-4, AD-5 |
| CAP-3 Cross-project attention rollup | `ProjectsOverview.tsx` (badge, sums batch response) | AD-3, AD-4 |
| CAP-4 Registry-driven empty states | `ProjectsOverview.tsx` + `RepoLayout.tsx` (both already read `fetchRepos`) | AD-3 (batch endpoint iterates the full registry, not just repos with jobs), AD-5 |
| CAP-5 Filter/search | `RepoLayout.tsx` sidebar, `ProjectsOverview.tsx` card grid | none new — client-side filter over existing fetched data |
| CAP-6 Project registry CRUD | `ProjectSettings.tsx`, `backend/api/projects.py`, `project_service.py` | AD-5, AD-15 |
| CAP-7 External tracker sync | `IntegrationsSettings.tsx` (global Credential CRUD), `ProjectSettings.tsx` (attach/detach TrackerLink), `credential_service.py`, `tracker_adapter.py`, `tracker_sync_service.py` | AD-6, AD-7, AD-16 |
| CAP-8 Widen recipe vocabulary | `sidecar/template_service.py` (existing validation function) | AD-8 |
| CAP-9 Project-scoped BMAD/spec-kit ingestion | `ProjectSettings.tsx` (trigger), `recipe_service.py` | AD-9 |
| CAP-10 Chained TaskLink cards on the board | `RepoBoard.tsx` (renders alongside job cards), `backend/api/projects.py` (task-links endpoint), `recipe_service.py` (atomic spawn) | AD-10, AD-11, AD-17 |
| CAP-11 tracker_write reuses CAP-7's approval gate | `recipe_service.py` → existing approval service | AD-7, AD-10, AD-16, AD-17 |
| CAP-12 Persistent Chat: launch Jobs and/or gate a recipe chain | `ChatPanel.tsx`, `backend/api/chats.py`, `chat_service.py`, `recipe_service.py` (gate check), existing approval service | AD-12, AD-18 |
| CAP-13 Agent-facing `codeplane_tracker` MCP tool | `mcp/server.py` (new tool), `tracker_adapter.py`, existing approval service | AD-13, AD-7 |
| CAP-14 Agent-facing `codeplane_pr` MCP tool | `mcp/server.py` (new tool), `merge_service/_service.py` (`_create_pr`, made idempotent per Job) | AD-14 |

## Deferred

- Whether `RepoLayout`'s sidebar itself should show live status badges per repo (beyond the overview page) — deferred; not required by any CAP in SPEC.md, would be a follow-up enhancement once CAP-1/CAP-2 ship and real usage patterns are visible.
- Auth/permissions scoping of which repos a user can see in the overview — deferred; out of scope for this feature, inherits whatever access model `fetchRepos`/`fetchRepoSummary` already have today (no change).
- Additional tracker providers beyond GitHub Projects/Jira/Azure DevOps — deferred; `TrackerAdapterInterface` (AD-7) is designed to admit more providers later without touching CAP-1-6.
