# TASK-062: Platform metrics and definitions

- **Parent epic:** EPIC-13 — Analytics and Growth
- **Assigned agent:** Analytics Engineer
- **Priority:** P2
- **Dependencies:** TASK-006, TASK-057, TASK-060
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub issue:** [#195](https://github.com/dhruv0641/Dolla/issues/195)
- **Pull request:** [#196](https://github.com/dhruv0641/Dolla/pull/196)
- **Branch:** `feature/TASK-062-platform-metrics-definitions`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want platform metrics and definitions, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver platform metrics and definitions as an independently verifiable capability within analytics and growth.

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

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Implementation Evidence

- Added a strict 22-entry `platform-metrics-v1` registry for YouTube,
  Instagram and Facebook. Raw names, units, provider definitions, official
  references, missing-value policy and versioned derived denominators remain
  platform-specific; the canonical registry fingerprint is
  `b994293e90e26358aa2ad15628be4a7b6fac7f53e035bf189b76c16452f6a7e5`.
- Added disabled-by-default collection contracts for the five fixed
  publish-relative windows. Each observation binds the owner-authorized
  publication target, platform, destination, remote object, source, window,
  registry and exact requested raw metric set. Missing values require a null
  plus an enumerated reason and cannot be silently replaced with zero.
- Added owner-scoped, replay-safe repository persistence and migration `0023`.
  The record path rechecks the locked published object, never persists the
  credential reference, and uses immutable attempt/observation triggers with
  exact identity and missing-value envelope checks.
- Added `FLOWX_PLATFORM_ANALYTICS_ENABLED=false`, operator documentation and
  official provider-definition references. No provider adapter, OAuth session,
  live read, account connection or external action was configured or invoked.
- Focused verification after independent-review corrections: `python -m unittest -q
  tests.test_metric_definitions tests.test_metric_collection
  tests.test_metric_observation_repository tests.test_config
  tests.test_migrations tests.test_publication_reconciliation
  tests.test_publication_reconciliation_repository` — 80 tests passed.
  `python -m compileall -q src`, `git diff --check`, PostgreSQL parsing through
  the migration suite and `python scripts/validate_project_plan.py` also pass.
- Caveman rejected the first review head because database evidence did not yet
  validate unit-specific JSON shapes or derive its fingerprint, and freshness
  used the clock sampled before the provider call. The correction adds an
  immutable database registry, raw/platform/unit validation for every datum,
  bounded scalar and structured values, database-derived observation
  fingerprints returned to the application, and a fresh post-provider clock
  sample with a slow-provider regression.
- Correction-head re-review accepted those two fixes but found the seeded SQL
  definition registry still allowed later inserts. The follow-up seals all
  definition inserts after migration seeding and enforces metric namespace to
  platform agreement, so the fingerprinted registry cannot be extended.
- Caveman accepted exact head `7c879e4e81d07c44bae857d3b89640a654e4ac92`
  after verifying the registry is seeded before its insert/update/delete guard,
  all prior findings are closed, and no critical/P1/P2 finding remains.
- The single final full suite passed all 596 tests. Remaining gate: GitHub
  PR/required CI and protected-branch merge. Production PostgreSQL and live
  provider behavior remain explicitly unverified.
