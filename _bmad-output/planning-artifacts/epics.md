---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: ["_bmad-output/specs/spec-project-boards/SPEC.md", "_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md", "_bmad-output/specs/spec-project-boards/ui-flows.md"]
---

# codeplane - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for codeplane, decomposing the requirements from the SPEC (used here as the PRD-equivalent input, since this initiative ran through `bmad-spec` rather than `bmad-prd`), the ui-flows.md UX contract, and the Architecture Spine requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: User can scope a Kanban board to a single repo/Project as a child route of the existing `/repos/:repoPath` shell. (CAP-1)
FR2: User can view a Projects Overview at the bare `/repos` index route with one card per Project (active/awaiting/failed counts, last-activity), drilling into that Project's board. (CAP-2)
FR3: User can see a single rolled-up "needs attention" (awaiting input + failed, cross-Project) signal on the overview screen. (CAP-3)
FR4: The set of boards/cards shown is driven by the Project registry, not only Projects with active jobs, so an idle Project still appears. (CAP-4)
FR5: User can filter the Projects Overview grid and sidebar Project list by name, applied generically at the card-rendering layer so it covers both Project cards and TaskLink cards. (CAP-5)
FR6: Adding a repo is done exclusively by creating or editing a Project; there is no standalone "register a repo" action. A single-repo Project is the common case; membership can be edited later. (CAP-6)
FR7: User registers a Credential (provider, label, base URL, encrypted PAT) once, globally, in Settings > Integrations. User attaches a TrackerLink (Credential + external project/board ref) to any Project; inbound sync polls and renders; outbound writes route through approval. (CAP-7)
FR8: The sidecar-template recipe vocabulary is widened with `lifetime: chained`, and new `outputRoutes` (`spawn_task`, `tracker_write`) and `contextSources` (`story_node`, `tracker_ticket`). (CAP-8)
FR9: BMAD stories / spec-kit `tasks.md` can be ingested per-Project (iterating every member repo) into `TaskLink` rows with cross-repo `depends_on` support within one Project, read-only against source repos. Alternatively, a `TaskLink` can be created manually and assigned directly to an existing tracker ticket (visible via CAP-7's TrackerLink) with a free-form prompt, independent of any BMAD/spec-kit source. Either creation path may optionally be paired with the other's field (`story_node_id` / `tracker_ticket_ref`) after the fact; neither path requires the other. (CAP-9)
FR10: TaskLink nodes with satisfied dependencies render as cards on the Project board; completing a linked job auto-spawns the next dependent TaskLink's job via `spawn_task`. (CAP-10)
FR11: Any recipe output routed to `tracker_write` reuses the existing `codeplane_approval` flow; no second, recipe-specific approval mechanism. The write targets the firing `TaskLink`'s own `tracker_ticket_ref` when set; a `TaskLink` with none has no `tracker_write` action available — never a fallback to an ambiguous Project-level default ticket. (CAP-11)
FR12: User can start a Chat: a persistent, purely conversational session with no worktree/branch/git operations, nullable `project_id` (context-default, user-overridable). From a Chat, the user can launch one or more Jobs (each with its own worktree/branch, seeded from the transcript, Chat remains open) and/or attach the Chat to a Project's Task Recipe chain to narrate progress and optionally gate auto-spawn behind an approval. (CAP-12)
FR13: Agent running inside a Job can call a new `codeplane_tracker` MCP tool (comment, transition) to act on the linked tracker ticket; every call routes through the existing `codeplane_approval` gate (same shape as recipe-driven writes), and the agent never handles the Credential's PAT directly. (CAP-13)
FR14: Agent running inside a Job can call a new `codeplane_pr` MCP tool to proactively request a PR mid-job, sharing the same `_create_pr` implementation as the existing automatic completion-time PR creation; idempotent per Job (no duplicate PRs). (CAP-14)

### NonFunctional Requirements

NFR1: External tracker PATs are encrypted at rest, never plaintext-logged, never included in agent-facing job prompts/context. (CAP-7 / Constraints)
NFR2: Tracker sync is poll-based only (configurable interval + manual refresh) — no inbound webhooks, since CodePlane has no public endpoint. (CAP-7 / Constraints)
NFR3: No OAuth app registrations for any tracker provider (GitHub Projects, Jira, Azure DevOps incl. on-prem Server) — locally-stored PATs only. (CAP-7 / Constraints, Non-goals)
NFR4: Overview data must be fetchable in one batch call, never N per-Project calls. (AD-3)
NFR5: A repo may belong to at most one explicit Project (enforced), to prevent double-counting job totals across overlapping Projects. (Constraints)
NFR6: Existing `Job`/`JobSummary` schema and single-board consumers (`KanbanBoard`, `MobileJobList`, `frontend/e2e`) must not break during rollout. (Constraints)
NFR7: Analytics/cost/health stay repo-keyed as source of truth; any Project-level number is a client-side or thin-aggregate sum, never a second pipeline. (Constraints)
NFR8: Chat is never git-capable itself (no `GitService` call of any kind, ever) — isolation between "just talking" and "a worktree exists" is absolute, not best-effort. (Constraints)
NFR9: PAT scope requirements are per-provider and must be documented + surfaced at Credential-creation time as copy-paste guidance only. GitHub fine-grained PATs are scopable per-repo (`Issues: R/W` for tracker writes; `Contents: R/W` + `Pull requests: R/W` for PR creation) — no runtime validate/warn against TrackerLinks, since Credential is deliberately global/reusable and broader-than-any-single-link scope is expected, not anomalous. Jira API-token auth has no granular scope (inherits full account permissions); Azure DevOps PATs are org-scoped not project-scoped. For Jira/AzDO the `codeplane_approval` write-back gate is the real security boundary, not token scope. (Constraints)

### Additional Requirements

- New `ProjectRow` (id, name, `repo_paths: list[str]`) as the sole repo-membership entity; existing `Job.repo`/`branch`/`pr_url` and `codeplane_repo` registry untouched structurally but narrowed to read-only. (AD-5)
- `GET /settings/projects/summary` batch endpoint, extending `RepoSummaryResponse` with `awaitingInputCount`/`failedCount` alongside existing `activeJobCount`; same extended shape on both batch and singular endpoints. (AD-3, AD-4)
- New `CredentialRow` (id, provider, label, base_url, encrypted secret) and `TrackerLinkRow` (id, project_id, credential_id, external_ref) as the many-to-many join; deleting a Credential blocked while referenced. (AD-6)
- `tracker_adapter.py` interface plus GitHub Projects/Jira/Azure DevOps adapters, PAT-only. (AD-7)
- `TaskLinkRow` (project_id, repo_path, story_node_id: nullable, depends_on[], job_id: nullable, tracker_ticket_ref: nullable, prompt_override: nullable, epic_id: nullable) as a thin correlation row, not a parallel execution model competing with `Job`; exactly one of `story_node_id`/`tracker_ticket_ref` is guaranteed non-null at creation (never neither). `epic_id` is cosmetic board-label data only, sourced solely from ingestion when the source BMAD story has identifiable Epic membership — never present on manually-assigned TaskLinks, never inferred. (AD-9)
- `ChatRow` (id, project_id nullable, title, created_at, last_message_at, status), owned by `chat_service.py` with zero `GitService` dependency. Two actions: `POST /settings/chats/{id}/launch-job` and `POST /settings/chats/{id}/attach-chain`. (AD-12)
- MCP surface: `codeplane_project` (create/update/list/get/assign-repos/attach-tracker-link/ingest-tasks) is the sole add-path; `codeplane_repo` narrows to read-only list/get; `codeplane_job` unchanged (repo-scoped). Two new agent-facing tools additive to this surface: `codeplane_tracker` (CAP-13) and `codeplane_pr` (CAP-14) — neither exposes the underlying Credential/git auth to the agent. (AD-13, AD-14)
- The existing flat `DashboardScreen`/`KanbanBoard` is retired outright; `/repos` (Overview + per-Project board) is the single entry point. No synthetic "default/All Projects" entity.

### UX Design Requirements

UX-DR1: `RepoBoard.tsx` — Kanban scoped to one Project (child route of `RepoLayout`), reusing the existing three-column status classifier. (ui-flows.md CAP-1)
UX-DR2: `ProjectsOverview.tsx` — card grid at `/repos` index, one card per Project (including empty ones), rolled-up attention badge, filter/search box. (ui-flows.md CAP-2/3/4/5)
UX-DR3: `IntegrationsSettings.tsx` — global Credential list (Settings > Integrations) showing usage counts; per-Project TrackerLink attach/detach UI. (ui-flows.md CAP-7)
UX-DR4: TaskLink cards render in the same column grid as Job cards on `RepoBoard`, greyed out until dependencies are satisfied. (ui-flows.md CAP-10)
UX-DR5: `ChatPanel.tsx` + `/repos/:project/chats` tab — flat list, conversation view, explicitly no repo/branch/worktree indicators; action buttons are "Launch Job" / "Attach to chain" / "Detach" (never "Promote"). (ui-flows.md CAP-12)

### FR Coverage Map

| Requirement | Epic |
| --- | --- |
| FR1, FR2, FR3, FR4, FR5, FR6, NFR5, NFR6, UX-DR1, UX-DR2 | Epic 1 |
| FR7, NFR1, NFR2, NFR3, NFR9, UX-DR3 | Epic 2 |
| FR8, FR9, FR10, FR11, UX-DR4 | Epic 3 |
| FR12, NFR8, UX-DR5 | Epic 4 |
| FR13, FR14 | Epic 5 |
| NFR2, NFR4, NFR7 | Cross-cutting (all epics) |

## Epic List

### Epic 1: Project-based organization
Users can create/edit Projects (single- or multi-repo) and see them organized as an overview + per-Project board — one complete, standalone outcome. No standalone "register a repo" action exists outside this epic.
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, NFR5, NFR6, UX-DR1, UX-DR2

### Epic 2: Tracker integration
Users connect a Jira/Azure DevOps/GitHub Projects account once (a global Credential) and attach it to any Project as a TrackerLink; they see ticket/board state pulled in via polling, and any write-back is visible as a normal approval request before it takes effect.
**FRs covered:** FR7, NFR1, NFR2, NFR3, NFR9, UX-DR3

### Epic 3: Task Recipe chaining
Users who have already run BMAD or spec-kit to produce a dependency-linked task list can ingest that graph per-Project and watch it execute end-to-end on the board — one task's job completing auto-starts the next dependent task's job — with tracker-write outputs routed through the same approval gate as any other write-back.
**FRs covered:** FR8, FR9, FR10, FR11, UX-DR4

### Epic 4: Chat
Users can open a persistent, purely conversational Chat with zero git footprint to think something through, then launch one or more Jobs from it (Chat stays open) and/or attach it to a Task Recipe chain to narrate progress and optionally gate auto-spawn behind an approval.
**FRs covered:** FR12, NFR8, UX-DR5

### Epic 5: Agent-facing MCP tools
An agent running inside a Job can act mid-run — comment/transition the linked tracker ticket, or proactively request a PR — without ever holding a Credential's decrypted PAT, routed through the same approval gate a human-initiated write already uses.
**FRs covered:** FR13, FR14

## Epic Sections

### Epic 1: Project-based organization

**Goal:** Users can create/edit Projects (single- or multi-repo) and see them organized as an overview + per-Project board.
**FRs:** FR1, FR2, FR3, FR4, FR5, FR6, NFR5, NFR6, UX-DR1, UX-DR2

#### Story 1.1: Create/Edit a Project

As a CodePlane user,
I want to create or edit a Project (one repo or many),
So that adding a repo always happens through Project membership, never a bare registration.

**Acceptance Criteria:**

**Given** no Project exists for a given repo path
**When** I create a new Project and assign it one or more repo paths
**Then** a `ProjectRow` is created with those `repo_paths`, and each repo becomes visible only as a member of that Project
**And** attempting to assign a repo path already belonging to another Project is rejected (NFR5: a repo belongs to at most one explicit Project)

**Given** an existing Project
**When** I edit its name or repo membership (add/remove a repo path)
**Then** the change is saved and reflected immediately on the Overview and that Project's board

**Given** the existing `Job`/`JobSummary` schema and `codeplane_repo` registry
**When** Project creation/editing runs
**Then** neither schema changes structurally, and existing single-board consumers (`KanbanBoard`, `MobileJobList`, `frontend/e2e`) continue to function unmodified (NFR6)

#### Story 1.2: View Projects Overview

As a CodePlane user,
I want to see all my Projects as cards on one overview screen,
So that I can see what exists and what needs attention without navigating into each one.

**Acceptance Criteria:**

**Given** one or more Projects are registered
**When** I load the `/repos` index route
**Then** I see one card per Project, including Projects with zero active jobs (idle Projects still appear)
**And** each card shows active/awaiting/failed counts and last-activity, sourced from a single batch `GET /settings/projects/summary` call — never N sequential per-Project fetches

**Given** a Project with no jobs at all
**When** the Overview loads
**Then** its card renders with zero counts, not omitted from the grid

#### Story 1.3: View a Project's board

As a CodePlane user,
I want to open a Kanban board scoped to just one Project,
So that I only see that Project's jobs, never another Project's noise mixed in.

**Acceptance Criteria:**

**Given** a Project card on the Overview
**When** I click into it
**Then** I land on a board at a child route of the existing `/repos/:repoPath` shell, showing only jobs belonging to that Project's member repo(s)
**And** the board reuses the existing three-column status classifier (In Progress / Awaiting Input / Failed) unmodified

**Given** the URL for a Project's board
**When** I refresh the page or share the link
**Then** the same scoped board loads (state lives in the URL route param, not client-only state)

#### Story 1.4: See cross-Project attention signal

As a CodePlane user managing several Projects,
I want one rolled-up signal for anything needing attention across all Projects,
So that I don't have to open every board to check for problems.

**Acceptance Criteria:**

**Given** two or more Projects, at least one with an awaiting-input or failed job
**When** I view the Overview
**Then** I see a single combined count (awaiting input + failed, summed across all Projects)
**And** the count updates when a job's state changes, sourced from the same batch summary call as Story 1.2 (no second endpoint)

**Given** no Project has any awaiting-input or failed job
**When** I view the Overview
**Then** the attention signal shows zero / is not alarmingly rendered

#### Story 1.5: Filter Projects by name

As a CodePlane user with many Projects,
I want to filter the Overview and sidebar by name,
So that I can find a specific Project quickly as the list grows.

**Acceptance Criteria:**

**Given** a search/filter box on the Projects Overview and the sidebar Project list
**When** I type a partial name match
**Then** only matching Project cards remain visible in both locations
**And** the same filter mechanism is applied generically at the card-rendering layer, so it also filters Task Recipe/TaskLink cards once Epic 3 introduces them (no Epic-1-only special case)

**Given** the filter text matches nothing
**When** I view the filtered list
**Then** an empty state is shown, not an error

### Epic 2: Tracker integration

**Goal:** Users connect a Jira/Azure DevOps/GitHub Projects account once and attach it to any Project; ticket state pulls in via polling, write-backs go through approval.
**FRs:** FR7, NFR1, NFR2, NFR3, NFR9, UX-DR3

#### Story 2.1: Register a Credential

As a CodePlane user,
I want to register a provider account (Jira, Azure DevOps, or GitHub Projects) once,
So that I don't have to re-enter credentials for every Project that needs it.

**Acceptance Criteria:**

**Given** the Settings > Integrations screen
**When** I enter a provider, label, base URL, and PAT
**Then** a `CredentialRow` is created with the PAT encrypted at rest
**And** the PAT is never rendered in plaintext after save, never logged, and never included in any agent-facing job prompt/context (NFR1)

**Given** an existing Credential is referenced by one or more TrackerLinks
**When** I attempt to delete it
**Then** the deletion is blocked until all referencing TrackerLinks are removed

#### Story 2.2: Attach a TrackerLink to a Project

As a CodePlane user,
I want to attach a Credential to a Project via a TrackerLink,
So that my Project's board reflects that Project's ticket state.

**Acceptance Criteria:**

**Given** at least one Credential is registered
**When** I attach it to a Project along with an external project/board reference
**Then** a `TrackerLinkRow` (Project + Credential + external ref) is created
**And** a Project can have more than one TrackerLink (e.g. referencing two external boards)
**And** any number of Projects may attach the same Credential (Credential is global, not consumed per-attachment)

#### Story 2.3: View synced ticket state

As a CodePlane user,
I want to see my linked tracker's ticket/board state inside CodePlane,
So that I don't have to leave CodePlane to check status.

**Acceptance Criteria:**

**Given** a Project with an attached TrackerLink
**When** the poll interval elapses (or I trigger a manual refresh)
**Then** ticket/board state is fetched and rendered, with no inbound webhook endpoint involved at any point (NFR2)

**Given** the configured poll interval
**When** I change it in settings
**Then** subsequent polls honor the new interval

#### Story 2.4: Approve a tracker write-back

As a CodePlane user,
I want any outbound tracker write to require my approval first,
So that nothing is written to an external tracker without my knowledge.

**Acceptance Criteria:**

**Given** a pending outbound write to a linked tracker (comment/transition)
**When** the write is triggered
**Then** it creates a `codeplane_approval` entry using the exact same approval mechanism already used elsewhere in CodePlane — no second, tracker-specific approval flow

**Given** an approval is rejected
**When** I reject it
**Then** the write is discarded and never sent to the external tracker

#### Story 2.5: See per-provider PAT scope guidance

As a CodePlane user registering a Credential,
I want to see the minimal token scope required for my provider,
So that I don't over-grant permissions I don't need.

**Acceptance Criteria:**

**Given** I am registering a GitHub Credential
**When** I view the registration screen
**Then** I see copy-paste guidance for fine-grained PAT scopes (`Issues: Read & write` for tracker writes; `Contents: Read & write` + `Pull requests: Read & write` if PR creation will also be used) (NFR9)

**Given** I am registering a Jira or Azure DevOps Credential
**When** I view the registration screen
**Then** I see guidance stating the token cannot be scoped down further than the full account (Jira API token) or the full organization (Azure DevOps PAT), and that the approval gate — not token scope — is the real security boundary (NFR9)

**Given** any provider's registration screen
**When** I look for an OAuth app connection option
**Then** none exists — PAT-only, confirming NFR3

### Epic 3: Task Recipe chaining

**Goal:** Users populate a Project's task graph (by ingestion or manual ticket-assignment) and watch it execute end-to-end on the board.
**FRs:** FR8, FR9, FR10, FR11, UX-DR4

#### Story 3.1: Widen the Task Recipe vocabulary

As a CodePlane user relying on existing sidecar templates,
I want the recipe schema to support chained, tracker-aware task recipes,
So that new chaining capability is additive and never breaks my existing sidecars.

**Acceptance Criteria:**

**Given** an existing `SidecarTemplateRow` with a pre-existing `lifetime`/`outputRoutes`/`contextSources` value
**When** the schema validation function is updated
**Then** `chained`, `spawn_task`, `tracker_write`, `story_node`, and `tracker_ticket` are accepted as new valid values, and every existing template continues to validate and run unchanged
**And** no new schema table, version flag, or migration is introduced — the same `definition_json` column is reused

#### Story 3.2: Ingest a task graph into a Project

As a CodePlane user who has run BMAD or spec-kit,
I want to ingest my existing dependency-linked task list into a Project,
So that I don't have to hand-author board cards for work already planned.

**Acceptance Criteria:**

**Given** a Project with 2+ member repos, each containing BMAD stories or a spec-kit `tasks.md`
**When** I trigger ingestion for that Project
**Then** one `TaskLink` is created per task, namespaced by `(project_id, repo_path, story_node_id)`, with `depends_on` correctly resolving to a sibling member repo's task when referenced

**Given** ingestion has already run once for a Project
**When** I re-run it
**Then** existing `TaskLink`s are upserted (matched by `project_id`, `repo_path`, `story_node_id`), never duplicated

**Given** the source repo's story/task files
**When** ingestion runs
**Then** the source files are read-only — never modified, and never ingested across a Project boundary

#### Story 3.3: Manually assign a task to an existing ticket

As a CodePlane user with a tracker ticket that has no BMAD/spec-kit backing,
I want to create a task recipe node directly against that ticket with my own prompt,
So that I can automate work the ticket describes without first authoring a planning doc.

**Acceptance Criteria:**

**Given** a Project with an attached TrackerLink showing synced tickets
**When** I pick an existing ticket and create a TaskLink against it with a free-form prompt
**Then** a `TaskLink` is created with `tracker_ticket_ref` and `prompt_override` set, and `story_node_id` left null

**Given** a ticket already has one manually-assigned TaskLink
**When** I create a second TaskLink against the same ticket
**Then** both TaskLinks exist independently (many TaskLinks may share one `tracker_ticket_ref`)

**Given** a manually-assigned TaskLink
**When** I view it later
**Then** nothing requires it to ever gain a `story_node_id` — it remains valid indefinitely without BMAD/spec-kit backing

#### Story 3.4: See TaskLink cards on the board

As a CodePlane user watching a Project board,
I want to see task recipe nodes as cards alongside regular job cards,
So that I can see the whole graph of planned and running work in one place.

**Acceptance Criteria:**

**Given** a Project with TaskLinks created via ingestion (3.2), manual assignment (3.3), or both
**When** I view that Project's board
**Then** every TaskLink renders as a card in the same column grid as job cards, through one client-side rendering pass (not a separate screen)

**Given** a TaskLink whose `depends_on` list has unsatisfied entries
**When** I view the board
**Then** that card renders greyed out with a chained-lifetime badge, distinguishing it from an active job card

**Given** a TaskLink whose dependencies are all satisfied
**When** I view the board
**Then** the card renders in its normal (non-greyed) state, ready to spawn or already linked to a running `job_id`

#### Story 3.5: Auto-spawn the next task on completion

As a CodePlane user running a task chain,
I want the next dependent task to start automatically when its prerequisite completes,
So that I don't have to manually start every step of a planned sequence.

**Acceptance Criteria:**

**Given** a TaskLink's linked Job completes successfully
**When** a dependent TaskLink's remaining dependencies are now all satisfied
**Then** its `spawn_task` output route fires, calling the same job-creation service function used by `codeplane_job create` (same worktree/branch provisioning), and the resulting `job_id` is written onto that TaskLink

**Given** a TaskLink with multiple unsatisfied dependencies
**When** only some of them complete
**Then** `spawn_task` does not fire until every dependency is satisfied

**Given** a TaskLink that already has a `job_id`
**When** its dependencies become satisfied again for any reason
**Then** it is never spawned a second time — one TaskLink points at zero-or-one real Job, never more

#### Story 3.6: Route recipe tracker-writes to the paired ticket

As a CodePlane user running a task chain paired with tracker tickets,
I want a completed task's tracker write to land on the exact ticket it's paired with,
So that status updates never land on the wrong ticket.

**Acceptance Criteria:**

**Given** a TaskLink with a `tracker_ticket_ref` set
**When** its recipe's `tracker_write` output route fires
**Then** it creates a `codeplane_approval` entry (the same mechanism as Epic 2's Story 2.4) targeting that specific ticket, not any other ticket the Project might be linked to

**Given** a TaskLink with no `tracker_ticket_ref` set
**When** its recipe would otherwise route to `tracker_write`
**Then** that action is unavailable for that TaskLink — there is no fallback to a Project-level default ticket

**Given** an approval created by a `tracker_write` output route
**When** it is approved or rejected
**Then** it behaves identically to any other `codeplane_approval` entry — same UI, same resolution path

### Epic 4: Chat

**Goal:** Users can open a persistent, purely conversational Chat with zero git footprint, launch one or more Jobs from it, and/or attach it to a Task Recipe chain to narrate/gate progress.
**FRs:** FR12, NFR8, UX-DR5

#### Story 4.1: Start a Chat

As a CodePlane user,
I want to open a persistent, purely conversational Chat,
So that I can think something through before committing to a real run, with zero git footprint.

**Acceptance Criteria:**

**Given** I start a new Chat from a Project's context (or from global nav)
**When** the Chat is created
**Then** a `ChatRow` is created with `project_id` defaulted accordingly — set to that Project if started from within one, left null if started from global nav — and always user-overridable

**Given** a Chat exists, at any point in its lifetime
**When** I inspect its implementation
**Then** it has zero `GitService` dependency of any kind — no worktree, no branch, no git operation is ever possible from within the conversation itself (NFR8)

**Given** a Chat with `project_id` still null
**When** I later launch a Job or attach it to a chain from that Chat
**Then** `project_id` is settled at that moment, from whichever happens first

#### Story 4.2: Launch a Job from a Chat

As a CodePlane user who has been thinking something through in a Chat,
I want to launch a real Job from that conversation,
So that I can commit to doing the work only once it's worth it, without losing the Chat.

**Acceptance Criteria:**

**Given** an open Chat with a transcript
**When** I launch a Job from it
**Then** a new Job is created, seeded from the Chat's transcript, provisioning its own worktree/branch only at that moment

**Given** a Job has been launched from a Chat
**When** I check the Chat afterward
**Then** the Chat remains open and unchanged — it is never consumed, closed, or transformed into the Job; it is a repeatable action

**Given** an open Chat
**When** I launch a second Job from it later
**Then** a second, independent Job is created — one Chat can launch more than one Job over its lifetime

#### Story 4.3: Attach a Chat to a Task Recipe chain

As a CodePlane user who would rather supervise a chain than let it run unattended,
I want to attach my Chat to a running Task Recipe chain,
So that I can narrate and watch its progress conversationally.

**Acceptance Criteria:**

**Given** an open Chat and an existing TaskLink chain
**When** I attach the Chat to that chain
**Then** the Chat is linked to the chain's `task_link_id`, and if `project_id` was still null it is settled from the chain's Project at this moment

**Given** a Chat attached to a chain
**When** the chain's TaskLink/Job states change
**Then** the Chat's narration reflects that state via read-only polling — it never calls `GitService` or the job-creation function directly on its own

**Given** a Chat attached to a chain
**When** I detach it
**Then** the chain continues to exist and run exactly as before, and the Chat remains open

#### Story 4.4: Gate a chain's auto-spawn behind approval

As a CodePlane user supervising a chain via an attached Chat,
I want the chain's next step to require my approval instead of starting automatically,
So that I stay in control of a chain I'm actively watching.

**Acceptance Criteria:**

**Given** a TaskLink chain with an attached Chat in gating mode
**When** a dependent TaskLink's dependencies become satisfied
**Then** `spawn_task` creates a `codeplane_approval` entry (the same mechanism AD-7/CAP-11 already use) instead of calling the job-creation service directly, and only calls it once that approval is granted

**Given** a TaskLink chain with no attached Chat
**When** a dependent TaskLink's dependencies become satisfied
**Then** the existing ungated auto-spawn behavior (Story 3.5) is completely unchanged — attaching a Chat is what switches a specific chain into gated mode, nothing else does

**Given** a gated chain's approval is rejected
**When** I check the chain afterward
**Then** the next TaskLink is never spawned, and the chain remains stalled at that point until a manual retry or a new approval

### Epic 5: Agent-facing MCP tools

**Goal:** An agent running inside a Job can act mid-run — comment/transition the linked tracker ticket, or proactively request a PR — without ever holding a Credential's decrypted PAT.
**FRs:** FR13, FR14

#### Story 5.1: Agent comments/transitions a tracker ticket mid-job

As a developer running an agent-driven Job,
I want the agent to be able to comment on or transition the linked tracker ticket itself,
So that ticket status stays current without me doing it manually after the fact.

**Acceptance Criteria:**

**Given** an agent running inside a Job whose Project has an attached TrackerLink
**When** the agent calls `codeplane_tracker` (comment or transition)
**Then** CodePlane resolves the Job's Project and TrackerLink(s) server-side and creates a `codeplane_approval` entry via the exact same function CAP-11's recipe-driven `tracker_write` already calls — same approval shape regardless of caller

**Given** the agent calls `codeplane_tracker`
**When** the call executes
**Then** the agent never receives or handles the Credential's decrypted PAT at any point — CodePlane resolves and uses it server-side on the agent's behalf

**Given** a `codeplane_tracker`-created approval is rejected
**When** I check the ticket afterward
**Then** no write reaches the external tracker

#### Story 5.2: Agent requests a PR mid-job

As a developer running an agent-driven Job,
I want the agent to be able to proactively request a PR while still working,
So that a PR can go up before the Job's automatic completion-time step, if that's useful for my workflow.

**Acceptance Criteria:**

**Given** an agent running inside a Job
**When** it calls `codeplane_pr`
**Then** CodePlane creates a PR using the exact same `_create_pr` implementation the automatic completion-time path already uses — one implementation, two callers

**Given** the agent has already called `codeplane_pr` successfully for its Job
**When** the Job later completes and the automatic completion-time PR path would normally fire
**Then** no duplicate PR is created — the existing PR is returned/reused (idempotent per Job)

**Given** the agent calls `codeplane_pr` a second time before the Job completes
**When** a PR already exists for that Job
**Then** the existing PR is returned, not a second one created
