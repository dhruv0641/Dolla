# TASK-010: Backup, restore and retention

- **Parent epic:** EPIC-02 — Database and Persistence
- **Assigned agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-009
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want backup, restore and retention, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver backup, restore and retention as an independently verifiable capability within database and persistence.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/maintenance/backups.py`, `tests/test_backups.py`, `docs/BACKUP_RESTORE.md`, README and trackers.

## Acceptance Criteria
- [x] Backup uses PostgreSQL custom format, protected service-file credentials, and archive verification before reporting success.
- [x] Backup manifest records size, SHA-256, service alias and UTC creation time.
- [x] Restore verifies checksum, uses one transaction, and does not drop/clean the target.
- [x] Retention planning is dry-run only and preserves a minimum latest-backup count.
- [x] Tests use mocks/temp directories and do not access a real database or delete user data.
- [x] Operator docs record unverified live backup/restore and production deployment requirements.
- [ ] CI passes.

## Tests and Verification
- Run `python -m unittest discover -s tests -v` and `python scripts/validate_project_plan.py`.
- Record PR and GitHub Actions evidence in this specification and `docs/IMPLEMENTATION_PLAN.md`.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/20
- Branch: `feature/TASK-010-backup-restore-and-retention`
- Pull request: https://github.com/dhruv0641/Dolla/pull/21
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
