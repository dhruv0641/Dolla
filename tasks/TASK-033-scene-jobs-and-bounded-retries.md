# TASK-033: Scene jobs and bounded retries

- **Parent epic:** EPIC-07 — Scene and Media Management
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-032
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#125](https://github.com/dhruv0641/Dolla/issues/125); branch `feature/TASK-033-scene-jobs-and-bounded-retries`.
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want scene jobs and bounded retries, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver scene jobs and bounded retries as an independently verifiable capability within scene and media management.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration, including bounded retries (two regenerations after the initial attempt).
- [x] Errors, state transitions and security boundaries are explicit and observable; unknown Flow submission outcomes remain BLOCKED and are never retried automatically.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

### Current evidence
- `python -m unittest discover -s tests -q`: 307 passed.
- Focused retry/job/policy/migration suite: 48 passed; generation job + retry policy regression subset: 14 passed.
- `python scripts/validate_project_plan.py`: 15 epics, 76 task specs, no dependency cycles.
- All migration SQL parses with `pglast`; `python -m compileall -q src tests` and `git diff --check` pass.
- Independent Technical Reviewer found no blockers after the historical retry-decision replay regression was fixed.
- PostgreSQL migration execution/locking and live Flow job operations are not verified; no Flow calls or paid operations were made.
- Required GitHub CI is pending on the implementation PR.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
