# TASK-028: Observed credit ledger and reconciliation

- **Parent epic:** EPIC-06 — Credit and Account Management
- **Assigned agent:** Credit and Account Engineer
- **Priority:** P0
- **Dependencies:** TASK-027
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** SCHEMA.sql; FLOW_MCP_ADAPTER_CONTRACT.json
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## Readiness and execution checkpoint — 2026-11-19
- TASK-027 is DONE through merged implementation and owner-preflight PRs; this task's sole dependency is satisfied.
- Issue [#101](https://github.com/dhruv0641/Dolla/issues/101) is open; implementation branch is `feature/TASK-028-observed-credit-ledger-reconciliation`, based on `develop` at `b6bf701`.
- Initial slice implemented: typed provider/domain contract, owner-preflight service, transactional repository for daily/monthly observations, replay-safe ledger keys and fingerprints, authenticated API routes, migration `0004`, and operator documentation.
- No Flow balance provider is available. The reconciliation API fails closed by default; unit tests currently use synthetic provider evidence and database fakes. PostgreSQL and live Flow integration remain unverified.

## User Story
As a FLOW AI Content OS operator, I want observed credit ledger and reconciliation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver observed credit ledger and reconciliation as an independently verifiable capability within credit and account management.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration; the provider is injected and absent by default.
- [x] Errors, state transitions and security boundaries are explicit; owner checks precede provider calls and database writes lock the account.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Focused credit-ledger and migration suite: 15 tests pass, including provider fail-closed behavior, owner-preflight ordering, invalid/stale evidence, transaction queries, replay handling, API redaction and SQL parsing.
- Full Python suite: 227 tests pass. Project-plan validator reports 15 epics/76 tasks/no cycles; compileall and `git diff --check` pass.
- Independent Technical Reviewer found no remaining code blocker after verifying the under-lock freshness check and 11-minute wait regression test.
- PR [#102](https://github.com/dhruv0641/Dolla/pull/102) targets `develop`; both required GitHub `validate-project-plan` checks pass. Post-merge validation remains pending.
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
