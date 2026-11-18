# TASK-030: Unknown-spend alarms and fail-closed controls

- **Parent epic:** EPIC-06 — Credit and Account Management
- **Assigned agent:** Credit and Account Engineer
- **Priority:** P0
- **Dependencies:** TASK-029
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** SCHEMA.sql; FLOW_MCP_ADAPTER_CONTRACT.json
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want unknown-spend alarms and fail-closed controls, so the platform can progress safely through a traceable production lifecycle.

## Execution checkpoint — 2026-11-19
- TASK-029 is DONE through PR [#105](https://github.com/dhruv0641/Dolla/pull/105), merged as `d91e400`; tracker closeout PR #106 and its post-merge validation passed.
- Issue [#107](https://github.com/dhruv0641/Dolla/issues/107) is linked to draft PR [#108](https://github.com/dhruv0641/Dolla/pull/108); commit `894452e` is pushed on implementation branch `feature/TASK-030-unknown-spend-alarms-fail-closed-controls`, based on `develop` at `20b9d94`.
- Inspection found reservations can enter `RECONCILE_PENDING` in the schema and remain capacity-held, but no service transition, durable alarm record, or operator alarm read route exists. External alert delivery is not configured.
- Implemented typed unknown-spend reason/state contracts, transactional reservation hold + account pause + durable alarm + workflow event, owner-scoped open-alarm listing, migration `0005`, and operator documentation. No alarm resolve/unpause or external delivery route is included.

## Objective
Deliver unknown-spend alarms and fail-closed controls as an independently verifiable capability within credit and account management.

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
- [x] Errors, state transitions and security boundaries are explicit; uncertain spend keeps the hold and pauses the account.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Focused alarm and migration suite: 17 tests pass, covering transactional transition/event writes, duplicate idempotency, reason conflict, owner scoping, closed/missing reservations, API roles/responses, and SQL parsing.
- Full Python suite: 241 tests pass. Project-plan validation reports 15 epics/76 tasks/no cycles; compileall and `git diff --check` pass.
- Independent Technical Reviewer re-review passes: authenticated principal is the only API actor source; `user:{subject}` is persisted consistently in `created_by` and the workflow event. The explicit system actor is reserved for trusted internal callers. No other acceptance/security blocker found.
- CI and post-merge checks remain pending. PostgreSQL execution and external alert delivery remain unverified and are not claimed.
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
