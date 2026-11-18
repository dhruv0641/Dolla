# TASK-027: Credit quote, reservation and limits

- **Parent epic:** EPIC-06 — Credit and Account Management
- **Assigned agent:** Credit and Account Engineer
- **Priority:** P0
- **Dependencies:** TASK-026
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#97](https://github.com/dhruv0641/Dolla/issues/97); branch `feature/TASK-027-credit-quote-reservation-limits` targets `develop`.
- **Related source documents:** SCHEMA.sql; FLOW_MCP_ADAPTER_CONTRACT.json
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want credit quote, reservation and limits, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver credit quote, reservation and limits as an independently verifiable capability within credit and account management.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and explicit injected dependencies; it remains disabled without quote, approval, and limit configuration.
- [x] Errors, reservation states, idempotency, balance freshness, row locking, and security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; live external integration is not claimed without verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Implementation checkpoint — 2026-11-19
- Started after TASK-026 implementation and tracker closeout were merged to `develop`; dependency TASK-026 is DONE.
- Issue [#97](https://github.com/dhruv0641/Dolla/issues/97) opened and branch `feature/TASK-027-credit-quote-reservation-limits` created from the latest `develop`.
- Reviewing supplied credit schema/contract and existing account-registry/Flow adapter boundaries. No Flow operation, generation, account change, or paid action has been performed.

## Implementation checkpoint — 2026-11-19 (resume)
- Added the typed quote and explicit spend-approval service, account-scoped transactional reservation repository, API boundary, and migration `0003_flow_credit_reservations.sql`.
- Hardened the final insert path to recheck quote expiry and observed-balance freshness after database waits while the account row remains locked. Provider quote references and requested model/duration are bounded and reject malformed values.
- Added operator documentation in `docs/CREDIT_QUOTE_RESERVATIONS.md`. No live Flow quote/balance endpoint is available in the discovered capability matrix, so no provider, rate, or balance is fabricated and the API remains unavailable by default.
- Focused reservation tests: 18 passed. Full Python suite: 212 passed. All SQL migrations parse with `pglast`; the project-plan validator reports 15 epics/76 tasks/76 dependency nodes/no cycles; `git diff --check` passes. Independent Technical Reviewer found no blockers. GitHub CI, live PostgreSQL execution, and provider integration remain outstanding.
