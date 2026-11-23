# TASK-060: Independent platform state and reconciliation

- **Parent epic:** EPIC-12 — Social Publishing
- **Assigned agent:** Publishing Integration Engineer
- **Priority:** P2
- **Dependencies:** TASK-059
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#189](https://github.com/dhruv0641/Dolla/issues/189)
- **Branch:** `feature/TASK-060-independent-platform-state-reconciliation`
- **Blockers:** No blocker for disabled-by-default local implementation. Live provider reconciliation requires separately authorized OAuth accounts and remains outside development verification.

## User Story
As a FLOW AI Content OS operator, I want independent platform state and reconciliation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver independent platform state and reconciliation as an independently verifiable capability within social publishing.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
- `src/flowx_os/publishing/reconciliation.py`
- `src/flowx_os/db/publication_reconciliation.py`
- `migrations/0021_platform_publication_reconciliation.sql`
- `docs/PLATFORM_PUBLICATION_RECONCILIATION.md`
- focused domain, repository, configuration and migration tests

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors, state transitions and security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Implementation evidence
- Added a disabled-by-default, provider-injected read-only reconciliation service
  that requires the exact existing remote object identity and never invokes a
  publisher mutation or changes `publication_jobs` workflow state.
- Provider observations must echo request, publication, platform, destination
  and remote-object identities and satisfy bounded freshness plus platform URL
  rules. Raw provider responses, errors and credential references are not
  persisted.
- Migration 0021 adds monotonic publication state versions, durable bounded
  pre-read reservations and immutable idempotent reconciliation history.
  Persistence locks and rechecks the full owner/channel/contract/destination/
  local-state snapshot after the remote read. Repository and SQL guards derive
  the only valid verdict and reject forged or unrelated evidence.
- Divergence and unknown verdicts require human review; exact completed request
  replays return without another provider call.
- Current local verification: 127 focused reconciliation/publishing/config/
  migration tests pass; all 22 migration files parse, compileall, diff hygiene
  and the 76-task dependency validator pass. Independent review and the final
  full suite remain pending.
- No live PostgreSQL execution, OAuth/account connection, provider observation,
  upload, publication, scheduling, deletion, paid operation or public action was
  performed or claimed.
