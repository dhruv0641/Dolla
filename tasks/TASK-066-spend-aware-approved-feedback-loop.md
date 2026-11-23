# TASK-066: Spend-aware approved feedback loop

- **Parent epic:** EPIC-13 — Analytics and Growth
- **Assigned agent:** Analytics Engineer
- **Priority:** P2
- **Dependencies:** TASK-065
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub issue:** [#207](https://github.com/dhruv0641/Dolla/issues/207)
- **Branch:** `feature/TASK-066-spend-aware-approved-feedback-loop`
- **Pull request:** [#208](https://github.com/dhruv0641/Dolla/pull/208), merged to `develop` as `af91b19232721b2748f252a927f886dc35525779`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want spend-aware approved feedback loop, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver spend-aware approved feedback loop as an independently verifiable capability within analytics and growth.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] One exact immutable TASK-065 proposal is bound to an owned credit reservation, explicit experiment approval, separate `video_generate` spend approval and hard credit cap.
- [x] Current account health, pause/compliance state, balance/reset/cycle freshness, active credits/concurrency, reservation/quote state and open unknown-spend alarms are rechecked transactionally after locks; unknown or mismatched state fails closed.
- [x] Immutable expiring attestations and revocations use a dedicated trusted writer capability; the ordinary gate runtime cannot create approval evidence.
- [x] Approval records do not grant durable execution authority: a separate executor must freshly revalidate the exact reservation, approvals, account, alarms, capability and job state.
- [x] Post-gate outcomes accept only owner/factor/platform/metric/window/registry/arm-compatible descriptive reports whose actual publications, metric windows and observations are strictly post-approval and meet fixed targets.
- [x] Decisions and outcomes are immutable, owner-scoped, canonical, versioned and insert-or-read idempotent; conflicting replay and direct-write substitutions fail.
- [x] Results remain descriptive/non-causal and any new recommendation requires separate human review.
- [x] Errors, state transitions, statistical/privacy limits and no-external-action boundaries are explicit and documented.

## Tests and Verification
- Focused feedback/recommendation/credit/alarm/repository/migration suite: **80 passed**.
- Single final full suite: **639 passed**.
- Independent Caveman review accepted the corrected exact diff with no critical, P1 or P2 findings.
- PostgreSQL parsing: **28 migrations / 272 statements** passed in the independent review environment.
- `compileall`, diff hygiene and project validator passed (15 epics, 76 tasks, no cycles).
- Live PostgreSQL, approval stores, account/provider state and paid execution remain unverified and are not claimed.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
