# TASK-061: Approval, schedule and duplicate prevention

- **Parent epic:** EPIC-12 — Social Publishing
- **Assigned agent:** Publishing Integration Engineer
- **Priority:** P2
- **Dependencies:** TASK-060
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#192](https://github.com/dhruv0641/Dolla/issues/192)
- **Branch:** `feature/TASK-061-approval-schedule-duplicate-prevention`
- **Blockers:** No blocker for disabled-by-default local implementation. Live scheduling and publication require separately authorized platform accounts and remain outside development verification.

## User Story
As a FLOW AI Content OS operator, I want approval, schedule and duplicate prevention, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver approval, schedule and duplicate prevention as an independently verifiable capability within social publishing.

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

## Implementation Evidence

- `PublicationSchedulingService` provides explicit owner approval and disabled-by-default, timezone-safe scheduling with structured failures and bounded policy.
- Migration `0022_publication_approval_schedule_duplicate_prevention.sql` stores immutable exact approvals and reservations, serializes channel limits, rejects stale/reconciled evidence, and atomically reserves the first provider mutation.
- YouTube, Instagram, and Facebook readiness checks require the due approval/reservation and reject human-review reconciliation evidence before provider authorization.
- `docs/PUBLICATION_APPROVAL_AND_SCHEDULING.md` records configuration, DST, idempotency, recovery, and live-verification limits.
- Initial focused verification passed 141 tests. Independent Caveman review then rejected head `c1ebbc8` with four findings: no due-event consumer, invalid local-day bounds when midnight is skipped, moving-clock replay rejection, and approval expiry blocking already-reserved recovery.
- Corrections add `ScheduledPublicationDispatcher`, exact leased reservation reload and injected platform executors; compute local-day boundaries from the first valid civil instant; load exact idempotent replays before moving gates; and apply approval expiry only before the atomic dispatch reservation. The expanded focused publishing/reconciliation/scheduling/workflow/configuration/migration gate passes **158 tests**. All 23 migrations parse, `compileall`, diff hygiene, and the 76-node project validator pass.
- No live PostgreSQL, OAuth, account, concrete provider executor, upload, scheduling, publication, paid, or public action was performed. Exact correction-head independent re-review and the one final full suite remain pending.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
