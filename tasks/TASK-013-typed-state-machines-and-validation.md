# TASK-013: Typed state machines and validation

- **Parent epic:** EPIC-03 — Backend and Orchestration
- **Assigned agent:** Backend Engineer
- **Priority:** P1
- **Dependencies:** TASK-012
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want typed state machines and validation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver typed state machines and validation as an independently verifiable capability within backend and orchestration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Content lifecycle statuses are represented by a `StrEnum` aligned with the database status constraint.
- [x] All allowed state edges are explicit; skipped, terminal and unknown transitions are rejected.
- [x] State changes require operator/admin authorization, target an owned content item, and serialize concurrent transitions under a row lock.
- [x] API responses distinguish malformed target (`422`), invalid transition (`409`), hidden missing/foreign content (`404`) and unavailable database (`503`).
- [x] Generic operator transitions cannot set `PUBLISHED` or `PARTIALLY_PUBLISHED`; those require a future trusted publisher with verified remote evidence.
- [x] Generic transitions cannot change scheduler/publisher-managed states or restart failed content without an artifact reset workflow.
- [x] Transition policy and live database verification limits are documented in `docs/CONTENT_STATE_MACHINE.md`.
- [x] All 72 backend tests, plan validation, compileall, diff checks, frontend typecheck/build and dependency audit pass locally.
- [x] Local tests, project-plan validator, frontend CI-equivalent checks, compileall and diff checks pass.
- [ ] GitHub CI passes, independent review completes, and PR [#30](https://github.com/dhruv0641/Dolla/pull/30) merges to `develop`.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Domain tests cover the forward lifecycle, explicit rework/failure edges, skipped transitions, terminal states, and the publication evidence gate.
- Repository/API tests cover owner-scoped locking/update, invalid transition rejection without mutation, safe errors, and enum validation.
- Live PostgreSQL integration is unavailable; do not claim database concurrency behavior is production-verified. GitHub CI and independent technical review remain pending.

## Definition of Done
Implementation is submitted on `feature/TASK-013-typed-state-machines-and-validation`; issue [#29](https://github.com/dhruv0641/Dolla/issues/29), PR [#30](https://github.com/dhruv0641/Dolla/pull/30). Reviewer findings on publication evidence, scheduler coordination and failed-artifact reset are addressed in the current unmerged follow-up; refreshed CI and reviewer confirmation are pending.
