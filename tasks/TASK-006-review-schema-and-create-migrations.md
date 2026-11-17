# TASK-006: Review schema and create migrations

- **Parent epic:** EPIC-02 — Database and Persistence
- **Assigned agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-001
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want review schema and create migrations, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver review schema and create migrations as an independently verifiable capability within database and persistence.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`migrations/0001_initial_schema.sql`, `docs/SCHEMA_REVIEW.md`, README and project trackers. The supplied SQL is a reference design; the checked-in migration adds review corrections.

## Acceptance Criteria
- [x] PostgreSQL 15+ baseline migration creates the reviewed schema with explicit ordering and FK constraints.
- [x] Schema findings cover tenant/RLS, lineage, secrets, payload/error retention, credit semantics, event identity, deletion and leases.
- [x] README/operator docs explain one-time forward-only migration handling and deployment prerequisites.
- [x] Migration parsed by PostgreSQL grammar parser (33 statements); local PostgreSQL server/client is unavailable, so execution is not claimed.
- [ ] CI installs the parser and validates the migration syntax on each change.
- [ ] CI passes.

## Tests and Verification
- Run `python scripts/validate_project_plan.py`; validate SQL syntax and apply on disposable PostgreSQL if tooling is available.
- Record PR and CI evidence in this specification and `docs/IMPLEMENTATION_PLAN.md`.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/12
- Branch: `feature/TASK-006-review-schema-and-create-migrations`
- Pull request: pending
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
