---
baseline_commit: bbf31746
---

# Story 4.1: Widen the Task Recipe vocabulary

Status: review

## Story

As a CodePlane user relying on existing sidecar templates,
I want the recipe schema to support chained, tracker-aware task recipes,
so that new chaining capability is additive and never breaks my existing sidecars.

## Acceptance Criteria

1. **Given** an existing `SidecarTemplateRow` with a pre-existing `lifetime`/`outputRoutes`/`contextSources` value, **when** the schema validation function is updated, **then** `chained`, `spawn_task`, `tracker_write`, `story_node`, and `tracker_ticket` are accepted as new valid values, and every existing template continues to validate and run unchanged.
2. **And** no new schema table, version flag, or migration is introduced — the same `definition_json` column is reused.

## Tasks / Subtasks

- [x] Add `chained` to `_ALLOWED_LIFETIMES`, `spawn_task`/`tracker_write` to `_ALLOWED_OUTPUT_ROUTES`, and `story_node`/`tracker_ticket` to `_ALLOWED_CONTEXT_SOURCES` in `backend/services/sidecar/template_service.py`.
- [x] Verify no schema table/migration/version flag is introduced — `definition_json` column reused as-is.
- [x] Add/extend tests proving new values validate and existing values still validate unchanged.
- [x] Run targeted test suite and lint.

## Dev Notes

- CAP-8 (SPEC.md) / AD-8 (ARCHITECTURE-SPINE.md): widen `_ALLOWED_LIFETIMES`/`_ALLOWED_OUTPUT_ROUTES`/`_ALLOWED_CONTEXT_SOURCES` in the existing `_validate_definition` function in `template_service.py`. No new schema table, version flag, or migration — `SidecarTemplateRow.definition_json` is reused unchanged.
- Scope is strictly the schema/validation widening. Do NOT implement TaskLink, ingestion (Story 4.2), ticket assignment (4.3), board rendering (4.4), auto-spawn (4.5), or tracker-write routing (4.6) — those are separate, dependent stories.
- Existing constants: `_ALLOWED_CONTEXT_SOURCES`, `_ALLOWED_OUTPUT_ROUTES`, `_ALLOWED_LIFETIMES` in `backend/services/sidecar/template_service.py`.
- Existing tests: `backend/tests/unit/test_sidecar_template_service.py`.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-41-Widen-the-Task-Recipe-vocabulary`]
- [Source: `_bmad-output/specs/spec-project-boards/SPEC.md#CAP-8`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-codeplane 2026-08-10/ARCHITECTURE-SPINE.md#AD-8`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (GitHub Copilot CLI).

### Debug Log References

- `python -m pytest backend/tests/unit/test_sidecar_template_service.py -q` -> 38 passed
- `python -m ruff check backend/services/sidecar/template_service.py backend/tests/unit/test_sidecar_template_service.py` -> All checks passed
- `python -m pytest backend/tests/unit -k "sidecar" -q` -> 130 passed, 3080 deselected (no regressions)

### Completion Notes

Widened the existing `_validate_definition` vocabulary in `backend/services/sidecar/template_service.py`
per CAP-8/AD-8, purely additively:
- `_ALLOWED_LIFETIMES` gained `chained`.
- `_ALLOWED_OUTPUT_ROUTES` gained `spawn_task`, `tracker_write`.
- `_ALLOWED_CONTEXT_SOURCES` gained `story_node`, `tracker_ticket`.

No new schema table, version flag, or migration was introduced; `SidecarTemplateRow.definition_json`
is unchanged and reused as-is. No TaskLink, ingestion, board rendering, auto-spawn, or tracker-write
routing logic was touched — those remain scoped to Stories 4.2–4.6. Extended
`test_sidecar_template_service.py`'s `TestConstants` with explicit assertions for the new values;
the existing parametrized `test_valid_lifetimes`/`test_valid_output_routes`/`test_valid_context_sources`
tests already iterate these constants so they automatically cover the new values end-to-end through
`_validate_definition`.

## File List

- `backend/services/sidecar/template_service.py` (modified)
- `backend/tests/unit/test_sidecar_template_service.py` (modified)
- `_bmad-output/implementation-artifacts/4-1-widen-the-task-recipe-vocabulary.md` (added)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified)

## Change Log

- Story created.
- Implemented CAP-8/AD-8 vocabulary widening; all targeted tests and lint pass; story marked for review.
