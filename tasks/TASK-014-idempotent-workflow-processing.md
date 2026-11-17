# TASK-014: Idempotent workflow processing

- **Parent epic:** EPIC-03 — Backend and Orchestration
- **Assigned agent:** Backend Engineer
- **Priority:** P1
- **Dependencies:** TASK-013
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want idempotent workflow processing, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver idempotent workflow processing as an independently verifiable capability within backend and orchestration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Leased jobs map to a validated typed contract with a stable job-ID idempotency key.
- [x] Only explicitly registered event handlers can run; unknown events and non-owning workers fail closed.
- [x] Handler database/outbox writes and job completion share one transaction; handler failure, lease loss, or lease expiry rolls back both.
- [x] Handler contract prohibits external/non-transactional side effects; retries rely on transactional writes and stable idempotency keys.
- [x] Retry/dead-letter timing remains owned by TASK-015 and no external processing is claimed.
- [x] All 79 backend tests, plan validation, compileall, diff checks, frontend typecheck/build and dependency audit pass locally.
- [ ] Tests, validator, CI and independent review pass; PR is merged to `develop`.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Fake-pool tests cover atomic handler+ack success, handler rollback, stale lease rollback, unknown event/worker denial and leased-row mapping.
- Local verification: `python -m unittest discover -s tests -v` (78 passed); `python scripts/validate_project_plan.py`; `python -m compileall -q src tests`; `git diff --check`; frontend typecheck/build/audit.
- No live PostgreSQL/worker deployment is available; do not claim end-to-end processing or external effect idempotency.

## Definition of Done
Implementation is in progress on `feature/TASK-014-idempotent-workflow-processing`; issue [#31](https://github.com/dhruv0641/Dolla/issues/31). Evidence will be recorded here and in the single development log.
