---
baseline_commit: 4e662805
---

# Story 4.3: Manually assign a task to an existing ticket

Status: in-progress

## Story

As a CodePlane user with a tracker ticket that has no BMAD/spec-kit backing,
I want to create a task recipe node directly against that ticket with my own prompt,
so that I can automate work the ticket describes without first authoring a planning document.

## Acceptance Criteria

1. **Given** a Project with an attached TrackerLink showing synced tickets, **when** I pick an existing ticket and create a TaskLink against it with a free-form prompt, **then** a `TaskLink` is created with `tracker_ticket_ref` and `prompt_override` set, and `story_node_id` left null.
2. **Given** a ticket already has one manually-assigned TaskLink, **when** I create a second TaskLink against the same ticket, **then** both TaskLinks exist independently; many TaskLinks may share one `tracker_ticket_ref`.
3. **Given** a manually-assigned TaskLink, **when** I view it later, **then** nothing requires it to ever gain a `story_node_id`; it remains valid indefinitely without BMAD/spec-kit backing.

## Tasks / Subtasks

- [ ] Task 1: Add manual TaskLink persistence and service behavior on top of Story 4.2 (AC: 1, 2, 3)
  - [ ] Extend Story 4.2's TaskLink repository/service rather than adding a second model, table, migration, or execution entity.
  - [ ] Create a fresh row per request with `tracker_ticket_ref` and `prompt_override` set; leave `story_node_id`, `job_id`, and `epic_id` null and initialize `depends_on` empty.
  - [ ] Preserve multiplicity: do not upsert or enforce uniqueness by `tracker_ticket_ref`.
  - [ ] Validate the target Project and repo membership using existing Project patterns; do not call tracker provider write APIs or expose credentials.
- [ ] Task 2: Expose manual assignment through the Project TaskLink API (AC: 1, 2, 3)
  - [ ] Add a camelCase request/response contract to the existing `/settings/projects/{project_id}/task-links` surface established by Story 4.2.
  - [ ] Keep the route thin: validate the request, delegate to `recipe_service.py`, and map existing domain errors consistently.
  - [ ] Return the persisted nullable fields so a later read proves `story_node_id` and `epic_id` remain null.
- [ ] Task 3: Add comprehensive automated coverage (AC: 1, 2, 3)
  - [ ] Unit-test manual row creation, independent rows sharing a ticket ref, Project/repo validation, null story/Epic/job fields, and persistence across a later read.
  - [ ] Integration-test the POST contract, camelCase serialization, validation failures, multiplicity, and GET visibility through the existing TaskLink list endpoint.
  - [ ] Run the smallest relevant TaskLink/Project/TrackerLink regression suites plus configured lint and type checks.

## Dev Notes

### Dependency and Scope Boundary

- Story 4.2 owns the canonical `TaskLinkRow`, migration, repository, ingestion path, `recipe_service.py`, and TaskLink list endpoint. Story 4.3 must rebase onto that work and extend it. If Story 4.2 is not yet available, tests and request contracts may be scaffolded, but no duplicate `TaskLinkRow`, `task_links` table, migration, or parallel service may be introduced.
- Story 4.1 widened the sidecar vocabulary; do not modify that validator here.
- Story 3.2 provides Project-to-Credential `TrackerLinkRow` attachment. This story does not implement tracker synchronization, polling, ticket mutation, board rendering, job spawning, or frontend UI.
- The acceptance criteria establish that the ticket was picked from already-visible synced state. The manual-create path records the selected `tracker_ticket_ref`; it must not invent tracker network I/O or a second ticket read model.

### Architecture Compliance

- AD-9 defines one thin Project-scoped `TaskLinkRow`: `id`, `project_id`, `repo_path`, nullable `story_node_id`, `depends_on`, nullable `job_id`, nullable `tracker_ticket_ref`, nullable `prompt_override`, and nullable `epic_id`.
- Exactly one of `story_node_id` or `tracker_ticket_ref` must be non-null at creation. For this manual path, `tracker_ticket_ref` is required and `story_node_id` is null.
- Manual TaskLinks never receive an inferred `epic_id`; it is null because no BMAD Epic is the source.
- Many TaskLinks may share one `tracker_ticket_ref`. Only ingestion upserts by `(project_id, repo_path, story_node_id)`; manual assignment always inserts a new row.
- `TaskLinkRow` is correlation state, not a competing run model. This story does not create a `JobRow`.
- All database access remains behind persistence repositories; API handlers stay thin; response models use `CamelModel`.
- Use `/settings/projects/{project_id}/task-links`, matching AD-11 and the existing `projects.py` route convention.

### Existing Code to Extend and Preserve

- `backend/api/projects.py`: existing Project CRUD routes use `DishkaRoute`, `FromDishka`, generated/backend schema models, and `ProjectService`. Extend Story 4.2's TaskLink routes here rather than creating a competing URL family.
- `backend/services/project/project_service.py` and `backend/persistence/project_repo.py`: reuse their Project lookup and repo-membership semantics; a manual TaskLink must target a repo that belongs to its Project.
- `backend/api/tracker_links.py` and `backend/persistence/tracker_link_repo.py`: preserve credential secrecy and existing TrackerLink attachment behavior. Manual TaskLink assignment stores only a ticket reference, never a credential or PAT.
- `backend/models/api_schemas.py`: remains the backend API contract source; frontend generated types are out of scope unless Story 4.2 has already established another TaskLink schema location.
- Existing Project, TrackerLink, credential, chat, sidecar, and job behavior must remain unchanged.

### Testing Requirements

- Follow current async pytest patterns with in-memory SQLite for repository/service tests and the integration `client` fixture for HTTP behavior.
- Prove both independent rows survive a fresh list/read query; checking only two POST response IDs is insufficient for AC2/AC3.
- Assert nullable fields explicitly and verify no `JobRow` is created as a side effect.
- Reject empty `tracker_ticket_ref`, empty `prompt_override`, unknown Projects, and repo paths outside the Project using existing validation/error conventions.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-43-Manually-assign-a-task-to-an-existing-ticket`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md#CAP-9`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-9`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane-2026-08-10/ARCHITECTURE-SPINE.md#AD-11`]
- [Source: `_bmad-output/implementation-artifacts/3-2-attach-a-trackerlink-to-a-project.md`]
- [Source: `_bmad-output/implementation-artifacts/4-1-widen-the-task-recipe-vocabulary.md`]

## Dev Agent Record

### Agent Model Used

GPT-5.6 Sol (GitHub Copilot CLI).

### Debug Log References

### Completion Notes List

- Comprehensive implementation context created from Epic 4, CAP-9, AD-9/AD-11, and existing Project/TrackerLink patterns.

### File List

## Change Log

- 2026-08-10: Story created with explicit Story 4.2 dependency boundary and manual-assignment guardrails.
