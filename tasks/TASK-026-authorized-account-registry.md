# TASK-026: Authorized account registry

- **Parent epic:** EPIC-06 — Credit and Account Management
- **Assigned agent:** Credit and Account Engineer
- **Priority:** P0
- **Dependencies:** TASK-006, TASK-021
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#94](https://github.com/dhruv0641/Dolla/issues/94); branch `feature/TASK-026-authorized-account-registry` targets `develop`.
- **Related source documents:** SCHEMA.sql; FLOW_MCP_ADAPTER_CONTRACT.json
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want authorized account registry, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver authorized account registry as an independently verifiable capability within credit and account management.

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

## Implementation checkpoint — 2026-11-19
- Started after TASK-006 and TASK-021 were confirmed DONE; TASK-056 is fully merged and closed out.
- Reviewed `SCHEMA.sql`, `FLOW_MCP_ADAPTER_CONTRACT.json`, the repository's initial migration, account-health adapter boundary, and capability matrix. The registry will store opaque account references and secret references only; verified identity, pause and authorization gates remain distinct.
- Issue [#94](https://github.com/dhruv0641/Dolla/issues/94) opened; implementation and verification are in progress. No account connection, account switch, remote operation, generation or paid action was performed.
- Added an owner-scoped PostgreSQL repository and authenticated create/list/pause API. New records are explicitly unverified and paused; response models omit owner and credential references. Raw credential values are rejected, duplicate aliases and storage failures use sanitized errors. Pause is owner-scoped, idempotent and one-way; no caller can unpause or self-assert verification.
- A focused security test initially found FastAPI validation errors echoing submitted raw credentials. Added a global validation response handler that retains field-level error metadata while removing submitted input and context values; the regression test now passes.
- Follow-up independent review identified that global alias uniqueness could expose cross-owner alias existence, and that reference syntax validation did not prove a reference existed. Added migration `0002_flow_account_owner_alias.sql` for owner-scoped uniqueness, changed the repository conflict target, and clarified that reference validation is syntax-only. The issue description and operator docs now distinguish syntax from approval/verification.
- Operator boundaries are in [`docs/FLOW_ACCOUNT_REGISTRY.md`](../docs/FLOW_ACCOUNT_REGISTRY.md). Focused registry tests (11), migration tests (3), and the full suite (193 tests) pass. Project-plan validation reports 15 epics/76 task specs/no cycles and `git diff --check` is clean. Independent reviewer found no blockers after the alias/reference corrections. Live PostgreSQL/provider integration is not configured or claimed; PR/CI remains pending.
