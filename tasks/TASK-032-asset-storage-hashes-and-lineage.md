# TASK-032: Asset storage, hashes and lineage

- **Parent epic:** EPIC-07 — Scene and Media Management
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-031
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#122](https://github.com/dhruv0641/Dolla/issues/122); branch `feature/TASK-032-asset-storage-hashes-and-lineage`.
- **Related source documents:** SCHEMA.sql; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want asset storage, hashes and lineage, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver asset storage, hashes and lineage as an independently verifiable capability within scene and media management.

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
- [x] Errors, state transitions and security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.
- Evidence: `python -m unittest discover -s tests -q` — 297 tests passed; focused asset/storage/repository/API/migration suite — 37 tests passed; `python scripts/validate_project_plan.py` — 15 epics/76 tasks/no dependency cycles; `python -m compileall -q src tests`; `git diff --check`.
- Independent Technical Reviewer passed after UUID-to-URI binding, pre-write authorization and signature-scope documentation corrections. PostgreSQL migration execution, locking, and production persistent-volume behavior remain unverified.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
