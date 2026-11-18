# TASK-029: Concurrency, pause and reset tracking

- **Parent epic:** EPIC-06 — Credit and Account Management
- **Assigned agent:** Credit and Account Engineer
- **Priority:** P0
- **Dependencies:** TASK-028
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** DONE
- **Related source documents:** SCHEMA.sql; FLOW_MCP_ADAPTER_CONTRACT.json
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want concurrency, pause and reset tracking, so the platform can progress safely through a traceable production lifecycle.

## Execution checkpoint — 2026-11-19
- TASK-028 is DONE through PR [#102](https://github.com/dhruv0641/Dolla/pull/102), merged to `develop` as `707310f`; tracker closeout PR #103 and post-merge validation also passed.
- Issue [#104](https://github.com/dhruv0641/Dolla/issues/104) closed through PR [#105](https://github.com/dhruv0641/Dolla/pull/105), merged to `develop` as `d91e400`; required PR checks and post-merge `validate-project-plan` passed.
- Branch `feature/TASK-029-concurrency-pause-reset-tracking` was based on `develop` at `fc679ba`.
- Existing account-row locking, active-reservation counting, monotonic pause, and reset-window checks were inspected. This task adds fail-closed behavior for missing reset/cycle evidence and a regression for a daily reset crossed during a database wait.

## Objective
Deliver concurrency, pause and reset tracking as an independently verifiable capability within credit and account management.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors, state transitions and security boundaries are explicit; missing or crossed reset windows prevent new reservations.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Focused reservation suite: 24 tests pass, including missing reset/cycle evidence and a reset crossed during the active-reservation query wait.
- Full Python suite: 229 tests pass. Project-plan validation reports 15 epics/76 tasks/no cycles; compileall and `git diff --check` pass.
- Independent Technical Reviewer found no blockers in reset checks, account row locking, active reservation counting, or owner-scoped monotonic pause behavior.
- Independent Technical Reviewer found no blockers. PR [#105](https://github.com/dhruv0641/Dolla/pull/105) and post-merge checks passed.
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
