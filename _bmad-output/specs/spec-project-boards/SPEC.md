---
id: SPEC-project-boards
companions: ["ui-flows.md", "architecture/ARCHITECTURE-SPINE.md"]
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate.

# Multi-Project Boards & Task Recipes for CodePlane

## Why

CodePlane's dashboard pools every job from every registered repo into one flat Kanban (`KanbanBoard.tsx`: In Progress / Awaiting Input / Failed). This is a pain to solve: as soon as a user works across more than one or two repos, the board becomes a "salad" where signal from one project drowns in noise from another, and there is no way to see "what needs my attention in repo X" without mentally filtering a shared list. Notably, the GitHub Copilot app - the very product used to design this spec - already organizes sessions per-project rather than pooling them flat, which is itself the pattern this spec is proposing CodePlane adopt.

A brownfield architecture pass (see `ARCHITECTURE-SPINE.md` companion) found that CodePlane already has a `/repos/:repoPath/*` shell (`RepoLayout` + `RepoOverview`/`RepoJobs`/`RepoHealth`/`RepoCost`/`RepoSettings`) and a `GET /settings/repos/{repo}/summary` endpoint. CAP-1-4's board/overview capabilities extend that existing shell rather than duplicate a second repo-navigation surface inside `DashboardScreen`.

A second, materially larger gap surfaced during design review: the repo registry has no grouping concept above a single repo path, and real usage often ties multiple repos to one external tracker project (a Jira project, an Azure DevOps project, a GitHub Project spanning repos), or vice versa. CAP-5/CAP-6/CAP-7 introduce **Project** as a first-class entity: a named collection of one or more repos plus optional external tracker links, with bidirectional sync (pull ticket/board state in, write status/comments back out under approval). This is no longer a pure read/navigation-layer change - it adds new entities, encrypted credential storage, and a poll-based sync engine - and it changes the add-flow itself: there is no standalone "register a repo" action anymore. Every add action creates a Project - either a single-repo Project (the common case, replacing what used to be a bare repo registration) or a multi-repo one - so a repo is never in the registry without also being a Project's member. Integration auth is scoped globally, not per-Project: a **Credential** (one PAT per provider account) is registered once in a global Settings > Integrations screen, and any number of Projects attach a **TrackerLink** (Project + Credential + external project/board reference) to it - matching how one Jira or Azure DevOps account is realistically shared across many Projects, and letting a single Project reference more than one external tracker at once.

