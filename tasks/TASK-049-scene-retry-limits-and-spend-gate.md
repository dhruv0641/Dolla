# TASK-049: Scene retry limits and spend gate

- **Parent epic:** EPIC-10 — Video Quality Assurance
- **Assigned agent:** QA and Security Engineer
- **Priority:** P1
- **Dependencies:** TASK-048
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **GitHub issue:** [#174](https://github.com/dhruv0641/Dolla/issues/174)
- **Branch:** `feature/TASK-049-scene-retry-limits-spend-gate`
- **Blockers:** None for bounded local implementation; live spend/account state and paid retry execution must remain unavailable without explicit authorization.

## User Story
As a FLOW AI Content OS operator, I want scene retry limits and spend gate, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver scene retry limits and spend gate as an independently verifiable capability within video quality assurance.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
QA retry-decision service, existing scene retry and credit-reservation contracts, idempotent persistence/migration if needed, focused tests and operator documentation. Reuse rather than bypass TASK-027 through TASK-030 and TASK-033; select exact paths after targeted inspection.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors, state transitions and security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- `python -m unittest tests.test_retry_spend_gate tests.test_generation_jobs tests.test_scene_retry_policy tests.test_credit_reservations tests.test_credit_ledger tests.test_credit_alarms tests.test_flow_jobs tests.test_migrations` — 98 passed.
- `python -m unittest discover -s tests` — 432 passed.
- `python -m compileall -q src tests`, `python scripts/validate_project_plan.py`, and `git diff --check` passed; all 16 migrations parse through the migration test.
- Evidence covers owner preflight before approval, exact approval/reservation binding, account → reservation → job/scene lock order, bounded attempts, stale/malformed spend denial, idempotent replay, direct-SQL gate shape and immutability.
- Live PostgreSQL concurrency, real approval-provider behavior, actual retry execution and paid Flow generation remain unverified and unauthorized.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
