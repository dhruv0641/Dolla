# TASK-007: Data access and transaction boundaries

- **Parent epic:** EPIC-02 — Database and Persistence
- **Assigned agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-006
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want data access and transaction boundaries, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver data access and transaction boundaries as an independently verifiable capability within database and persistence.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/db/transaction.py`, `tests/test_transactions.py`, `docs/DATABASE_TRANSACTIONS.md`, README and project trackers.

## Acceptance Criteria
- [x] Async unit-of-work helper acquires/releases a pooled connection and commits or rolls back one transaction.
- [x] No automatic retries or network side effects occur inside the transaction boundary.
- [x] Unit tests verify connection release, commit, and rollback.
- [x] Operator docs state supported pool/connection shape and integration limits.
- [ ] CI passes.

## Tests and Verification
- Run `python -m unittest discover -s tests -v` and `python scripts/validate_project_plan.py`.
- Record PR and GitHub Actions evidence in this specification and `docs/IMPLEMENTATION_PLAN.md`.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/14
- Branch: `feature/TASK-007-data-access-and-transactions`
- Pull request: pending
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
