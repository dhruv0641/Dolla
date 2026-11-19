# TASK-023: Auth and account health

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-022
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#85](https://github.com/dhruv0641/Dolla/issues/85) closed by tracker PR [#112](https://github.com/dhruv0641/Dolla/pull/112), merged to `develop` as `b13cab9`; implementation PR [#86](https://github.com/dhruv0641/Dolla/pull/86) merged as `3520bed` with pre-merge and post-merge CI success; independent Technical Reviewer review passed.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **External prerequisite:** Satisfied for this task by direct Flow account-panel inspection and the user's explicit confirmation that the identity shown in Flow is acceptable. The address itself is intentionally omitted from repository docs.
- **Remaining external state:** The old image job remains in `sent` with unknown final outcome. TASK-024 owns safe reconciliation; no retry or new generation is authorized by this identity confirmation.

## User Story
As a FLOW AI Content OS operator, I want auth and account health, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver auth and account health as an independently verifiable capability within google flow mcp integration.

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
- [x] Unsupported or unverified server capabilities fail closed.

## Implementation checkpoint — 2026-11-18
- Added `src/flowx_os/flow_mcp/account_health.py`: non-secret health snapshots, explicit health states and an injected provider/service boundary.
- Authorization is minted only by `FlowAccountHealthService` after it reads and type-checks its injected provider evidence. The proof includes check/expiry timestamps, and the adapter rejects future/expired proof on every call. It requires fresh, connected, logged-in, explicitly identity-verified evidence matching the configured opaque account reference. Missing/throwing/malformed providers, stale evidence, logged-out state, unknown identity and mismatches deny authorization with sanitized stable errors.
- No email, cookie, token or browser storage is accepted in health snapshots or status payloads.
- Authorization is short-lived and rechecked immediately before the adapter transport call, after asynchronous manifest/approval gates complete.
- Verification: `python -m unittest tests.test_flow_account_health tests.test_flow_mcp_adapter -v` — 24 passed; full suite — 181 passed; project-plan validation — 15 epics/76 tasks/no cycles; `git diff --check` — clean.
- Independent Technical Reviewer re-review passed with no remaining code blockers. PR #86 is merged, and post-merge GitHub CI passed. On 2026-11-19, the Flow account details panel identity was shown directly and the user explicitly confirmed it is acceptable. Exact account address is omitted. This completes TASK-023 identity acceptance; it does not resolve the separate stale job or configure the application transport.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