A third thread, researched separately (`cline/kanban`, GitHub spec-kit, and CodePlane's own installed BMAD methodology) converged on one more gap: task dependency graphs produced by structured planning (BMAD stories, spec-kit `tasks.md`) are inert documents today - a human or agent works through them file by file, and spec-kit's own answer to "then what" is shipping the list out to a static GitHub Issues tracker. `cline/kanban` proved that rendering a task graph as a *live, executable* board (own worktree per card, auto-start-next-on-completion) is a real, validated UX win, but it solved this only within a single repo, with nothing upstream deciding what the graph should be - confirming the Project layer above is genuinely uncontested ground, not a catch-up feature. CodePlane already has most of the right primitive for the chaining half: `SidecarTemplateRow.definition_json` is already a declarative `trigger → context → agent → output` recipe, just hardwired to mean "helper inside one job's lifetime." CAP-8-11 generalize that existing schema - rather than building three separate systems for sidecars, inter-job chaining, and BMAD/spec-kit ingestion - into **Task Recipes**, additive and backward-compatible with every existing sidecar template.

A fourth thread closes a gap the first three left open: every unit of work in CodePlane today is a `Job` - which always means a worktree and a branch, provisioned up front, even for existing "plan mode" runs (verified: `test_plan_mode_flow.py` still sets `worktree_path` before any planning happens). There is no lighter-weight, purely conversational unit for "let me think this through before committing to a real run," the way the GitHub Copilot app has plain chats distinct from full sessions, and separately no way to supervise a `cline/kanban`-style chain the way a person actively watches a board card-by-card. CAP-12 introduces a single **Chat** entity that covers both: no worktree, no branch, no git operations at all in the conversation itself, `project_id` nullable and settled only when it's actually needed. A Chat is never "promoted" or transformed into anything - it persists, and from within it a user can launch one or more Jobs directly (each provisioning its own worktree only at that moment) and/or attach it to a Task Recipe chain to narrate progress and optionally hold CAP-10's auto-spawn behind an approval. A Project with no Chats behaves exactly as CAP-1-11 already describe.

Since this spec has no installed users to preserve compatibility for, it is designed for its ideal shape rather than a migration path: the existing flat, cross-repo `DashboardScreen`/`KanbanBoard` is retired outright rather than kept alongside the new Project-organized `/repos` entry point, and no synthetic "default/All Projects" catch-all entity is introduced - the Projects Overview grid, with CAP-3's rolled-up cross-project attention count, is already the all-up glance.

## Capabilities

- **CAP-1**
  - **intent:** User can scope a Kanban board to a single repo, as a new child route of the existing `/repos/:repoPath` shell (e.g. `/repos/:repoPath/board`), so each repo gets its own In Progress / Awaiting Input / Failed board without a second repo-navigation UI.
  - **success:** Navigating to a repo's board tab shows only that repo's jobs in all three columns; the URL itself (via the existing `:repoPath` param) identifies the repo, so it survives a refresh and is shareable.

- **CAP-2**
  - **intent:** User can view a projects overview at the bare `/repos` index route (replacing today's silent auto-redirect to the first repo) with one card per Project, showing active/awaiting/failed counts and last-activity time, and drill into that Project's board (CAP-1) from the card.
  - **success:** Landing on `/repos` with no path shows the overview grid instead of redirecting; clicking a card navigates to that repo's CAP-1 board; the counts shown on the card match the underlying job list for that repo.

- **CAP-3**
  - **intent:** User can see a single rolled-up "needs attention" signal (awaiting input + failed, across all repos) on the overview screen without opening any individual board.
  - **success:** A single number or badge showing total cross-repo attention count is visible on the overview screen before drill-in.

- **CAP-4**
  - **intent:** The set of boards/cards shown is driven by the Project registry (`codeplane_project` list), not only Projects that currently have jobs, so a newly created but idle Project is still represented.
  - **success:** Creating a new Project with zero jobs immediately shows an empty board (CAP-1) and an empty-state card (CAP-2).

- **CAP-5**
  - **intent:** User can filter the Projects Overview card grid and the sidebar Project list by name via a text filter, so managing 3+ projects doesn't require scanning the whole set. The filter operates on card identity generically at the board-rendering layer, so it applies uniformly to every card type a board or overview renders - both CAP-2 Project cards and CAP-10 TaskLink cards - with no separate filtering logic per card type.
  - **success:** Typing in the filter box narrows visible cards/sidebar entries to name matches in real time, across both Project cards and any TaskLink cards on a board; clearing it restores the full set.

- **CAP-6**
  - **intent:** Adding a repo is done exclusively by creating or editing a Project - there is no standalone "register a repo" action. Creating a Project takes a name and one or more repo paths (cloning/registering each, reusing the existing clone/register logic) up front; a single-repo Project is the common case and looks like today's per-repo card, but is always backed by a real `ProjectRow`, never a bare repo entry read at display time. An existing Project's membership can be edited later to add or remove repos.
  - **success:** There is no UI path or endpoint that creates a repo without also creating or attaching it to a `ProjectRow`; creating a Project with 2+ member repos shows one card/board (CAP-1/CAP-2) combining those repos' jobs; a repo can belong to at most one Project (enforced, prevents double-counting).

- **CAP-7**
  - **intent:** User registers a **Credential** (provider, label, base URL, encrypted PAT) once in a global Settings > Integrations screen, independent of any Project. User can then attach a **TrackerLink** (references one Credential plus an external project/board identifier, e.g. a Jira project key or GitHub Project number) to any Project. CodePlane polls each Project's TrackerLinks in for display; write-backs are routed through the existing `codeplane_approval` flow, never applied automatically.
  - **success:** A Credential registered once can be referenced by TrackerLinks on multiple different Projects without re-entering the PAT; a Project can hold more than one TrackerLink (e.g. a Jira link and a GitHub Projects link simultaneously) and shows combined live ticket counts/state on a configurable poll interval; a job completion that would update an external ticket creates an approval request instead of writing directly; deleting a Credential is blocked while any TrackerLink still references it.

- **CAP-8**
  - **intent:** Widen the existing sidecar-template recipe vocabulary (`phase`/`lifetime`/`scope`/`triggers[].contextSources`/`triggers[].outputRoutes`) with `lifetime: chained` (spans multiple jobs), new `outputRoutes` (`spawn_task`, `tracker_write`), and new `contextSources` (`story_node`, `tracker_ticket`).
  - **success:** Every existing sidecar template continues to validate and run unchanged; a new template using `lifetime: chained` and `outputRoutes: [spawn_task]` validates and is creatable through the existing template CRUD surface.

- **CAP-9**
  - **intent:** Ingest BMAD stories or spec-kit `tasks.md` (including documented `depends_on` relationships) for an entire Project - once per Project, iterating every member repo in `project.repo_paths` - into thin `TaskLink` rows (`project_id`, `repo_path`, `story_node_id`, `depends_on: list[story_node_id]`, `job_id: nullable`), read-only against every source repo, never duplicating or taking ownership of them. `depends_on` may reference a `story_node_id` in a different member repo of the same Project, so a multi-repo Project's task graph can express real cross-repo dependencies (e.g. a frontend task depending on a backend task in a sibling repo).
  - **success:** Running ingestion against a Project with 2+ member repos, each with a `tasks.md`, produces one `TaskLink` per task, correctly namespaced by `repo_path` (since `story_node_id` is only unique within one repo), with `depends_on` edges resolving correctly whether the dependency is in the same repo or a sibling member repo; re-running upserts by `(project_id, repo_path, story_node_id)` rather than creating duplicates; ingestion never reads or writes across a Project boundary.

- **CAP-10**
  - **intent:** Render `TaskLink` nodes with satisfied dependencies as cards on the CAP-1 Project board; completing a linked job auto-spawns the next dependent `TaskLink`'s job via its recipe's `spawn_task` output route, each in its own worktree, Cline-style.
  - **success:** Completing the job behind a `TaskLink` whose dependents have all other dependencies satisfied automatically creates and starts the next job, visible as a new card, with no manual step.

- **CAP-11**
  - **intent:** Any recipe output routed to `tracker_write` reuses CAP-7 exactly - it creates a `codeplane_approval` entry, never applies directly. No second, recipe-specific approval mechanism.
  - **success:** A `chained` recipe configured with a `tracker_write` output route never calls an external tracker's write endpoint directly; an approval entry appears instead, identical in shape to any other pending approval.

- **CAP-12**
  - **intent:** User can start a Chat - a persistent, purely conversational session with no worktree, no branch, and no git operations of any kind, optionally given read-only repo context via the existing workspace read tools. `project_id` is nullable: creation defaults to the Project of the board it was opened from, or unscoped if opened from the global nav, always user-overridable at creation time. A Chat is never consumed or transformed - from within it, the user can (a) launch one or more Jobs directly (each a normal Job with its own worktree/branch, seeded from the chat transcript, the Chat itself remaining open afterward), and/or (b) attach the Chat to a Project's Task Recipe chain to narrate its progress and optionally gate CAP-10's auto-spawn step behind an approval. Whichever of these an unscoped Chat does first is what settles its Project - resolved at that moment via a prompt, not required upfront.
  - **success:** Starting a Chat never touches `GitService` and never creates a `JobRow`. Launching a Job from a Chat creates a new Job with a fresh worktree/branch and an initial prompt derived from the chat transcript, while the Chat itself remains open and can launch further Jobs later. A chain with no Chat attached keeps CAP-10's default ungated auto-spawn behavior unchanged; a chain with a Chat attached and gated creates an approval entry instead of auto-spawning when a TaskLink's dependencies become satisfied, and spawns only once that approval is granted. A Chat that never launches a Job or attaches to a chain can be abandoned with zero git-visible trace.

## Constraints

- Must not change the `Job`/`JobSummary` schema or break existing single-board consumers (`KanbanBoard`, `MobileJobList`, and the `frontend/e2e` suite) during rollout.
- Must reuse existing store selectors and patterns (`selectActiveJobs`, `selectSignoffJobs`, `selectAttentionJobs`, `useShallow`) rather than introducing a parallel state model.
- Repo summary counts for CAP-2/CAP-3 must be computable from data already fetched by `DashboardScreen` (`fetchJobs`) or a small additive aggregate; this must not require a new heavy backend service.
- Project is additive: a new `ProjectRow` (id, name, `repo_paths: list[str]`) is introduced; existing `Job.repo`/`branch`/`pr_url` fields and the `codeplane_repo` registry are untouched. A repo may belong to at most one explicit Project (enforced) to avoid double-counting job totals across overlapping projects.
- Integration auth is global, not embedded in `ProjectRow`: a new `CredentialRow` (id, provider, label, base_url, encrypted secret) is managed from a Settings > Integrations screen, and a new `TrackerLinkRow` (id, project_id, credential_id, external_ref) is the many-to-many join between Projects and Credentials. Deleting a `CredentialRow` is blocked while any `TrackerLinkRow` references it.
- External tracker PATs are encrypted at rest in CodePlane's local DB (never plaintext config, never logged, never included in job prompts/context sent to the coding agent).
- Sync is poll-based only (no inbound webhooks - CodePlane has no public endpoint), with a configurable interval and a manual refresh action.
- All external tracker write-backs (ticket transitions, comments) go through the existing `codeplane_approval` flow; only inbound polling/reads are unapproved.
- No OAuth app registrations or maintainer-hosted redirect infrastructure for any provider - auth is locally-stored PATs only, for all three initial providers (GitHub Projects, Jira, Azure DevOps), including on-prem Azure DevOps Server which has no OAuth support at all.
- Task Recipes are backward compatible: existing `SidecarTemplateRow` rows, the existing validation function, and the existing template CRUD surface are extended in place, not replaced or duplicated.
- No new atomic-run entity for recipes/chaining: `TaskLink` is a thin correlation row (story/task node to zero-or-one `JobRow`), not a parallel execution model competing with `Job`.
- Ingestion (CAP-9) is Project-scoped (iterates every member repo of a Project) and read-only against source `tasks.md`/story files - CodePlane never rewrites or takes ownership of BMAD's or spec-kit's own artifacts, and never ingests across a Project boundary.
- MCP surface: a new `codeplane_project` tool (list/get/create/update/assign-repos/attach-tracker-link/ingest-tasks) replaces bare repo registration as the add-path; `create`/`update` are where a repo path is cloned/registered (reusing the existing clone/register logic), always as part of a Project. `codeplane_repo` narrows to read-only operations (list/get) reflecting Project membership; its `register`/`remove` actions are retired since a repo is never added or removed independent of a Project. `codeplane_job` is unchanged - job creation stays repo-scoped, a Job always targets exactly one repo; Project is a read/organization layer above Job, never a job-creation parameter.
- Removing a repo from a Project (or deleting a single-repo Project) reuses `unregister_repo`'s existing logic, gated the same way today's guard would be: blocked while the repo has active jobs (must be reassigned/cancelled first) - there is no separate bare-repo deletion path to guard, since removal always happens through Project membership editing.
- `PlatformConfig.repos` (existing per-platform auth binding) is explicitly out of scope and orthogonal to `ProjectRow` - it is never read, written, or conflated by any Project capability.
- Analytics/cost/health (`analytics.py`'s `cost_by_repo`, `RepoHealth`, `RepoCost`) remain repo-keyed as the source of truth; any Project-level rollup is computed by summing the existing per-repo values for a Project's member repos client-side or in a thin aggregate, never a second parallel cost/health pipeline.
- The existing flat cross-repo `DashboardScreen`/`KanbanBoard` is retired outright, not kept alongside the new `/repos` Projects Overview - there is no legacy install base to preserve, and having two ways to view the same job list is not the target design. `/repos` (Overview + per-Project board) is the single entry point.
- No synthetic "default/All Projects" entity is introduced - the Projects Overview grid plus CAP-3's rolled-up cross-project attention count already serves as the all-up glance; a catch-all Project would be a redundant second way to see the same data.
- CAP-12 Chat never provisions git state (no `GitService` call of any kind) - not even once it launches a Job, since launching creates a distinct new `JobRow`/worktree rather than mutating the Chat itself; the isolation between "just talking" and "an actual worktree exists" is absolute, not best-effort, and there is no "promotion" transform - the Chat persists after launching a Job.
- CAP-12's `project_id` is nullable: default is context-driven at creation (inside a Project board -> that Project; from global nav -> unscoped), always user-overridable, and settled automatically the first time the Chat launches a Job into a repo or attaches to gate a specific chain, whichever comes first.
- CAP-12's chain-gating is opt-in per chain: a `TaskLink` chain with no attached Chat keeps CAP-10's existing ungated auto-spawn-on-completion behavior unchanged; attaching a Chat to a chain (in gating mode) is what switches that one chain to gated.

## Non-goals

- Any change to job execution, worktree management, or the underlying job state machine.
- Automatic (non-approved) write-backs to any external tracker.
- OAuth-based authentication to external trackers.
- A new UI for editing BMAD stories or spec-kit `tasks.md` content - CodePlane visualizes and executes against them, it does not become a spec/story editor.
- Chat (CAP-12) becoming a second execution engine - a Chat is never git-capable itself; only a Job it launches is, and the Chat remains a distinct, ongoing entity rather than being consumed by that launch.
- A synthetic "default/All Projects" entity, and any effort to keep the old flat `DashboardScreen`/`KanbanBoard` view alive alongside the new one.

## Success signal

- A user managing 3+ Projects can, within one click from app load, see which specific project(s) need attention (CAP-3), and within one more click reach a board scoped to just that project's jobs (CAP-2 → CAP-1) - without ever seeing another project's jobs mixed into the list. A user connecting a Project to Jira/AzDO/GitHub Projects sees that project's ticket state without leaving CodePlane, and any write-back is visible as a normal approval request before it takes effect. A user who has already run BMAD or spec-kit to produce a dependency-linked task list can, without hand-authoring any board cards, see that task graph rendered live on a Project board and watch it execute end-to-end - one task's job completing auto-starts the next dependent task's job. A user unsure whether something is even worth a full run can open a Chat, work through it conversationally with zero git footprint, and launch a Job from it only once it's worth doing, without the Chat itself disappearing - and if they'd rather supervise a chain than let it run unattended, that same Chat can attach to it and turn CAP-10's auto-spawn into an approve-each-step flow instead.

## Assumptions

- Job counts per repo are cheap to compute client-side from the already-fetched job list at current job volumes; a dedicated backend aggregate endpoint is an optional optimization, not a hard requirement of this spec.
- BMAD stories and spec-kit `tasks.md` both expose a parseable dependency relationship (explicit `depends_on`/prerequisite reference) sufficient to build `TaskLink.depends_on` without requiring a new annotation convention from either tool.

## Constraints (resolved decisions folded in)

- Selected repo state for CAP-1 lives in the URL (React Router `:repoPath` param of the existing `/repos/:repoPath` shell), not client-only state or a new query-string convention, so boards are shareable and survive refresh.
- CAP-2 Projects Overview is always shown as the `/repos` landing route, including for users with only one Project; it is never skipped.
- `GET /settings/repos/{repo}/summary` gains `awaitingInputCount` and `failedCount` (additive to the existing `activeJobCount`); a new batch `GET /settings/repos/summary` returns the same extended shape for all registered repos in one call, so CAP-2/CAP-3 never do N sequential per-repo fetches.
- `RepoJobs.tsx` (the existing analytics job table) is left untouched; CAP-1's board is a separate new component, not a retrofit of that table.
- External tracker integration (CAP-7) supports GitHub Projects, Jira, and Azure DevOps at launch as the initial provider set; each is a display-and-sync source, not merely a link.

