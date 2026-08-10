---
stepsCompleted: [1, 2, 3, 4, 5]
---

# Implementation Readiness Assessment Report

**Date:** 2026-08-10
**Project:** codeplane

## Document Inventory

- **PRD (adopted via bmad-spec):** `_bmad-output/specs/spec-project-boards/SPEC.md`
- **Architecture:** `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md`
- **UX (spec-authored companion):** `_bmad-output/specs/spec-project-boards/ui-flows.md`
- **Epics & Stories:** `_bmad-output/planning-artifacts/epics.md`

No duplicate document formats found. No missing document types once the corrected `bmad-spec`/`bmad-architecture` output paths were used (see `.memlog.md` correction entry in `spec-project-boards/` dated 2026-08-10).

## PRD Analysis

SPEC.md (the PRD-equivalent, produced by `bmad-spec` rather than `bmad-prd`) does not use FR/NFR labels natively — it uses `CAP-N` capabilities and prose `Constraints`. The extraction below maps every CAP-N and load-bearing Constraint to a numbered FR/NFR, verified against a complete read of SPEC.md's Capabilities, Constraints, and Non-goals sections (lines 25-117).

### Functional Requirements

FR1: User can scope a Kanban board to a single repo/Project as a child route of the existing `/repos/:repoPath` shell. (CAP-1)
FR2: User can view a Projects Overview at the bare `/repos` index route with one card per Project (active/awaiting/failed counts, last-activity), drilling into that Project's board. (CAP-2)
FR3: User can see a single rolled-up "needs attention" (awaiting input + failed, cross-Project) signal on the overview screen. (CAP-3)
FR4: The set of boards/cards shown is driven by the Project registry, not only Projects with active jobs, so an idle Project still appears. (CAP-4)
FR5: User can filter the Projects Overview grid and sidebar Project list by name, applied generically at the card-rendering layer so it covers both Project cards and TaskLink cards. (CAP-5)
FR6: Adding a repo is done exclusively by creating or editing a Project; there is no standalone "register a repo" action. A single-repo Project is the common case; membership can be edited later. (CAP-6)
FR7: User registers a Credential (provider, label, base URL, encrypted PAT) once, globally, in Settings > Integrations. User attaches a TrackerLink (Credential + external project/board ref) to any Project; inbound sync polls and renders; outbound writes route through approval. (CAP-7)
FR8: The sidecar-template recipe vocabulary is widened with `lifetime: chained`, and new `outputRoutes` (`spawn_task`, `tracker_write`) and `contextSources` (`story_node`, `tracker_ticket`). (CAP-8)
FR9: BMAD stories / spec-kit `tasks.md` can be ingested per-Project (iterating every member repo) into `TaskLink` rows with cross-repo `depends_on` support within one Project, read-only against source repos. Alternatively, a `TaskLink` can be created manually and assigned directly to an existing tracker ticket (visible via CAP-7's TrackerLink) with a free-form prompt, independent of any BMAD/spec-kit source. Either creation path may optionally be paired with the other's field (`story_node_id` / `tracker_ticket_ref`) after the fact; neither path requires the other. Ingested TaskLinks additionally capture `epic_id` when the source BMAD story has identifiable Epic membership (cosmetic board-label data only). (CAP-9)
FR10: TaskLink nodes with satisfied dependencies render as cards on the Project board; completing a linked job auto-spawns the next dependent TaskLink's job via `spawn_task`. (CAP-10)
FR11: Any recipe output routed to `tracker_write` reuses the existing `codeplane_approval` flow; no second, recipe-specific approval mechanism. The write targets the firing `TaskLink`'s own `tracker_ticket_ref` when set; a `TaskLink` with none has no `tracker_write` action available — never a fallback to an ambiguous Project-level default ticket. (CAP-11)
FR12: User can start a Chat: a persistent, purely conversational session with no worktree/branch/git operations, nullable `project_id` (context-default, user-overridable). From a Chat, the user can launch one or more Jobs (each with its own worktree/branch, seeded from the transcript, Chat remains open) and/or attach the Chat to a Project's Task Recipe chain to narrate progress and optionally gate auto-spawn behind an approval. When attached to a chain, the Chat's card is labeled with a specific Epic only if every TaskLink in that chain shares the same non-null `epic_id`; otherwise it renders generically as "chain." (CAP-12)
FR13: Agent running inside a Job can call a new `codeplane_tracker` MCP tool (comment, transition) to act on the linked tracker ticket; every call routes through the existing `codeplane_approval` gate (same shape as recipe-driven writes), and the agent never handles the Credential's PAT directly. (CAP-13)
FR14: Agent running inside a Job can call a new `codeplane_pr` MCP tool to proactively request a PR mid-job, sharing the same `_create_pr` implementation as the existing automatic completion-time PR creation; idempotent per Job (no duplicate PRs). (CAP-14)

Total FRs: 14

### Non-Functional Requirements

NFR1: External tracker PATs are encrypted at rest, never plaintext-logged, never included in agent-facing job prompts/context. (CAP-7 / Constraints)
NFR2: Tracker sync is poll-based only (configurable interval + manual refresh) — no inbound webhooks, since CodePlane has no public endpoint. (CAP-7 / Constraints)
NFR3: No OAuth app registrations for any tracker provider (GitHub Projects, Jira, Azure DevOps incl. on-prem Server) — locally-stored PATs only. (CAP-7 / Constraints, Non-goals)
NFR4: Overview data must be fetchable in one batch call, never N per-Project calls. (Constraints)
NFR5: A repo may belong to at most one explicit Project (enforced), to prevent double-counting job totals across overlapping Projects. (Constraints)
NFR6: Existing `Job`/`JobSummary` schema and single-board consumers (`KanbanBoard`, `MobileJobList`, `frontend/e2e`) must not break during rollout. (Constraints)
NFR7: Analytics/cost/health stay repo-keyed as source of truth; any Project-level number is a client-side or thin-aggregate sum, never a second pipeline. (Constraints)
NFR8: Chat is never git-capable itself (no `GitService` call of any kind, ever) — isolation between "just talking" and "a worktree exists" is absolute, not best-effort. (Constraints)
NFR9: PAT scope requirements are per-provider and must be documented + surfaced at Credential-creation time as copy-paste guidance only. GitHub fine-grained PATs are scopable per-repo; Jira API-token auth has no granular scope (inherits full account permissions); Azure DevOps PATs are org-scoped not project-scoped. For Jira/AzDO the `codeplane_approval` write-back gate is the real security boundary, not token scope. (Constraints)

Total NFRs: 9

### Additional Requirements

- New `ProjectRow` (id, name, `repo_paths: list[str]`) as the sole repo-membership entity; existing `Job.repo`/`branch`/`pr_url` and `codeplane_repo` registry untouched structurally but narrowed to read-only.
- `GET /settings/projects/summary` batch endpoint, extending `RepoSummaryResponse` with `awaitingInputCount`/`failedCount` alongside existing `activeJobCount`.
- New `CredentialRow` (id, provider, label, base_url, encrypted secret) and `TrackerLinkRow` (id, project_id, credential_id, external_ref) as the many-to-many join; deleting a Credential blocked while referenced.
- `tracker_adapter.py` interface plus GitHub Projects/Jira/Azure DevOps adapters, PAT-only.
- `TaskLinkRow` (project_id, repo_path, story_node_id: nullable, depends_on[], job_id: nullable, tracker_ticket_ref: nullable, prompt_override: nullable, epic_id: nullable) as a thin correlation row, not a parallel execution model; exactly one of `story_node_id`/`tracker_ticket_ref` guaranteed non-null at creation.
- `ChatRow` (id, project_id nullable, title, created_at, last_message_at, status), owned by `chat_service.py` with zero `GitService` dependency.
- MCP surface: `codeplane_project` is the sole add-path; `codeplane_repo` narrows to read-only; `codeplane_job` unchanged. `codeplane_tracker` (CAP-13) and `codeplane_pr` (CAP-14) additive, agent-facing.
- The existing flat `DashboardScreen`/`KanbanBoard` is retired outright; `/repos` is the single entry point. No synthetic "default/All Projects" entity.

### PRD Completeness Assessment

SPEC.md is complete and internally consistent for its 14 capabilities: every Capability has both an `intent` and a `success` criterion, every Constraint traces to a specific CAP-N or is a standalone cross-cutting rule, and Non-goals explicitly bound scope (no OAuth, no job-execution changes, no BMAD/spec-kit editor, no Chat-as-execution-engine, no default-Project catch-all). Two genuine design gaps surfaced and were resolved mid-workflow (CAP-9's TaskLink/TrackerLink coupling; CAP-9/CAP-12's Epic-labeling) and are reflected in the current text, not left as open items. No unresolved `assumptions[]`/`open_questions[]` remain unaddressed.

## Epic Coverage Validation

### Coverage Matrix

| Requirement | PRD Requirement (summary) | Epic Coverage | Status |
| --- | --- | --- | --- |
| FR1 | Board scoped to one repo/Project | Epic 1, Story 1.3 | ✓ Covered |
| FR2 | Projects Overview at `/repos` index | Epic 1, Story 1.2 | ✓ Covered |
| FR3 | Rolled-up cross-Project attention signal | Epic 1, Story 1.4 | ✓ Covered |
| FR4 | Idle Projects still appear | Epic 1, Story 1.2/1.4 | ✓ Covered |
| FR5 | Name filter, generic across card types | Epic 1, Story 1.5 | ✓ Covered |
| FR6 | Adding a repo only via Project create/edit | Epic 1, Story 1.1 | ✓ Covered |
| FR7 | Global Credential + per-Project TrackerLink, poll sync, approval write-back | Epic 2, Stories 2.1-2.4 | ✓ Covered |
| FR8 | Recipe vocabulary widened (`chained`, `spawn_task`, `tracker_write`, `story_node`, `tracker_ticket`) | Epic 3, Story 3.1 | ✓ Covered |
| FR9 | Dual TaskLink creation (ingest / manual-assign-to-ticket), cross-repo `depends_on`, optional `epic_id` | Epic 3, Stories 3.2/3.3 | ✓ Covered |
| FR10 | TaskLink cards render, auto-spawn on completion | Epic 3, Stories 3.4/3.5 | ✓ Covered |
| FR11 | `tracker_write` reuses approval flow, targets paired ticket only | Epic 3, Story 3.6 | ✓ Covered |
| FR12 | Chat entity, launch Job / attach chain, conditional Epic-label | Epic 4, Stories 4.1-4.3 | ✓ Covered |
| FR13 | `codeplane_tracker` MCP tool, approval-gated | Epic 5, Story 5.1 | ✓ Covered |
| FR14 | `codeplane_pr` MCP tool, idempotent, shared `_create_pr` | Epic 5, Story 5.2 | ✓ Covered |
| NFR1 | PAT encrypted at rest, never logged/in-prompt | Epic 2, Story 2.1 | ✓ Covered |
| NFR2 | Poll-based sync only, no webhooks | Epic 2, Story 2.3 | ✓ Covered |
| NFR3 | No OAuth, PAT-only for all 3 providers | Epic 2, Story 2.5 | ✓ Covered |
| NFR4 | Single batch call, never N per-Project fetches | Epic 1, Stories 1.2/1.4 | ✓ Covered |
| NFR5 | A repo belongs to at most one Project | Epic 1, Story 1.1 | ✓ Covered |
| NFR6 | Existing Job schema / single-board consumers unbroken | Epic 1, Story 1.1 | ✓ Covered |
| NFR7 | Analytics/cost/health stay repo-keyed, thin aggregate only | Cross-cutting (no dedicated story; constraint on implementation, not a user-facing capability) | ⚠ Constraint-only, not story-traced |
| NFR8 | Chat has zero `GitService` dependency | Epic 4, Story 4.1 | ✓ Covered |
| NFR9 | Per-provider PAT scope guidance surfaced at Credential-creation | Epic 2, Story 2.5 | ✓ Covered |

### Missing Requirements

No FRs are missing coverage — all 14 trace to a specific story with matching acceptance criteria.

One NFR (NFR7) is a standing implementation constraint ("never build a second cost/health pipeline") rather than a user-facing behavior with its own acceptance criterion — this is expected for a constraint of this shape (there is nothing to demo; it's a prohibition on the implementer, verifiable only by code review, not a testable user-facing story). Not a gap requiring a new story.

### Coverage Statistics

- Total PRD FRs: 14
- FRs covered in epics: 14
- FR coverage percentage: 100%
- Total PRD NFRs: 9
- NFRs covered in epics: 8 (verifiable via story AC), 1 (NFR7) as a cross-cutting implementation constraint with no dedicated AC (expected, not a gap)

## UX Alignment Assessment

### UX Document Status

Found: `ui-flows.md` (spec-authored companion to SPEC.md).

### Alignment Issues

None. All 5 UX Design Requirements (UX-DR1-5) map to a named component and are architecturally traced:

| UX-DR | Component | Architecture trace |
| --- | --- | --- |
| UX-DR1 (CAP-1 board) | `RepoBoard.tsx` | AD-1, AD-2, AD-5 |
| UX-DR2 (CAP-2/3/4/5 overview) | `ProjectsOverview.tsx` | AD-3, AD-4, AD-5 |
| UX-DR3 (CAP-7 integrations) | `IntegrationsSettings.tsx`, `ProjectSettings.tsx` | AD-6, AD-7 |
| UX-DR4 (CAP-10 TaskLink cards) | `RepoBoard.tsx` (shared grid) | AD-10, AD-11 |
| UX-DR5 (CAP-12 Chat) | `ChatPanel.tsx` | AD-12 |

Every UX-referenced route (`/repos/:repoPath/board`, `/repos` index, `/repos/:project/chats`) matches a route named in the Architecture Spine's file-tree/routing sections. No UI component is implied by ui-flows.md without a backing architectural rule.

### Warnings

None.

## Epic Quality Review

Applied `create-epics-and-stories`-standard checks rigorously against all 5 epics / 23 stories.

### Epic Structure Validation

| Epic | User-value title? | Independent of later epics? |
| --- | --- | --- |
| 1: Project-based organization | ✓ (no technical-milestone naming) | ✓ standalone |
| 2: Tracker integration | ✓ | ✓ uses only Epic 1 output (Project) |
| 3: Task Recipe chaining | ✓ | ✓ uses Epic 1/2 output only (Project, TrackerLink) — backward, permitted |
| 4: Chat | ✓ | ✓ uses Epic 1/3 output only (Project, TaskLink chain) — backward, permitted |
| 5: Agent-facing MCP tools | ✓ | ✓ uses Epic 1/2 output only (Project, TrackerLink) — backward, permitted |

No technical-milestone epics found (no "Database Setup," "API Development," or similar). No epic requires a later epic to function — every cross-epic reference (Epic 3→2, Epic 4→1/3, Epic 5→1/2) points strictly backward.

### Story Quality Assessment

All 23 stories use consistent As-a/I-want/So-that framing with Given/When/Then ACs; all are independently completable within their own epic without referencing a later story's output. Database/entity creation is deferred to first need in every case: `ProjectRow` (1.1), `CredentialRow`/`TrackerLinkRow` (2.1/2.2), no new table for the recipe vocabulary widening (3.1, reuses `SidecarTemplateRow.definition_json`), `TaskLinkRow` (3.2/3.3), `ChatRow` (4.1).

**🟡 Minor Concern:** Story 1.5's second AC bullet ("the same filter mechanism is applied generically... so it also filters Task Recipe/TaskLink cards once Epic 3 introduces them") references Epic 3, which doesn't exist yet at Epic-1 implementation time. This isn't a blocking forward *dependency* (Story 1.5 is fully completable and shippable using only Project cards), but that specific bullet isn't independently testable until Epic 3's TaskLink cards exist — a strict reading of "Testable: each AC can be verified independently?" flags it. **Recommendation:** reword as an implementation note ("the filter must be implemented generically at the card-rendering layer, not Project-card-specific, to avoid rework in Epic 3") rather than a testable AC, or defer verification of that specific bullet to Epic 3, Story 3.4's own ACs.

No other violations found: no forward within-epic dependencies, no vague/non-measurable ACs, no missing error-path coverage (rejection/deletion-blocked/duplicate-prevention cases are explicitly covered throughout).

### Special Implementation Checks

Brownfield project (existing CodePlane codebase) — no starter-template requirement applies. Brownfield indicators present throughout: Story 1.1 explicitly preserves the existing `Job`/`JobSummary` schema and consumers; Story 3.1 explicitly preserves existing `SidecarTemplateRow` validation; integration points with existing systems (`GitService`, `codeplane_approval`, `merge_service._create_pr`) are named in nearly every story.

### Quality Assessment Summary

- 🔴 Critical Violations: none
- 🟠 Major Issues: none
- 🟡 Minor Concerns: 1 (Story 1.5 forward-reference AC wording, non-blocking)

## Summary and Recommendations

### Overall Readiness Status

**READY**

### Critical Issues Requiring Immediate Action

None. Zero critical or major violations across document discovery, FR/NFR extraction, epic coverage, UX alignment, and epic quality review.

### Recommended Next Steps

1. (Optional, cosmetic) Reword Story 1.5's second AC bullet to state the generic-filter implementation requirement as a design note rather than an Epic-3-dependent testable assertion — see Epic Quality Review for exact wording.
2. Proceed to implementation starting with Epic 1 (Project-based organization), Story 1.1 — it has no unresolved dependencies and establishes `ProjectRow`, the foundation every later epic builds on.
3. Consider running `bmad-sprint-planning` next to sequence the 23 stories into sprints, now that readiness is confirmed.

### Final Note

This assessment found 1 issue (a Minor Concern, non-blocking) across 4 validation categories (document discovery, FR/NFR coverage, UX alignment, epic quality). All 14 FRs and 9 NFRs trace to specific stories with testable acceptance criteria; no epic requires a later epic to function; no technical-milestone epics exist; database/entity creation is deferred to first need throughout. The spec/architecture/UX/epics artifact set is ready for implementation as-is; the one Minor Concern may be fixed opportunistically but does not block starting Epic 1.

**Assessed:** 2026-08-10, via `bmad-check-implementation-readiness` steps 1-6, against `_bmad-output/specs/spec-project-boards/SPEC.md`, `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md`, `_bmad-output/specs/spec-project-boards/ui-flows.md`, and `_bmad-output/planning-artifacts/epics.md`.





