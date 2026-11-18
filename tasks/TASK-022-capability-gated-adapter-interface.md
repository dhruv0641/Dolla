# TASK-022: Capability-gated adapter interface

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-021
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Completion scope:** Adapter-boundary implementation only; no live transport or generation is configured.
- **GitHub:** Issue [#83](https://github.com/dhruv0641/Dolla/issues/83); draft PR [#84](https://github.com/dhruv0641/Dolla/pull/84) targets `develop`; implementation branch `feature/TASK-022-capability-gated-adapter-interface`.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want capability-gated adapter interface, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver capability-gated adapter interface as an independently verifiable capability within google flow mcp integration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and disabled-by-default configuration.
- [x] Errors, account/operation authorization, freshness gates and supported schema validation are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.
- [x] Unsupported or unverified server capabilities fail closed.

## Implementation and review evidence — 2026-11-18
- Added `src/flowx_os/flow_mcp/` capability models and transport-injected adapter. No Codex host MCP endpoint is assumed or wired into the application.
- Adapter defaults to disabled and checks configured server/account identity, explicit verification, manifest age, observed tool bindings, input schema values, and sanitized transport/result failures.
- Recursively immutable schemas accept only the supported JSON Schema subset; unsupported or malformed schema constraints fail closed.
- Spending operations require an account- and operation-scoped approval plus an injected trusted `SpendAuthorizationVerifier`. There is no verifier or transport configured in the running app; actual credit cost enforcement remains unverified, so no production generation claim is made.
- Operator limits: [`docs/FLOW_MCP_ADAPTER.md`](../docs/FLOW_MCP_ADAPTER.md); runtime capability evidence: [`docs/MCP_CAPABILITY_MATRIX.md`](../docs/MCP_CAPABILITY_MATRIX.md).
- Local verification: `python -m unittest tests.test_flow_mcp_adapter -v` — 13 passed; `python -m unittest discover -s tests` — 170 passed; `python scripts/validate_project_plan.py` — 15 epics/76 tasks/76 dependency nodes/no cycles; `git diff --check` — clean.
- Independent Technical Reviewer re-review: no remaining blocker for this adapter-boundary scope. Reviewer confirmed schema immutability/validation and trusted, scoped spend approval checks. Live Flow transport and generation were not tested or invoked.
- GitHub CI: PR #84 is open as draft; `validate-project-plan` is still running for head `62b9a2bb642500c1a29e15891416271def7ad38a`. Keep IN_REVIEW until required CI completes and PR is merged.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
