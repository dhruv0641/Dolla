# TASK-075: Encrypted backups and runbooks

- **Parent epic:** EPIC-15 — Security Observability and Deployment
- **Assigned agent:** DevOps Engineer
- **Priority:** P2
- **Dependencies:** TASK-074
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#75](https://github.com/dhruv0641/Dolla/issues/75) closed by PR [#76](https://github.com/dhruv0641/Dolla/pull/76), merged to `develop` as `b1b9e8d`; branch `feature/TASK-075-encrypted-backups-runbooks`.
- **Related source documents:** ARCHITECTURE; SCHEMA.sql
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want encrypted backups and runbooks, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver encrypted backups and runbooks as an independently verifiable capability within security observability and deployment.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/maintenance/backups.py` will stream `pg_dump` through age encryption and decrypt directly into `pg_restore`, requiring a public recipient and an externally mounted identity file. `docs/BACKUP_RESTORE.md` will document key custody and recovery drills. No plaintext dump may be written to disk.

## Acceptance Criteria
- [x] Capability streams PostgreSQL custom dumps through age encryption without plaintext files; restores first authenticate a private ciphertext snapshot, then decrypt it to transactional `pg_restore` stdin.
- [x] No-overwrite publication, least-privilege process environments, finite configurable timeouts, cleanup, manifest checksum/size checks and dry-run encrypted retention define the main safety boundaries.
- [x] Operator runbooks describe key custody, recovery, retention and known limits; no live integration or production-readiness claim is made without verification.

## Tests and Verification
- `python -m unittest tests.test_backups -v` — 10 tests passed, including no-overwrite publication and an authentication failure before any restore call.
- `python -m unittest discover -s tests` — 157 tests passed.
- `python -m compileall -q src tests` — passed.
- `python scripts/validate_project_plan.py` — 15 epics and 76 task specs validated; no dependency cycles.
- `git diff --check` — passed; only Git's LF/CRLF normalization warnings were reported.
- Technical Reviewer re-review — no blockers; confirmed the restore authentication, race, environment, cleanup and timeout findings are resolved.
- Live `pg_dump`/`pg_restore`/age/database recovery remains unverified because the tools, database and identity are not configured in this environment.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
