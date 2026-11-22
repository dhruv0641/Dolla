# TASK-046: Deterministic integrity checks

- **Parent epic:** EPIC-10 — Video Quality Assurance
- **Assigned agent:** QA and Security Engineer
- **Priority:** P1
- **Dependencies:** TASK-034, TASK-045
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **GitHub issue:** [#165](https://github.com/dhruv0641/Dolla/issues/165)
- **Branch:** `feature/TASK-046-deterministic-integrity-checks`
- **Blockers:** None for local implementation. Live environment evidence must be reported separately if unavailable.

## User Story
As a FLOW AI Content OS operator, I want deterministic integrity checks, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver deterministic integrity checks as an independently verifiable capability within video quality assurance.

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

## Implementation and acceptance evidence

- `MediaIntegrityService` binds owner-scoped final/export metadata to a strict expectation and emits a PASS/FAIL report with closed, stably ordered finding codes and a canonical SHA-256 evidence fingerprint.
- The bounded managed-media probe now reports sanitized container, frame-rate, H.264 profile, pixel format and subtitle evidence while preserving full hash and decode verification.
- Checks cover declared fingerprint/profile, managed digest, decode, MP4 container, exact video/audio/subtitle stream counts and codecs, dimensions, FPS, profile, `yuv420p` and duration tolerance. Unsafe tool text is redacted.
- Migration 0013 and `IntegrityReportRepository` persist one immutable owner-scoped `integrity-v1` report per active same-content render artifact. Exact replay is idempotent; rebinding fails closed; no invented score is stored.
- `docs/MEDIA_INTEGRITY_QA.md` records the trust boundary, checks, recovery and separation from visual, policy, human approval and publishing.
- 18 focused tests and 38 combined QA/probe/render regressions pass, including a real H.264/AAC/mov_text fixture.
- Full application suite: 377 passed. Migration suite: 13 passed, including parsing every migration with `pglast` (390 total).
- Compileall, diff hygiene, and project validation (15 epics, 76 tasks, no cycles) pass.
- Live PostgreSQL trigger/locking execution and production media-volume behavior remain unverified and are not claimed.
- Independent Technical Reviewer: pending against the exact implementation commit.
