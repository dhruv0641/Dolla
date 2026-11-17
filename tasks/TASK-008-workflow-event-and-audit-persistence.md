# TASK-008: Workflow event and audit persistence

- **Parent epic:** EPIC-02 — Database and Persistence
- **Assigned agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-007
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** DONE
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want workflow event and audit persistence, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver workflow event and audit persistence as an independently verifiable capability within database and persistence.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/db/workflow_events.py`, `tests/test_workflow_events.py`, `docs/WORKFLOW_EVENTS.md`, README and project trackers.

## Acceptance Criteria
- [x] Events persist through parameterized SQL inside caller-owned transactions.
- [x] Event identity, UUIDs, JSON encoding and payload size are validated before database access.
- [x] Tests verify parameterization and reject invalid/oversized payloads without database writes.
- [x] Operator documentation defines authorization, redaction, and polymorphic entity limitations.
- [x] CI passes on PR and push events.

## Tests and Verification
- Run `python -m unittest discover -s tests -v` and `python scripts/validate_project_plan.py`.
- Record PR and GitHub Actions evidence in this specification and `docs/IMPLEMENTATION_PLAN.md`.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/16
- Branch: `feature/TASK-008-workflow-event-audit-persistence`
- Pull request: https://github.com/dhruv0641/Dolla/pull/17
- CI runs: passing on head `9ad0d5ceb6253a66042c015f522759e4cf09924a`
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
