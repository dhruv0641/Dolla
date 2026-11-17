# TASK-012: Brand and content lifecycle APIs

- **Parent epic:** EPIC-03 — Backend and Orchestration
- **Assigned agent:** Backend Engineer
- **Priority:** P1
- **Dependencies:** TASK-011
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want brand and content lifecycle apis, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver brand and content lifecycle apis as an independently verifiable capability within backend and orchestration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Authenticated operators/admins can create brands; authorized read roles can list only brands belonging to the token subject.
- [x] Authenticated operators/admins can create content under an owned brand; authorized read roles can list content only for an owned brand.
- [x] Owner predicates are applied in parameterized repository SQL; absent and foreign-owned brand IDs return the same safe 404.
- [x] Inputs enforce field bounds, known timezone names and non-blank required fields; missing/unavailable database responses fail closed.
- [x] API contract, limitations and verification state are documented in `docs/CONTENT_API.md`.
- [x] Local API/repository test suite (56 tests), project-plan validation, compilation and diff whitespace checks pass.
- [ ] GitHub CI passes, PR is merged to `develop`, and reviewer evidence is recorded.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Mock-boundary API tests cover authentication, owner subject propagation, response mapping, input validation and unconfigured database behavior.
- Repository tests assert parameterized owner filters and hide foreign-owned brands as not found.
- Record actual commands/results; live PostgreSQL integration is not available in this environment and is required before claiming production readiness.

## Definition of Done
Implementation is in progress on `feature/TASK-012-brand-and-content-lifecycle-apis`; issue [#24](https://github.com/dhruv0641/Dolla/issues/24). PR/CI/review evidence will be recorded here and in the single development log.
