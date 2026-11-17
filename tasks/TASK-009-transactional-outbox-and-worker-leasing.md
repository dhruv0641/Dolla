# TASK-009: Transactional outbox and worker leasing

- **Parent epic:** EPIC-02 — Database and Persistence
- **Assigned agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-008
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want transactional outbox and worker leasing, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver transactional outbox and worker leasing as an independently verifiable capability within database and persistence.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`migrations/0002_outbox_idempotency.sql`, `src/flowx_os/db/outbox.py`, `tests/test_outbox.py`, `tests/test_migrations.py`, `docs/WORKER_OUTBOX.md`, README and trackers.

## Acceptance Criteria
- [x] Outbox enqueue is transactional and idempotent by a unique key.
- [x] Leasing uses `FOR UPDATE SKIP LOCKED`, reclaims expired leases, and enforces limits.
- [x] Completion is conditional on current lease owner; lost leases are explicit.
- [x] Tests cover insert idempotency, safe concurrent lease query construction, UTC time validation, and lease ownership.
- [x] Operator docs describe lifecycle limits and forbid side effects before lease commit.
- [ ] CI validates code and both SQL migrations.

## Tests and Verification
- Run `python -m unittest discover -s tests -v` and `python scripts/validate_project_plan.py`.
- Record PR and GitHub Actions evidence in this specification and `docs/IMPLEMENTATION_PLAN.md`.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/18
- Branch: `feature/TASK-009-transactional-outbox-and-leasing`
- Pull request: pending
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
